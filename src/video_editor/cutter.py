"""時間軸規劃、非線性拼接編譯與無損影片匯出模組。"""

import subprocess
from pathlib import Path
from typing import List, Tuple

from video_editor.config import EditorConfig
from video_editor.models import EditPlan, format_timestamp


class VideoCutter:
    """處理時間軸計算、跨段無縫拼接規劃與實際切片輸出的執行器。"""

    def __init__(self, config: EditorConfig):
        self.config = config

    @staticmethod
    def calculate_valid_segments(
        total_duration: float, freeze_ranges: List[Tuple[float, float]]
    ) -> List[Tuple[float, float]]:
        """扣除暫離區間，合併產出有效內容區間。"""
        if not freeze_ranges:
            return [(0.0, total_duration)]

        sorted_freezes = sorted(freeze_ranges, key=lambda x: x[0])
        merged_freezes: List[Tuple[float, float]] = []
        for start, end in sorted_freezes:
            if not merged_freezes or start > merged_freezes[-1][1]:
                merged_freezes.append((start, end))
            else:
                merged_freezes[-1] = (
                    merged_freezes[-1][0],
                    max(merged_freezes[-1][1], end),
                )

        valid_segments: List[Tuple[float, float]] = []
        current_time = 0.0

        for f_start, f_end in merged_freezes:
            if f_start > current_time:
                valid_segments.append((current_time, f_start))
            current_time = max(current_time, f_end)

        if current_time < total_duration:
            valid_segments.append((current_time, total_duration))

        return [seg for seg in valid_segments if seg[1] - seg[0] > 1.0]

    @staticmethod
    def find_natural_cut_point(
        window_start: float,
        window_end: float,
        transitions: List[float],
        silences: List[Tuple[float, float]],
        ideal_cut: float,
        require_transition: bool = True,
    ) -> float:
        """
        在搜尋窗口內尋找最自然的切點。
        若 require_transition 為 True，強制只在黑色或白色轉場畫面進行分割，
        絕不因單純台詞語音停頓而腰斬劇情對話。
        """
        transitions_in_window = [
            t for t in transitions if window_start <= t <= window_end
        ]

        if transitions_in_window:
            scored_trans: List[Tuple[float, float]] = []
            for t in transitions_in_window:
                dist = abs(t - ideal_cut)
                score = 1000.0 - (dist / 60.0) * 10.0

                has_silence = any(
                    s_start - 1.0 <= t <= s_end + 1.0 for s_start, s_end in silences
                )
                if has_silence:
                    score += 200.0

                scored_trans.append((score, t))

            scored_trans.sort(key=lambda x: x[0], reverse=True)
            return scored_trans[0][1]

        if require_transition and transitions:
            future_trans = [t for t in transitions if t > window_end]
            if future_trans:
                return future_trans[0]

            past_trans = [t for t in transitions if t < window_start]
            if past_trans:
                return past_trans[-1]

        if not require_transition or not transitions:
            silence_candidates: List[Tuple[float, float]] = []
            for s_start, s_end in silences:
                if s_end < window_start or s_start > window_end:
                    continue

                cut_t = (s_start + s_end) / 2.0
                if cut_t < window_start or cut_t > window_end:
                    cut_t = max(window_start, min(window_end, s_start + 0.1))

                duration = s_end - s_start
                score = 100.0 + min(50.0, duration * 25.0)
                score -= (abs(cut_t - ideal_cut) / 60.0) * 8.0
                silence_candidates.append((score, cut_t))

            if silence_candidates:
                silence_candidates.sort(key=lambda x: x[0], reverse=True)
                return silence_candidates[0][1]

        return window_end

    @staticmethod
    def plan_slices(
        valid_segments: List[Tuple[float, float]],
        transitions: List[float],
        silences: List[Tuple[float, float]],
        min_len: float,
        max_len: float,
        max_overtime: float = 180.0,
        require_transition: bool = True,
        detector: object = None,
    ) -> List[Tuple[float, float]]:
        """
        在有效區間內規劃每集切片時間段。
        若 require_transition 為 True，強制只在黑色或白色轉場畫面進行分割。
        """
        planned_slices: List[Tuple[float, float]] = []

        for seg_start, seg_end in valid_segments:
            seg_len = seg_end - seg_start
            if seg_len <= max_len:
                planned_slices.append((seg_start, seg_end))
                continue

            seg_transitions = [t for t in transitions if seg_start <= t <= seg_end]
            seg_silences = [
                s for s in silences if seg_start <= s[0] and s[1] <= seg_end
            ]

            sub_start = seg_start
            while sub_start < seg_end:
                remaining = seg_end - sub_start
                if remaining <= max_len:
                    planned_slices.append((sub_start, seg_end))
                    break

                target_window_start = sub_start + min_len
                target_window_end = min(seg_end, sub_start + max_len + max_overtime)
                ideal_cut = sub_start + (min_len + max_len) / 2.0

                cut_time = VideoCutter.find_natural_cut_point(
                    window_start=target_window_start,
                    window_end=target_window_end,
                    transitions=seg_transitions,
                    silences=seg_silences,
                    ideal_cut=ideal_cut,
                    require_transition=require_transition,
                )

                if cut_time <= sub_start:
                    cut_time = min(seg_end, sub_start + max_len)

                if detector is not None and hasattr(detector, "find_nearest_keyframe"):
                    try:
                        kf = detector.find_nearest_keyframe(cut_time, search_window=2.0)
                        if (
                            kf is not None
                            and abs(kf - cut_time) <= 2.5
                            and kf > sub_start
                            and kf < seg_end
                        ):
                            cut_time = kf
                    except Exception:
                        pass

                planned_slices.append((sub_start, cut_time))
                sub_start = cut_time

        return planned_slices

    @staticmethod
    def merge_contiguous_ranges(
        ranges: List[Tuple[float, float]], tolerance: float = 0.05
    ) -> List[Tuple[float, float]]:
        """僅在相鄰區間於原始時間軸上剛好首尾相接且順序一致時合併，保留重排與跨段刪除結構。"""
        if not ranges:
            return []
        merged: List[Tuple[float, float]] = [ranges[0]]
        for start, end in ranges[1:]:
            prev_start, prev_end = merged[-1]
            if abs(start - prev_end) <= tolerance and end > prev_end:
                merged[-1] = (prev_start, end)
            else:
                merged.append((start, end))
        return merged

    @staticmethod
    def compile_export_groups(
        plan: EditPlan,
        transitions: List[float],
        silences: List[Tuple[float, float]],
        max_overtime: float = 180.0,
        require_transition: bool = True,
        detector: object = None,
    ) -> List[List[Tuple[float, float]]]:
        """
        將 EditPlan 中保留且依 sequence 排序的段落，編譯為最終輸出檔案的區間群組清單。
        每個內層 List[Tuple[float, float]] 代表一個最終輸出的 MP4 檔案（若含多段則以 concat 無損拼接）。
        """
        raw_ranges = plan.get_kept_ordered_ranges()
        if not raw_ranges:
            return []

        merged_ranges = VideoCutter.merge_contiguous_ranges(raw_ranges)

        # 模式 1: single -> 所有保留片段按順序無縫拼接為單一完整檔
        if plan.export_mode == "single":
            return [merged_ranges]

        # 模式 2: clips -> 每個保留段落各自獨立匯出成一個檔案
        if plan.export_mode == "clips":
            return [[r] for r in merged_ranges]

        # 模式 3: episodes -> 將保留片段無縫拼接，並依 target_min_part_len ~ target_max_part_len 自動分集
        min_len = plan.target_min_part_len
        max_len = plan.target_max_part_len
        episodes: List[List[Tuple[float, float]]] = []
        current_ep: List[Tuple[float, float]] = []
        current_dur = 0.0

        queue: List[Tuple[float, float]] = list(merged_ranges)
        while queue:
            r_start, r_end = queue.pop(0)
            r_len = r_end - r_start
            if r_len <= 0.1:
                continue

            # 若放入當前集數後仍未超過 max_len，直接併入本集
            if current_dur + r_len <= max_len:
                current_ep.append((r_start, r_end))
                current_dur += r_len
                continue

            # 若當前集數已達 min_len，且加上這段會超過 max_len，先將當前集數封裝完成
            if current_dur >= min_len and current_ep:
                episodes.append(current_ep)
                current_ep = []
                current_dur = 0.0
                queue.insert(0, (r_start, r_end))
                continue

            # 需要在當前 (r_start, r_end) 內部尋找切點以湊滿本集
            needed_min = max(1.0, min_len - current_dur)
            needed_max = max(needed_min, max_len - current_dur)

            seg_transitions = [t for t in transitions if r_start <= t <= r_end]
            seg_silences = [
                s for s in silences if r_start <= s[0] and s[1] <= r_end
            ]

            target_window_start = r_start + needed_min
            target_window_end = min(r_end, r_start + needed_max + max_overtime)
            ideal_cut = r_start + (needed_min + needed_max) / 2.0

            cut_time = VideoCutter.find_natural_cut_point(
                window_start=target_window_start,
                window_end=target_window_end,
                transitions=seg_transitions,
                silences=seg_silences,
                ideal_cut=ideal_cut,
                require_transition=require_transition,
            )

            if cut_time <= r_start:
                cut_time = min(r_end, r_start + needed_max)

            if (
                cut_time < r_end
                and detector is not None
                and hasattr(detector, "find_nearest_keyframe")
            ):
                try:
                    kf = detector.find_nearest_keyframe(cut_time, search_window=2.0)
                    if (
                        kf is not None
                        and abs(kf - cut_time) <= 2.5
                        and r_start < kf < r_end
                    ):
                        cut_time = kf
                except Exception:
                    pass

            if cut_time >= r_end - 1.0:
                current_ep.append((r_start, r_end))
                episodes.append(current_ep)
                current_ep = []
                current_dur = 0.0
            else:
                current_ep.append((r_start, cut_time))
                episodes.append(current_ep)
                current_ep = []
                current_dur = 0.0
                queue.insert(0, (cut_time, r_end))

        if current_ep:
            episodes.append(current_ep)

        return episodes

    def _extract_single_range_copy(
        self, start: float, end: float, out_path: Path
    ) -> None:
        """呼叫 FFmpeg 以 -c copy 流複製技術切出單一連續區間。"""
        cmd = [
            self.config.ffmpeg_bin,
            "-y",
            "-ss",
            str(start),
            "-to",
            str(end),
            "-i",
            str(self.config.video_path),
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            str(out_path),
        ]
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )

    def _concat_ranges_copy(
        self,
        ranges: List[Tuple[float, float]],
        out_path: Path,
        group_idx: int,
    ) -> None:
        """將多個不連續或重排後的區間以 FFmpeg concat demuxer (-c copy) 無損拼接為單一 MP4。"""
        self.config.temp_dir.mkdir(parents=True, exist_ok=True)
        extension = self.config.video_path.suffix or ".mp4"
        temp_parts: List[Path] = []
        concat_list_path = self.config.temp_dir / f"concat_group_{group_idx}.txt"

        try:
            for sub_idx, (s_t, e_t) in enumerate(ranges, start=1):
                part_path = (
                    self.config.temp_dir / f"concat_part_{group_idx}_{sub_idx}{extension}"
                )
                self._extract_single_range_copy(s_t, e_t, part_path)
                temp_parts.append(part_path)

            # 產生 FFmpeg concat demuxer 清單（處理路徑單引號與反斜線以完整支援空白、中文與逗號檔名）
            lines: List[str] = []
            for p in temp_parts:
                posix_str = p.resolve().as_posix().replace("'", "'\\''")
                lines.append(f"file '{posix_str}'")
            concat_list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            cmd = [
                self.config.ffmpeg_bin,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list_path),
                "-c",
                "copy",
                str(out_path),
            ]
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
        finally:
            if not self.config.keep_temp:
                for p in temp_parts:
                    try:
                        if p.exists():
                            p.unlink()
                    except OSError:
                        pass
                try:
                    if concat_list_path.exists():
                        concat_list_path.unlink()
                except OSError:
                    pass

    def export_plan(
        self,
        plan: EditPlan,
        export_groups: List[List[Tuple[float, float]]],
    ) -> List[Path]:
        """根據編譯後的區間群組執行無損匯出（單段直接流複製，多段透過 concat demuxer 無損拼接）。"""
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        output_files: List[Path] = []

        print(
            f"\n▶ 正在以【{plan.export_mode}】模式無損匯出 {len(export_groups)} 個影片檔至 '{self.config.output_dir}'..."
        )

        base_name = self.config.video_path.stem
        extension = self.config.video_path.suffix or ".mp4"

        for idx, group in enumerate(export_groups, start=1):
            total_sec = sum(e - s for s, e in group)
            duration_min = total_sec / 60.0

            if self.config.output_file is not None:
                if len(export_groups) == 1:
                    out_path = self.config.output_file
                    filename = out_path.name
                else:
                    out_stem = self.config.output_file.stem
                    out_suffix = self.config.output_file.suffix or extension
                    filename = f"{out_stem}-{idx}{out_suffix}"
                    out_path = self.config.output_dir / filename
            else:
                if plan.export_mode == "single" and len(export_groups) == 1:
                    filename = f"{base_name}-edited{extension}"
                elif plan.export_mode == "clips":
                    filename = f"{base_name}-clip-{idx}{extension}"
                else:
                    filename = f"{base_name}-{idx}{extension}"

                out_path = self.config.output_dir / filename
            output_files.append(out_path)

            ranges_desc = " + ".join(
                f"[{format_timestamp(s)}~{format_timestamp(e)}]" for s, e in group
            )
            mode_tag = "無損拼接" if len(group) > 1 else "直接流複製"
            print(
                f"  - [{idx}/{len(export_groups)}] 匯出 {filename} ({mode_tag}): "
                f"{ranges_desc} (總長: {duration_min:.2f} 分鐘)"
            )

            if self.config.dry_run:
                continue

            if len(group) == 1:
                s_t, e_t = group[0]
                self._extract_single_range_copy(s_t, e_t, out_path)
            else:
                self._concat_ranges_copy(group, out_path, group_idx=idx)

        if self.config.dry_run:
            print("✔ [Dry-Run] 模擬完成，未實際寫入檔案。")
        else:
            print("✔ 全部影片無損匯出完成！")

        return output_files

    def export_slices(self, slices: List[Tuple[float, float]]) -> List[Path]:
        """呼叫 FFmpeg 使用無損流複製 (-c copy) 快速產出各分段 MP4。"""
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        output_files: List[Path] = []

        print(f"\n▶ 正在輸出 {len(slices)} 個影片分段至 '{self.config.output_dir}'...")

        base_name = self.config.video_path.stem
        extension = self.config.video_path.suffix or ".mp4"

        for idx, (start, end) in enumerate(slices, start=1):
            duration_min = (end - start) / 60.0
            filename = f"{base_name}-{idx}{extension}"
            out_path = self.config.output_dir / filename
            output_files.append(out_path)

            print(
                f"  - [{idx}/{len(slices)}] 匯出 {filename}: "
                f"{start:.1f}s -> {end:.1f}s (片長: {duration_min:.2f} 分鐘)"
            )

            if self.config.dry_run:
                continue

            self._extract_single_range_copy(start, end, out_path)

        if self.config.dry_run:
            print("✔ [Dry-Run] 模擬完成，未實際寫入檔案。")
        else:
            print("✔ 全部分段匯出完成！")

        return output_files
