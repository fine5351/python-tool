"""命令列介面與路徑處理單元測試。"""

import sys
import tempfile
import unittest
from pathlib import Path

from video_editor.cli import main, parse_args
from video_editor.config import EditorConfig, clean_path


class TestCLI(unittest.TestCase):
    """測試命令列引數解析與輸出目錄自動建立。"""

    def test_clean_path_trailing_quotes(self):
        """測試 Windows 命令列因轉義反斜線引號遺留的尾部雙引號與空白清理。"""
        # 模擬 Windows CMD 下傳入 "folder\" 導致字串變為 folder"
        dirty_path_1 = 'output_folder"'
        self.assertEqual(clean_path(dirty_path_1), Path("output_folder"))

        # 兩側引號與空白
        dirty_path_2 = '  "sub_dir/output"  '
        self.assertEqual(clean_path(dirty_path_2), Path("sub_dir/output"))

        # 既有 Path 物件
        clean_p = Path("normal_dir")
        self.assertEqual(clean_path(clean_p), Path("normal_dir"))

    def test_editor_config_normalizes_paths(self):
        """測試 EditorConfig 初始化會自動將所有路徑正規化，且 temp_dir 錨定至專案根目錄。"""
        from video_editor.config import PROJECT_ROOT

        cfg = EditorConfig(
            video_path='input.mp4"',
            output_dir='output_dir"',
            temp_dir='temp_dir"',
        )
        self.assertEqual(cfg.video_path, Path("input.mp4"))
        self.assertEqual(cfg.output_dir, Path("output_dir"))
        self.assertEqual(cfg.temp_dir, (PROJECT_ROOT / "temp_dir").resolve())

    def test_temp_dir_defaults_to_project_root(self):
        """測試 temp_dir 預設必在專案根目錄下，不受當前執行目錄影響。"""
        from video_editor.config import PROJECT_ROOT

        cfg = EditorConfig(video_path=Path("dummy.mp4"))
        self.assertEqual(cfg.temp_dir, (PROJECT_ROOT / "temp_frames").resolve())

    def test_pipeline_cleanup_temp_frames(self):
        """測試 Pipeline 完成或結束時會自動清理暫存影格。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_temp_dir = Path(tmp_dir) / "test_temp_frames"
            tmp_temp_dir.mkdir(parents=True, exist_ok=True)
            dummy_frame = tmp_temp_dir / "cut_candidate_1.jpg"
            dummy_frame.write_bytes(b"image_data")

            cfg = EditorConfig(
                video_path=Path("dummy.mp4"),
                temp_dir=tmp_temp_dir,
                keep_temp=False,
            )
            from video_editor.pipeline import VideoEditorPipeline
            pipeline = VideoEditorPipeline(cfg)
            pipeline.cleanup_temp_frames()

            # 驗證暫存目錄與檔案已被清理
            self.assertFalse(dummy_frame.exists())
            self.assertFalse(tmp_temp_dir.exists())

    def test_parse_args_cleans_output_path(self):
        """測試 parse_args 能正確清理包含引號的輸出目錄參數。"""
        args = parse_args(["-i", "video.mp4", "-o", 'my_output"'])
        self.assertEqual(args.output, Path("my_output"))
        self.assertEqual(args.input, Path("video.mp4"))
        self.assertTrue(args.require_transition)

    def test_parse_args_white_and_transition_flags(self):
        """測試 parse_args 能正確解析白畫面參數與強制轉場開關。"""
        args = parse_args([
            "-i", "video.mp4",
            "--no-require-transition",
            "--white-duration", "1.2",
            "--white-pixel", "0.15",
            "--white-ratio", "0.95",
        ])
        self.assertFalse(args.require_transition)
        self.assertEqual(args.white_duration, 1.2)
        self.assertEqual(args.white_pixel, 0.15)
        self.assertEqual(args.white_ratio, 0.95)

    def test_main_creates_output_dir_if_not_exists(self):
        """測試當預期的 output 目錄不存在時，主程式會自行建立。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            fake_video = tmp_path / "test_video.mp4"
            fake_video.write_bytes(b"dummy")

            expected_output_dir = tmp_path / "nested" / "auto_created_output"
            self.assertFalse(expected_output_dir.exists())

            # 模擬執行 main，並傳入尚未建立的輸出目錄
            test_argv = [
                "main.py",
                "-i",
                str(fake_video),
                "-o",
                str(expected_output_dir) + '"',  # 故意模擬 Windows 轉義雙引號
                "--dry-run",
            ]
            original_argv = sys.argv
            try:
                sys.argv = test_argv
                # 攔截 Pipeline.run 以免觸發 ffprobe
                from unittest.mock import patch

                with patch("video_editor.cli.VideoEditorPipeline.run"):
                    main()
            finally:
                sys.argv = original_argv

            # 驗證輸出目錄已被建立
            self.assertTrue(expected_output_dir.exists())
            self.assertTrue(expected_output_dir.is_dir())


if __name__ == "__main__":
    unittest.main()
