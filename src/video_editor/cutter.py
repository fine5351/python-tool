"""時間軸規劃與影片切片匯出模組。"""

import subprocess
from pathlib import Path
from typing import List, Tuple

from video_editor.config import EditorConfig


class VideoCutter:
    """處理時間軸計算與實際切片輸出的執行器。"""

    def __init__(self, config: EditorConfig):
        self.config = config

    @staticmethod
    def calculate_valid_segments(
        total_duration: float, freeze_ranges: List[Tuple[float, float]]
    ) -> List[Tuple[float, float]]:
        """扣除暫離區間，合併產出有效內容區間。"""
        if not freeze_ranges:
            return [(0.0, total_duration)]

        # 排序並合併重疊的暫離區間
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
        # 1. 窗口內的黑白轉場點
        transitions_in_window = [
            t for t in transitions if window_start <= t <= window_end
        ]

        if transitions_in_window:
            scored_trans: List[Tuple[float, float]] = []
            for t in transitions_in_window:
                # 離理想目標時間越近越好
                dist = abs(t - ideal_cut)
                score = 1000.0 - (dist / 60.0) * 10.0

                # 若轉場同時落在靜音或語音停頓區間內，額外加分 (代表完美銜接)
                has_silence = any(
                    s_start - 1.0 <= t <= s_end + 1.0 for s_start, s_end in silences
                )
                if has_silence:
                    score += 200.0

                scored_trans.append((score, t))

            scored_trans.sort(key=lambda x: x[0], reverse=True)
            return scored_trans[0][1]

        # 2. 若窗口內無轉場，但有啟用 require_transition
        if require_transition and transitions:
            # 優先搜尋窗口之後最近的轉場點（即便稍微延後，也絕不在對話中腰斬）
            future_trans = [t for t in transitions if t > window_end]
            if future_trans:
                return future_trans[0]

            # 若後面無轉場，但在窗口前附近有轉場
            past_trans = [t for t in transitions if t < window_start]
            if past_trans:
                return past_trans[-1]

        # 3. 若完全無轉場點或未強制轉場：退回檢查語音停頓
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

        # 4. 保底退回窗口上限
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

            # 篩選當前有效區間內的轉場與停頓點
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

                # 若選出的切點過於接近開頭（異常情況），強制至少切出 min_len
                if cut_time <= sub_start:
                    cut_time = min(seg_end, sub_start + max_len)

                # 若提供 detector 且切點在片段內部，嘗試對齊至最近的關鍵影格 (Keyframe)，
                # 確保無損流複製 (-c copy) 切片完全無重疊與雜音
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

            # 使用 -c copy 進行秒級無損切片，並加上 -avoid_negative_ts make_zero 防止時間戳記重疊
            cmd = [
                self.config.ffmpeg_bin,
                "-y",
                "-ss", str(start),
                "-to", str(end),
                "-i", str(self.config.video_path),
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                str(out_path),
            ]
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )

        if self.config.dry_run:
            print("✔ [Dry-Run] 模擬完成，未實際寫入檔案。")
        else:
            print("✔ 全部分段匯出完成！")

        return output_files
