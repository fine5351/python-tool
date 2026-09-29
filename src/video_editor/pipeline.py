"""主處理流程管線模組。"""

from video_editor.config import EditorConfig
from video_editor.cutter import VideoCutter
from video_editor.detector import VideoDetector
from video_editor.verifier import AIVerifier


class VideoEditorPipeline:
    """整合掃描、AI 複審與切片的端到端管線。"""

    def __init__(self, config: EditorConfig):
        self.config = config
        self.detector = VideoDetector(config)
        self.verifier = AIVerifier(config, self.detector)
        self.cutter = VideoCutter(config)

    def run(self) -> None:
        """執行完整剪輯管線。"""
        print(f"=== 開始處理影片: {self.config.video_path.name} ===")

        # 1. 取得總長度
        total_duration = self.detector.get_duration()
        total_minutes = total_duration / 60.0
        print(f"ℹ 影片總時長: {total_minutes:.2f} 分鐘 ({total_duration:.1f} 秒)")

        # 2. 快速特徵掃描 (靜止、黑畫面轉場與音訊語音停頓)
        raw_freezes, raw_blacks = self.detector.detect_freeze_and_black()
        silences = self.detector.detect_silences()

        # 3. AI 視覺複審 (暫離與過場)
        confirmed_freezes = self.verifier.verify_freezes(raw_freezes)
        confirmed_cuts = self.verifier.verify_transitions(raw_blacks)

        # 4. 規劃有效區間與考量語音/動作的自然切點
        valid_segments = self.cutter.calculate_valid_segments(
            total_duration, confirmed_freezes
        )
        slices = self.cutter.plan_slices(
            valid_segments=valid_segments,
            transitions=confirmed_cuts,
            silences=silences,
            min_len=self.config.target_min_part_len,
            max_len=self.config.target_max_part_len,
            max_overtime=self.config.max_search_overtime,
        )

        # 5. 若啟用 AI，對各集切點進行動作定格與畫面穩定度抽檢
        if self.config.enable_ai and len(slices) > 1:
            print("\n▶ 正在進行 AI 切點畫面穩定度審核（確保動作結束與定格）...")
            for idx, (_, end_time) in enumerate(slices[:-1], start=1):
                is_stable = self.verifier.verify_cut_frame_stability(end_time)
                status = "動作已收尾/畫面定格平穩" if is_stable else "稍微伴隨動作或動態"
                print(f"  - 第 {idx} 集結尾 ({end_time:.1f}s): {status}")

        # 6. 匯出分段 MP4
        self.cutter.export_slices(slices)
        print("=== 處理完成 ===\n")
