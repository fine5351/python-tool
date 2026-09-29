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
    ) -> float:
        """
        在搜尋窗口內尋找最自然的切點（優先：語音說完的停頓點 + 動作定格/轉場點）。
        絕不在台詞發音中硬切。
        """
        candidates: List[Tuple[float, float]] = []

        # 1. 檢查落在窗口內的語音停頓/靜音區間
        for s_start, s_end in silences:
            if s_end < window_start or s_start > window_end:
                continue

            # 切點設在靜音區間內部（避免吃音或切到下一個字）
            cut_t = (s_start + s_end) / 2.0
            if cut_t < window_start or cut_t > window_end:
                cut_t = max(window_start, min(window_end, s_start + 0.1))

            duration = s_end - s_start
            score = 100.0  # 基本分數：確保是語音已講完的停頓

            # 停頓時間越長（代表一句話或對話段落告一段落越充分），加分
            score += min(50.0, duration * 25.0)

            # 若 2 秒內伴隨黑畫面過場/讀取，大幅加分（完美過場）
            has_trans = any(abs(t - cut_t) <= 2.0 for t in transitions)
            if has_trans:
                score += 300.0

            # 離理想目標時間越近越好
            dist_to_ideal = abs(cut_t - ideal_cut)
            score -= (dist_to_ideal / 60.0) * 8.0

            candidates.append((score, cut_t))

        # 2. 窗口內的轉場點 (黑畫面)
        for t in transitions:
            if window_start <= t <= window_end:
                dist_to_ideal = abs(t - ideal_cut)
                score = 80.0 - (dist_to_ideal / 60.0) * 8.0
                candidates.append((score, t))

        # 3. 若有找到自然的停頓點，挑選最高分者
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

        # 4. 若無任何停頓點，退回到窗口上限
        return window_end

    @staticmethod
    def plan_slices(
        valid_segments: List[Tuple[float, float]],
        transitions: List[float],
        silences: List[Tuple[float, float]],
        min_len: float,
        max_len: float,
        max_overtime: float = 90.0,
    ) -> List[Tuple[float, float]]:
        """
        在有效區間內規劃每集切片時間段。
        嚴格考量語音是否講完、動作是否做完（優先落在語音停頓與轉場點）。
        """
        planned_slices: List[Tuple[float, float]] = []

        for seg_start, seg_end in valid_segments:
            seg_len = seg_end - seg_start
            if seg_len <= max_len:
                planned_slices.append((seg_start, seg_end))
                continue

            sub_start = seg_start
            while sub_start < seg_end:
                remaining = seg_end - sub_start
                if remaining <= max_len:
                    planned_slices.append((sub_start, seg_end))
                    break

                target_window_start = sub_start + min_len
                # 允許為了等待話講完或動作做完，最多延後 max_overtime 秒搜尋切點
                target_window_end = min(seg_end, sub_start + max_len + max_overtime)
                ideal_cut = sub_start + (min_len + max_len) / 2.0

                cut_time = VideoCutter.find_natural_cut_point(
                    window_start=target_window_start,
                    window_end=target_window_end,
                    transitions=transitions,
                    silences=silences,
                    ideal_cut=ideal_cut,
                )

                # 若選出的切點過於接近開頭（異常情況），強制至少切出 min_len
                if cut_time <= sub_start:
                    cut_time = min(seg_end, sub_start + max_len)

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

            # 使用 -c copy 進行秒級無損切片
            cmd = [
                self.config.ffmpeg_bin,
                "-y",
                "-ss", str(start),
                "-to", str(end),
                "-i", str(self.config.video_path),
                "-c", "copy",
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
