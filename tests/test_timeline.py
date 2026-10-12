"""時間軸與切片演算法的單元測試（相容 pytest 與 unittest）。"""

import unittest
from video_editor.cutter import VideoCutter


class TestTimeline(unittest.TestCase):
    """時間軸計算與切片演算法測試案例。"""

    def test_calculate_valid_segments_no_freeze(self):
        """無暫離區間時，整段影片應完整保留。"""
        segments = VideoCutter.calculate_valid_segments(
            total_duration=3600.0, freeze_ranges=[]
        )
        self.assertEqual(segments, [(0.0, 3600.0)])

    def test_calculate_valid_segments_with_freezes(self):
        """測試扣除暫離區間，並能自動合併重疊區間。"""
        # 總長 1000 秒，在 100~200、180~250（重疊）、500~600 暫離
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
        # 在 1500.0 ~ 1501.0 秒有 1 秒的對話句末停頓
        silences = [(1500.0, 1501.0)]
        slices = VideoCutter.plan_slices(
            valid_segments=valid_segments,
            transitions=[],
            silences=silences,
            min_len=1200.0,
            max_len=1800.0,
        )
        # 第一刀應切在 1500.5 靜音中點
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
        from pathlib import Path
        from video_editor.config import EditorConfig

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
        # 在 1432.0 有黑白轉場點，在 1541.0 有對話句間的語音停頓
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
        # 第一刀必須切在 1432.0 轉場點，絕不能因 1541.0 有語音停頓而在台詞中硬切
        self.assertEqual(slices[0], (0.0, 1432.0))

    def test_plan_slices_waits_for_future_transition_when_forced(self):
        """強制轉場時，若窗口內無轉場但後續有轉場點，應主動等待並切在該轉場點。"""
        valid_segments = [(0.0, 4000.0)]
        # 窗口為 1200 ~ 1800，最近的轉場點在 1920.0
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
        # 應等待至 1920.0 轉場點，而非在 1500.0 或 1800.0 硬切
        self.assertEqual(slices[0], (0.0, 1920.0))

    def test_plan_slices_keyframe_snapping(self):
        """測試若提供 detector，切點會自動微調吸附至轉場區間內之關鍵影格。"""
        class MockDetector:
            def find_nearest_keyframe(self, t, search_window=2.0):
                # 假設在 1433.86 有關鍵影格
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
        # 切點應自動微調吸附至 1433.86 關鍵影格
        self.assertEqual(slices[0], (0.0, 1433.86))


if __name__ == "__main__":
    unittest.main()
