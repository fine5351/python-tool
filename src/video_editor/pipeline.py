"""主處理流程管線模組（整合通用場景索引、互動式對話編修與無損拼接匯出）。"""

from typing import List, Tuple

from video_editor.config import EditorConfig
from video_editor.cutter import VideoCutter
from video_editor.detector import VideoDetector
from video_editor.interactive import InteractiveSession
from video_editor.models import EditPlan
from video_editor.verifier import AIVerifier


class VideoEditorPipeline:
    """整合特徵掃描、AI 通用場景索引、終端機對話重組與無損拼接匯出的端到端管線。"""

    def __init__(self, config: EditorConfig):
        self.config = config
        self.detector = VideoDetector(config)
        self.verifier = AIVerifier(config, self.detector)
        self.cutter = VideoCutter(config)
        self.interactive = InteractiveSession(config, self.verifier)

    def cleanup_temp_frames(self) -> None:
        """清理分析期間產生的暫存影格圖片與 concat 清單。"""
        if self.config.keep_temp:
            return

        if self.config.temp_dir.exists() and self.config.temp_dir.is_dir():
            for item in self.config.temp_dir.iterdir():
                if item.is_file():
                    try:
                        item.unlink()
                    except OSError:
                        pass
            try:
                self.config.temp_dir.rmdir()
            except OSError:
                pass

    def run(self) -> None:
        """執行完整 AI 互動剪輯管線。"""
        if not self.config.output_dir.exists():
            self.config.output_dir.mkdir(parents=True, exist_ok=True)
            print(f"ℹ 預期的輸出目錄不存在，已自動建立: '{self.config.output_dir}'")

        try:
            print(f"=== 開始處理影片: {self.config.video_path.name} ===")
            print(
                f"ℹ AI 職責模型配置: "
                f"fast_vision={self.config.models.fast_vision}, "
                f"deep_vision={self.config.models.deep_vision}, "
                f"planner={self.config.models.planner}"
            )

            total_duration = self.detector.get_duration()
            total_minutes = total_duration / 60.0
            print(f"ℹ 影片總時長: {total_minutes:.2f} 分鐘 ({total_duration:.1f} 秒)")

            confirmed_cuts: List[float] = []
            silences: List[Tuple[float, float]] = []

            if self.config.plan_file is not None and self.config.plan_file.is_file():
                print(f"ℹ 載入既有剪輯計畫檔: '{self.config.plan_file}'")
                plan = EditPlan.load(self.config.plan_file)
                confirmed_cuts = sorted({seg.end for seg in plan.segments[:-1]})
            elif self.config.resolved_plan_file.is_file():
                print(f"ℹ 載入既有剪輯計畫檔: '{self.config.resolved_plan_file}'")
                plan = EditPlan.load(self.config.resolved_plan_file)
                confirmed_cuts = sorted({seg.end for seg in plan.segments[:-1]})
            else:
                # Stage 1: 快速特徵掃描 + AI 通用場景索引建立
                raw_freezes, raw_blacks = self.detector.detect_freeze_and_black()
                silences = self.detector.detect_silences()

                confirmed_freezes = self.verifier.verify_freezes(raw_freezes)
                confirmed_cuts = self.verifier.verify_transitions(raw_blacks)

                plan = self.verifier.build_initial_edit_plan(
                    total_duration=total_duration,
                    confirmed_freezes=confirmed_freezes,
                    confirmed_cuts=confirmed_cuts,
                )

            # Stage 2: 終端機互動對話微調與動態視覺探勘
            should_export = self.interactive.run_loop(plan)
            if not should_export:
                print("=== 流程結束（已儲存剪輯計畫，未執行影片匯出） ===\n")
                return

            # Stage 3: 編譯保留與重組後的區間群組並執行無損匯出
            export_groups = self.cutter.compile_export_groups(
                plan=plan,
                transitions=confirmed_cuts,
                silences=silences,
                max_overtime=self.config.max_search_overtime,
                require_transition=self.config.require_transition,
                detector=self.detector,
            )

            if not export_groups:
                print("⚠ 目前剪輯計畫沒有任何保留的段落，取消匯出。")
                return

            if len(export_groups) > 1 and plan.export_mode == "episodes":
                model_name = self.config.models.get_model("fast_vision")
                print(
                    f"\n▶ 正在進行 AI 切點畫面穩定度審核 (model={model_name})..."
                )
                for idx, group in enumerate(export_groups[:-1], start=1):
                    end_time = group[-1][1]
                    is_stable = self.verifier.verify_cut_frame_stability(end_time)
                    status = (
                        "動作已收尾/畫面定格平穩"
                        if is_stable
                        else "稍微伴隨動作或動態"
                    )
                    print(f"  - 第 {idx} 集結尾 ({end_time:.1f}s): {status}")

            self.cutter.export_plan(plan, export_groups)
            print("=== 處理完成 ===\n")
        finally:
            self.cleanup_temp_frames()
