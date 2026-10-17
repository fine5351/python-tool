"""時間軸、三級模型分流配置與非線性 AI 剪輯重組演算法的單元測試（相容 pytest 與 unittest）。"""

from pathlib import Path
import sys
import tempfile
import unittest

_src_dir = Path(__file__).resolve().parents[1] / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from video_editor.cli import parse_args
from video_editor.config import EditorConfig, ModelConfig
from video_editor.cutter import VideoCutter
from video_editor.detector import VideoDetector
from video_editor.interactive import InteractiveSession
from video_editor.models import EditPlan, TimelineSegment
from video_editor.verifier import AIVerifier


class TestTimeline(unittest.TestCase):
    """時間軸計算、三級模型配置與非線性剪輯重組測試案例。"""

    def test_calculate_valid_segments_no_freeze(self):
        """無暫離區間時，整段影片應完整保留。"""
        segments = VideoCutter.calculate_valid_segments(
            total_duration=3600.0, freeze_ranges=[]
        )
        self.assertEqual(segments, [(0.0, 3600.0)])

    def test_calculate_valid_segments_with_freezes(self):
        """測試扣除暫離區間，並能自動合併重疊區間。"""
        freeze_ranges = [(100.0, 200.0), (180.0, 250.0), (500.0, 600.0)]
        segments = VideoCutter.calculate_valid_segments(
            total_duration=1000.0, freeze_ranges=freeze_ranges
        )

        expected = [
            (0.0, 100.0),
            (250.0, 500.0),
            (600.0, 1000.0),
        ]
        self.assertEqual(segments, expected)

    def test_plan_slices_short_segment(self):
        """長度未超過最大切片長度時，不應進一步分割。"""
        valid_segments = [(0.0, 1500.0)]  # 25 分鐘
        slices = VideoCutter.plan_slices(
            valid_segments=valid_segments,
            transitions=[1300.0],
            silences=[],
            min_len=1200.0,  # 20 分鐘
            max_len=1800.0,  # 30 分鐘
        )
        self.assertEqual(slices, [(0.0, 1500.0)])

    def test_plan_slices_prefer_transition_point(self):
        """長片段應在 20 ~ 30 分鐘區間內優先選擇轉場點切割。"""
        valid_segments = [(0.0, 3600.0)]  # 60 分鐘
        transitions = [1400.0, 2900.0]
        slices = VideoCutter.plan_slices(
            valid_segments=valid_segments,
            transitions=transitions,
            silences=[],
            min_len=1200.0,
            max_len=1800.0,
        )

        expected = [
            (0.0, 1400.0),
            (1400.0, 2900.0),
            (2900.0, 3600.0),
        ]
        self.assertEqual(slices, expected)

    def test_plan_slices_prefer_speech_pause(self):
        """優先選擇語音停頓點（話已講完），而非在說話中硬切。"""
        valid_segments = [(0.0, 3600.0)]
        silences = [(1500.0, 1501.0)]
        slices = VideoCutter.plan_slices(
            valid_segments=valid_segments,
            transitions=[],
            silences=silences,
            min_len=1200.0,
            max_len=1800.0,
        )
        self.assertEqual(slices[0], (0.0, 1500.5))

    def test_plan_slices_fallback_to_max_len(self):
        """若在目標窗口內沒有任何轉場或停頓點，退回在窗口結束處切割。"""
        valid_segments = [(0.0, 4000.0)]
        slices = VideoCutter.plan_slices(
            valid_segments=valid_segments,
            transitions=[],
            silences=[],
            min_len=1200.0,
            max_len=1800.0,
            max_overtime=0.0,
        )

        expected = [
            (0.0, 1800.0),
            (1800.0, 3600.0),
            (3600.0, 4000.0),
        ]
        self.assertEqual(slices, expected)

    def test_export_slices_naming(self):
        """測試產出的切片檔案名稱格式應為 {原檔名}-{1based-count}.{原副檔名}。"""
        config = EditorConfig(
            video_path=Path("F:/Download/4.6-月升之前,與獸共舞.mp4"),
            output_dir=Path("output_parts"),
            dry_run=True,
        )
        cutter = VideoCutter(config)
        slices = [(0.0, 1200.0), (1200.0, 2400.0)]
        output_files = cutter.export_slices(slices)

        self.assertEqual(len(output_files), 2)
        self.assertEqual(output_files[0].name, "4.6-月升之前,與獸共舞-1.mp4")
        self.assertEqual(output_files[1].name, "4.6-月升之前,與獸共舞-2.mp4")

    def test_plan_slices_force_transition_over_dialogue_pause(self):
        """強制在黑白轉場分割：即使台詞中有停頓，也絕對優先選擇黑白轉場點。"""
        valid_segments = [(0.0, 3600.0)]
        transitions = [1432.0]
        silences = [(1540.8, 1541.5)]
        slices = VideoCutter.plan_slices(
            valid_segments=valid_segments,
            transitions=transitions,
            silences=silences,
            min_len=1200.0,
            max_len=1800.0,
            require_transition=True,
        )
        self.assertEqual(slices[0], (0.0, 1432.0))

    def test_plan_slices_waits_for_future_transition_when_forced(self):
        """強制轉場時，若窗口內無轉場但後續有轉場點，應主動等待並切在該轉場點。"""
        valid_segments = [(0.0, 4000.0)]
        transitions = [1920.0]
        silences = [(1500.0, 1500.8)]
        slices = VideoCutter.plan_slices(
            valid_segments=valid_segments,
            transitions=transitions,
            silences=silences,
            min_len=1200.0,
            max_len=1800.0,
            max_overtime=180.0,
            require_transition=True,
        )
        self.assertEqual(slices[0], (0.0, 1920.0))

    def test_plan_slices_keyframe_snapping(self):
        """測試若提供 detector，切點會自動微調吸附至轉場區間內之關鍵影格。"""

        class MockDetector:
            def find_nearest_keyframe(self, t, search_window=2.0):
                if abs(t - 1432.0) <= 2.0:
                    return 1433.86
                return None

        valid_segments = [(0.0, 3600.0)]
        transitions = [1432.0]
        slices = VideoCutter.plan_slices(
            valid_segments=valid_segments,
            transitions=transitions,
            silences=[],
            min_len=1200.0,
            max_len=1800.0,
            detector=MockDetector(),
        )
        self.assertEqual(slices[0], (0.0, 1433.86))

    def test_three_tier_model_config_and_command_dispatch(self):
        """測試三級職責模型配置 (fast_vision, deep_vision, planner) 與 AGY CLI 參數路由。"""
        models = ModelConfig(
            fast_vision="gemini-2.5-flash-lite",
            deep_vision="gemini-2.5-flash",
            planner="gemini-2.5-pro",
        )
        self.assertEqual(models.get_model("vision-fast"), "gemini-2.5-flash-lite")
        self.assertEqual(models.get_model("deep"), "gemini-2.5-flash")
        self.assertEqual(models.get_model("planner"), "gemini-2.5-pro")

        # 動態切換模型
        models.set_model("planner", "flash")
        self.assertEqual(models.get_model("plan"), "flash")

        config = EditorConfig(video_path=Path("test.mp4"), models=models)
        detector = VideoDetector(config)
        verifier = AIVerifier(config, detector)

        fast_cmd = verifier._build_agy_cmd(
            "check idle", image_path=Path("a.jpg"), role="fast_vision"
        )
        deep_cmd = verifier._build_agy_cmd(
            "inspect range", image_path=Path("b.jpg"), role="deep_vision"
        )
        plan_cmd = verifier._build_agy_cmd("reorder plan", role="planner")

        self.assertIn("--model=gemini-2.5-flash-lite", fast_cmd)
        self.assertIn("--model=gemini-2.5-flash", deep_cmd)
        self.assertIn("--model=flash", plan_cmd)

    def test_cli_parses_model_flags_and_removes_no_ai(self):
        """測試 CLI 參數支援三級模型配置，且已移除舊版機械式 --no-ai 參數。"""
        args = parse_args(
            [
                "-i",
                "sample.mp4",
                "--model-vision-fast",
                "flash_lite_custom",
                "--model-vision-deep",
                "flash_custom",
                "--model-planner",
                "pro_custom",
                "--export-mode",
                "single",
                "-p",
                "只保留最後一次通關",
            ]
        )
        self.assertEqual(args.model_vision_fast, "flash_lite_custom")
        self.assertEqual(args.model_vision_deep, "flash_custom")
        self.assertEqual(args.model_planner, "pro_custom")
        self.assertEqual(args.export_mode, "single")
        self.assertEqual(args.prompt, "只保留最後一次通關")
        self.assertFalse(hasattr(args, "no_ai"))

    def test_edit_plan_nonlinear_operations_and_persistence(self):
        """測試通用 EditPlan 的刪除、切分、修剪、重組順序與 JSON 讀寫。"""
        plan = EditPlan(
            video_path="boss_run.mp4",
            total_duration=1800.0,
            segments=[
                TimelineSegment(id=1, start=0.0, end=300.0, summary="進場劇情"),
                TimelineSegment(id=2, start=300.0, end=600.0, summary="第 1 次挑戰"),
                TimelineSegment(id=3, start=600.0, end=900.0, summary="第 2 次挑戰"),
                TimelineSegment(id=4, start=900.0, end=1400.0, summary="最終成功通關"),
                TimelineSegment(id=5, start=1400.0, end=1800.0, summary="結尾動畫"),
            ],
        )

        # 透過 structured operations 刪除中間重試 (2, 3)、將第 4 段切開、並把精華放到最前面
        ops = [
            {"op": "drop", "segment_ids": [2, 3]},
            {
                "op": "split",
                "segment_id": 4,
                "cut_time": 1100.0,
                "left_summary": "通關前半鋪陳",
                "right_summary": "通關致命一擊精華",
            },
            {"op": "reorder", "sequence": [6, 1, 4, 6, 5]},
            {"op": "set_export", "mode": "single"},
        ]
        plan.apply_operations(ops)

        self.assertEqual(plan.export_mode, "single")
        kept_ranges = plan.get_kept_ordered_ranges()
        # 順序應為: #6 (1100~1400) -> #1 (0~300) -> #4 (900~1100) -> #6 (1100~1400) -> #5 (1400~1800)
        self.assertEqual(
            kept_ranges,
            [
                (1100.0, 1400.0),
                (0.0, 300.0),
                (900.0, 1100.0),
                (1100.0, 1400.0),
                (1400.0, 1800.0),
            ],
        )

        # 測試儲存與載入 JSON
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = Path(tmp_dir) / "plan.json"
            plan.save(json_path)
            loaded = EditPlan.load(json_path)
            self.assertEqual(loaded.get_kept_ordered_ranges(), kept_ranges)
            self.assertEqual(loaded.export_mode, "single")

    def test_compile_export_groups_stitches_across_deleted_middle_segments(self):
        """測試刪除中間片段後，episodes 模式會將前後保留段落無縫拼接成同一集，而非碎成多個小檔。"""
        plan = EditPlan(
            video_path="gameplay.mp4",
            total_duration=2400.0,
            segments=[
                TimelineSegment(id=1, start=0.0, end=600.0, summary="探索", keep=True),
                TimelineSegment(id=2, start=600.0, end=1000.0, summary="剔除段", keep=False),
                TimelineSegment(id=3, start=1000.0, end=1900.0, summary="主線推進", keep=True),
            ],
            export_mode="episodes",
            target_min_part_len=1200.0,  # 20 分鐘
            target_max_part_len=1800.0,  # 30 分鐘
        )
        # 保留段落總長為 600s + 900s = 1500s (25 分鐘)，介於 20~30 分鐘內
        groups = VideoCutter.compile_export_groups(
            plan=plan,
            transitions=[],
            silences=[],
        )
        # 應合併為單一第 1 集，內部由兩段不連續區間組成（交由 concat demuxer 無縫拼接）
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0], [(0.0, 600.0), (1000.0, 1900.0)])

    def test_export_plan_naming_for_single_and_clips_modes(self):
        """測試 export_plan 在 single 與 clips 匯出模式下的輸出檔名規則。"""
        config = EditorConfig(
            video_path=Path("videos/BossFight.mp4"),
            output_dir=Path("output_parts"),
            dry_run=True,
        )
        cutter = VideoCutter(config)

        plan_single = EditPlan(
            video_path="videos/BossFight.mp4",
            total_duration=1000.0,
            export_mode="single",
        )
        files_single = cutter.export_plan(
            plan_single, [[(0.0, 300.0), (600.0, 900.0)]]
        )
        self.assertEqual(len(files_single), 1)
        self.assertEqual(files_single[0].name, "BossFight-edited.mp4")

        plan_clips = EditPlan(
            video_path="videos/BossFight.mp4",
            total_duration=1000.0,
            export_mode="clips",
        )
        files_clips = cutter.export_plan(
            plan_clips, [[(0.0, 300.0)], [(600.0, 900.0)]]
        )
        self.assertEqual(len(files_clips), 2)
        self.assertEqual(files_clips[0].name, "BossFight-clip-1.mp4")
        self.assertEqual(files_clips[1].name, "BossFight-clip-2.mp4")

    def test_interactive_session_slash_model_switch(self):
        """測試在互動對話中使用 /model 指令即時切換工作職責的模型。"""
        config = EditorConfig(video_path=Path("demo.mp4"))
        detector = VideoDetector(config)
        verifier = AIVerifier(config, detector)
        session = InteractiveSession(config, verifier)

        handled = session.handle_slash_command("/model planner flash")
        self.assertTrue(handled)
        self.assertEqual(config.models.planner, "flash")

        handled2 = session.handle_slash_command("/model deep_vision pro")
        self.assertTrue(handled2)
        self.assertEqual(config.models.deep_vision, "pro")


if __name__ == "__main__":
    unittest.main()
