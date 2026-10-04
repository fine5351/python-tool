"""Video RPA 統一命令列介面 (CLI Entry Point)."""

import argparse
import logging
import os
import sys
from typing import List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from natsort import natsorted

from video_rpa.core.trail_tracker import OperationTrailTracker
from video_rpa.services.bilibili_service import BilibiliService
from video_rpa.services.rednote_service import rednoteService
from video_rpa.services.tiktok_service import TikTokService
from video_rpa.services.youtube_service import YouTubeService
from video_rpa.utils.webdriver_util import WebDriverUtil

# Setup basic logging to console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("VideoRPA")


def get_filename_without_extension(file_path: str) -> str:
    if not file_path:
        return ""
    return os.path.splitext(os.path.basename(file_path))[0]


def process_multi_platform_upload(file_path: str, description: str, playlist: str, bilibili_category: str, hashtags: list, keep_open: bool, target_platforms: Optional[List[str]] = None) -> bool:
    title = get_filename_without_extension(file_path)
    logger.info(f"Starting multi-platform tabbed upload for {title}...")

    if not target_platforms:
        selected = ["youtube", "bilibili", "rednote", "tiktok"]
    else:
        selected = [p.strip().lower() for p in target_platforms if p.strip()]
        if not selected:
            selected = ["youtube", "bilibili", "rednote", "tiktok"]

    logger.info(f"Target platforms: {', '.join(selected)}")

    driver = None
    successful_platforms = []
    failed_platforms = []

    try:
        driver = WebDriverUtil.initialize_driver()
        platforms = []
        is_first_tab = True

        def prepare_tab():
            nonlocal is_first_tab
            if is_first_tab:
                is_first_tab = False
                return driver.current_window_handle
            else:
                driver.switch_to.new_window('tab')
                return driver.current_window_handle

        # 1. YouTube
        if "youtube" in selected:
            try:
                logger.info("Starting YouTube form...")
                window_yt = prepare_tab()
                yt_service = YouTubeService()
                yt_service.start_upload_form(driver, file_path, title, description, playlist, "PUBLIC", hashtags)
                platforms.append({"name": "YouTube", "handle": window_yt, "service": yt_service})
            except Exception as e:
                logger.error(f"Failed to start upload form for YouTube: {e}", exc_info=True)
                failed_platforms.append(f"YouTube (表單初始化失敗: {e})")

        # 2. Bilibili
        if "bilibili" in selected:
            try:
                logger.info("Starting Bilibili form...")
                window_bili = prepare_tab()
                bili_service = BilibiliService()
                bili_service.start_upload_form(driver, file_path, title, description, bilibili_category, hashtags)
                platforms.append({"name": "Bilibili", "handle": window_bili, "service": bili_service})
            except Exception as e:
                logger.error(f"Failed to start upload form for Bilibili: {e}", exc_info=True)
                failed_platforms.append(f"Bilibili (表單初始化失敗: {e})")

        # 3. rednote
        if "rednote" in selected:
            try:
                logger.info("Starting rednote form...")
                window_xhs = prepare_tab()
                xhs_service = rednoteService()
                xhs_service.start_upload_form(driver, file_path, title, description, hashtags)
                platforms.append({"name": "rednote", "handle": window_xhs, "service": xhs_service})
            except Exception as e:
                logger.error(f"Failed to start upload form for rednote: {e}", exc_info=True)
                failed_platforms.append(f"rednote (表單初始化失敗: {e})")

        # 4. TikTok
        if "tiktok" in selected:
            try:
                logger.info("Starting TikTok form...")
                window_tiktok = prepare_tab()
                tiktok_service = TikTokService()
                tiktok_service.start_upload_form(driver, file_path, title, description, hashtags)
                platforms.append({"name": "TikTok", "handle": window_tiktok, "service": tiktok_service})
            except Exception as e:
                logger.error(f"Failed to start upload form for TikTok: {e}", exc_info=True)
                failed_platforms.append(f"TikTok (表單初始化失敗: {e})")

        # Phase 2: Wait and publish
        logger.info("All forms submitted. Now waiting for uploads to complete and publishing...")
        for p in platforms:
            try:
                driver.switch_to.window(p["handle"])
                logger.info(f"Switching to {p['name']} tab to finish publish...")
                p["service"].wait_and_publish(driver)
                logger.info(f"✅ {p['name']} upload completed successfully!")
                successful_platforms.append(p["name"])
            except Exception as e:
                logger.error(f"Failed to publish for {p['name']}: {e}", exc_info=True)
                failed_platforms.append(f"{p['name']} (發佈階段失敗: {e})")

        OperationTrailTracker.get_instance().save_to_file()

    except Exception as e:
        logger.error(f"Error during multi tab process: {e}", exc_info=True)
    finally:
        if driver is not None:
            if not keep_open:
                driver.quit()
            else:
                logger.warning("Browser left open for debugging due to --keep-open.")

    logger.info("\n" + "=" * 60)
    logger.info(f"📊【多平台發佈結果統計】《{title}》")
    logger.info(f"  ✅ 成功發佈 ({len(successful_platforms)}): {', '.join(successful_platforms) if successful_platforms else '無'}")
    if failed_platforms:
        logger.error(f"  ❌ 發佈失敗 ({len(failed_platforms)}): {', '.join(failed_platforms)}")
    logger.info("=" * 60 + "\n")

    return len(failed_platforms) == 0 and len(successful_platforms) > 0


def main():
    parser = argparse.ArgumentParser(description="Video RPA CLI - 多平台影音自動發佈工具")
    parser.add_argument("--show-trail", action="store_true", help="顯示當前待固化的操作軌跡報告並結束。")
    subparsers = parser.add_subparsers(dest="command", help="可用子命令 (Subcommands)")

    # Common arguments
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--file", type=str, help="影片檔案路徑。", required=False)
    common_parser.add_argument("--folder", type=str, help="影片資料夾路徑 (供多影片批次發佈)。", required=False)
    common_parser.add_argument("--title", type=str, help="影片標題 (預設為檔案名稱)。", default=None)
    common_parser.add_argument("--desc", type=str, help="影片說明或文案。", default="")
    common_parser.add_argument("--tags", type=str, help="以逗號分隔的主題標籤 (例如: tag1,tag2)。", default="")
    common_parser.add_argument("--keep-open", action="store_true", help="失敗或結束時保持瀏覽器開啟以供除錯。")
    common_parser.add_argument("--show-trail", action="store_true", help="顯示當前待固化的操作軌跡報告並結束。")

    # YouTube Specific
    parser_yt = subparsers.add_parser("youtube", parents=[common_parser], help="上傳至 YouTube")
    parser_yt.add_argument("--playlist", type=str, help="YouTube 播放清單", default="")
    parser_yt.add_argument("--visibility", type=str, choices=["PUBLIC", "UNLISTED", "PRIVATE"], default="PUBLIC")

    # TikTok Specific
    parser_tiktok = subparsers.add_parser("tiktok", parents=[common_parser], help="上傳至 TikTok")
    parser_tiktok.add_argument("--visibility", type=str, choices=["PUBLIC", "UNLISTED", "PRIVATE"], default="PUBLIC")

    # rednote Specific
    parser_xhs = subparsers.add_parser("rednote", parents=[common_parser], help="上傳至小紅書 (Rednote)")

    # Bilibili Specific
    parser_bili = subparsers.add_parser("bilibili", parents=[common_parser], help="上傳至 Bilibili")
    parser_bili.add_argument("--category", type=str, help="Bilibili 分區", default="游戏")

    # Multi-Platform Specific
    parser_multi = subparsers.add_parser("multi", parents=[common_parser], help="批次或同時上傳至所有平台")
    parser_multi.add_argument("--playlist", type=str, help="YouTube 播放清單", default="")
    parser_multi.add_argument("--category", type=str, help="Bilibili 分區", default="游戏")
    parser_multi.add_argument("--platforms", type=str, help="指定發佈平台 (例如: youtube,bilibili)，預設為所有平台", default="")

    args = parser.parse_args()

    tracker = OperationTrailTracker.get_instance()

    if getattr(args, "show_trail", False):
        tracker.print_consolidation_log(logger)
        return

    if not args.command:
        parser.print_help()
        return

    hashtags = [t.strip() for t in args.tags.split(",")] if args.tags else []
    target_platforms = [p.strip().lower() for p in args.platforms.split(",")] if getattr(args, "platforms", None) else None

    VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.mov', '.flv', '.avi', '.webm', '.wmv')
    success = True

    try:
        if args.command == "multi" and args.folder:
            folder = args.folder
            if not os.path.isdir(folder):
                logger.error(f"Invalid folder path: {folder}")
                sys.exit(1)

            files = [
                os.path.join(folder, f)
                for f in os.listdir(folder)
                if os.path.isfile(os.path.join(folder, f)) and f.lower().endswith(VIDEO_EXTENSIONS)
            ]
            files = natsorted(files)

            if not files:
                logger.warning(f"在目錄 {folder} 中未找到任何影片檔案 (支援副檔名: {', '.join(VIDEO_EXTENSIONS)})。")
                sys.exit(0)

            all_ok = True
            for f in files:
                logger.info(f"Processing file in batch: {os.path.basename(f)}")
                ok = process_multi_platform_upload(f, args.desc, args.playlist, args.category, hashtags, args.keep_open, target_platforms=target_platforms)
                if not ok:
                    all_ok = False

            if not all_ok:
                sys.exit(1)
            return

        if not args.file:
            logger.error("--file 或 --folder 為必填參數。")
            sys.exit(1)

        file_path = args.file
        if not os.path.isfile(file_path):
            logger.error(f"找不到檔案: {file_path}")
            sys.exit(1)

        title = args.title if args.title is not None else get_filename_without_extension(file_path)

        if args.command == "youtube":
            service = YouTubeService()
            success = service.upload_video(file_path, title, args.desc, args.playlist, args.visibility, hashtags, args.keep_open)
        elif args.command == "tiktok":
            service = TikTokService()
            success = service.upload_video(file_path, title, args.desc, args.visibility, hashtags, args.keep_open)
        elif args.command == "rednote":
            service = rednoteService()
            success = service.upload_video(file_path, title, args.desc, hashtags, args.keep_open)
        elif args.command == "bilibili":
            service = BilibiliService()
            success = service.upload_video(file_path, title, args.desc, args.category, hashtags, args.keep_open)
        elif args.command == "multi":
            success = process_multi_platform_upload(file_path, args.desc, args.playlist, args.category, hashtags, args.keep_open, target_platforms=target_platforms)

        if not success:
            sys.exit(1)

    finally:
        # 任務結束後輸出 log 表示需要回寫 script 進行固化
        tracker.print_consolidation_log(logger)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n [系統] 接收到中斷指令 (Ctrl+C)，正在安全關閉並結束程式...")
        OperationTrailTracker.get_instance().print_consolidation_log(logger)
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)
