"""命令列介面入口模組（支援三級 AI 模型配置與對話式剪輯重組）。"""

import argparse
import sys
from pathlib import Path

from video_editor.config import EditorConfig, ModelConfig, clean_path
from video_editor.pipeline import VideoEditorPipeline


def parse_args(args=None) -> argparse.Namespace:
    """解析終端機命令列引數。"""
    parser = argparse.ArgumentParser(
        description="通用型 AI 對話式影片智慧剪輯、重組與無損匯出工具（結合 FFmpeg 與 AGY 多模態分流）"
    )

    parser.add_argument(
        "-i",
        "--input",
        type=clean_path,
        required=True,
        help="輸入的影片檔案路徑 (例如: input.mp4)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=clean_path,
        default=Path("output_parts"),
        help="影片輸出目錄 (預設: output_parts)",
    )
    parser.add_argument(
        "--export-mode",
        type=str,
        choices=["episodes", "single", "clips"],
        default="episodes",
        help="匯出模式: episodes (無縫拼接並按時長分集) | single (合併為單一完整檔) | clips (各保留段獨立輸出)",
    )
    parser.add_argument(
        "-p",
        "--prompt",
        type=str,
        default="",
        help="啟動時自動套用的初始自然語言剪輯指令 (例如: '刪除重打失敗過程，只留最後通關並匯出單一檔')",
    )
    parser.add_argument(
        "--plan-file",
        type=clean_path,
        default=None,
        help="指定載入或儲存剪輯計畫 JSON 的路徑 (若檔案已存在將直接載入免重跑初始掃描)",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="完成初始 AI 規劃後自動確認並匯出，跳過終端機互動對話等待",
    )

    # AI 工作職責三級模型配置參數
    parser.add_argument(
        "--model-vision-fast",
        type=str,
        default="flash_lite",
        help="基礎視覺快篩與場景摘要模型 (預設: flash_lite)",
    )
    parser.add_argument(
        "--model-vision-deep",
        type=str,
        default="flash",
        help="深度視覺探勘與區間密集細掃模型 (預設: flash)",
    )
    parser.add_argument(
        "--model-planner",
        type=str,
        default="pro",
        help="自然語言對話推理與非線性時間軸重組模型 (預設: pro)",
    )

    # 時間軸與特徵門檻參數
    parser.add_argument(
        "--min-part",
        type=float,
        default=20.0,
        help="episodes 模式下每集目標最短時長 (分鐘，預設: 20)",
    )
    parser.add_argument(
        "--max-part",
        type=float,
        default=30.0,
        help="episodes 模式下每集目標最長時長 (分鐘，預設: 30)",
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
        default=180.0,
        help="為了等待黑白轉場畫面出現，允許最多延後的秒數 (秒，預設: 180)",
    )
    parser.add_argument(
        "--no-require-transition",
        dest="require_transition",
        action="store_false",
        help="停用強制黑白轉場分割（允許在無轉場時退回語音停頓切片）",
    )
    parser.set_defaults(require_transition=True)
    parser.add_argument(
        "--white-duration",
        type=float,
        default=0.5,
        help="白畫面轉場判定最短秒數 (秒，預設: 0.5)",
    )
    parser.add_argument(
        "--white-pixel",
        type=float,
        default=0.10,
        help="白畫面像素門檻 (預設: 0.10)",
    )
    parser.add_argument(
        "--white-ratio",
        type=float,
        default=0.98,
        help="白畫面佔比門檻 (預設: 0.98)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="僅進行場景分析、互動規劃與模擬，不實際寫入分割影片檔",
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
    parser.add_argument(
        "--temp-dir",
        type=clean_path,
        default=None,
        help="暫存影格圖片與 concat 清單目錄 (預設: 專案目錄下之 temp_frames)",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="保留暫存影格圖片（預設會於流程結束後自動清理）",
    )

    return parser.parse_args(args)


def main() -> None:
    """程式主進入點。"""
    args = parse_args()

    if not args.input.exists():
        print(f"錯誤：找不到指定的影片檔案 '{args.input}'", file=sys.stderr)
        sys.exit(1)

    if not args.output.exists():
        try:
            args.output.mkdir(parents=True, exist_ok=True)
            print(f"ℹ 預期的輸出目錄不存在，已自動建立: '{args.output}'")
        except Exception as err:
            print(f"錯誤：無法建立輸出目錄 '{args.output}' ({err})", file=sys.stderr)
            sys.exit(1)

    models_cfg = ModelConfig(
        fast_vision=args.model_vision_fast,
        deep_vision=args.model_vision_deep,
        planner=args.model_planner,
    )

    config_kwargs = {
        "video_path": args.input,
        "output_dir": args.output,
        "plan_file": args.plan_file,
        "models": models_cfg,
        "export_mode": args.export_mode,
        "initial_prompt": args.prompt,
        "auto_confirm": args.yes,
        "min_freeze_duration": args.freeze_threshold,
        "target_min_part_len": args.min_part * 60.0,
        "target_max_part_len": args.max_part * 60.0,
        "max_search_overtime": args.max_overtime,
        "silence_noise_threshold": args.silence_noise,
        "min_silence_duration": args.min_silence,
        "min_white_duration": args.white_duration,
        "white_pixel_threshold": args.white_pixel,
        "white_ratio_threshold": args.white_ratio,
        "require_transition": args.require_transition,
        "ffmpeg_bin": args.ffmpeg_path,
        "ffprobe_bin": args.ffprobe_path,
        "agy_bin": args.agy_path,
        "dry_run": args.dry_run,
        "keep_temp": args.keep_temp,
    }
    if args.temp_dir is not None:
        config_kwargs["temp_dir"] = args.temp_dir

    config = EditorConfig(**config_kwargs)

    pipeline = VideoEditorPipeline(config)
    try:
        pipeline.run()
    except Exception as err:
        print(f"\n❌ 執行中斷: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
