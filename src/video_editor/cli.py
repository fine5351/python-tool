"""命令列介面入口模組。"""

import argparse
import sys
from pathlib import Path

from video_editor.config import EditorConfig
from video_editor.pipeline import VideoEditorPipeline


def parse_args(args=None) -> argparse.Namespace:
    """解析終端機命令列引數。"""
    parser = argparse.ArgumentParser(
        description="長篇遊戲劇情影片智慧剪輯工具（結合 FFmpeg 與 AGY AI 多模態）"
    )

    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        required=True,
        help="輸入的長影片檔案路徑 (例如: input.mp4)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("output_parts"),
        help="切片輸出目錄 (預設: output_parts)",
    )
    parser.add_argument(
        "--min-part",
        type=float,
        default=20.0,
        help="每集目標最短時長 (分鐘，預設: 20)",
    )
    parser.add_argument(
        "--max-part",
        type=float,
        default=30.0,
        help="每集目標最長時長 (分鐘，預設: 30)",
    )
    parser.add_argument(
        "--freeze-threshold",
        type=float,
        default=30.0,
        help="判定為疑似暫離的連續靜止秒數 (秒，預設: 30)",
    )
    parser.add_argument(
        "--silence-noise",
        type=str,
        default="-30dB",
        help="語音靜音音量判定門檻 (預設: -30dB)",
    )
    parser.add_argument(
        "--min-silence",
        type=float,
        default=0.4,
        help="判定為語音停頓的最小秒數 (秒，預設: 0.4)",
    )
    parser.add_argument(
        "--max-overtime",
        type=float,
        default=90.0,
        help="為了等待話講完或動作做完，允許最多延後的秒數 (秒，預設: 90)",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="停用 AI 多模態審查，直接依照特徵閾值切片",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="僅進行特徵分析與切點規劃，不實際輸出分割影片檔",
    )
    parser.add_argument(
        "--ffmpeg-path",
        type=str,
        default="ffmpeg",
        help="自訂 FFmpeg 執行檔路徑 (若未加入環境變數)",
    )
    parser.add_argument(
        "--ffprobe-path",
        type=str,
        default="ffprobe",
        help="自訂 FFprobe 執行檔路徑 (若未加入環境變數)",
    )
    parser.add_argument(
        "--agy-path",
        type=str,
        default="agy",
        help="自訂 AGY CLI 執行檔路徑",
    )

    return parser.parse_args(args)


def main() -> None:
    """程式主進入點。"""
    args = parse_args()

    if not args.input.exists():
        print(f"錯誤：找不到指定的影片檔案 '{args.input}'", file=sys.stderr)
        sys.exit(1)

    config = EditorConfig(
        video_path=args.input,
        output_dir=args.output,
        min_freeze_duration=args.freeze_threshold,
        target_min_part_len=args.min_part * 60.0,
        target_max_part_len=args.max_part * 60.0,
        max_search_overtime=args.max_overtime,
        silence_noise_threshold=args.silence_noise,
        min_silence_duration=args.min_silence,
        ffmpeg_bin=args.ffmpeg_path,
        ffprobe_bin=args.ffprobe_path,
        agy_bin=args.agy_path,
        enable_ai=not args.no_ai,
        dry_run=args.dry_run,
    )

    pipeline = VideoEditorPipeline(config)
    try:
        pipeline.run()
    except Exception as err:
        print(f"\n❌ 執行中斷: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
