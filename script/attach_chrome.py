#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Video RPA - Chrome 執行時期接入與除錯互動工具 (Attach Chrome CLI).

用法：
    python script/attach_chrome.py
    python script/attach_chrome.py --port 9222
    python script/attach_chrome.py --auto-launch
"""

import argparse
import code
import os
import sys
import time
from typing import List, Dict

# 將 src 目錄加入 sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_dir = os.path.join(root_dir, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from video_rpa.utils.webdriver_util import WebDriverUtil


def list_tabs(driver) -> List[Dict[str, str]]:
    """列出所有目前分頁資訊並標記當前啟動分頁."""
    original_handle = driver.current_window_handle
    tabs = []
    for idx, handle in enumerate(driver.window_handles):
        try:
            driver.switch_to.window(handle)
            tabs.append({
                "index": idx + 1,
                "handle": handle,
                "title": driver.title or "(無標題)",
                "url": driver.current_url or "(無網址)",
                "is_current": (handle == original_handle)
            })
        except Exception:
            tabs.append({
                "index": idx + 1,
                "handle": handle,
                "title": "(讀取失敗)",
                "url": "(讀取失敗)",
                "is_current": (handle == original_handle)
            })
    # 切換回原先分頁
    try:
        driver.switch_to.window(original_handle)
    except Exception:
        pass
    return tabs


def print_tabs_summary(tabs: List[Dict[str, str]]):
    """印出分頁列表."""
    print("\n" + "=" * 70)
    print("📑【當前 Chrome 分頁列表】")
    print("=" * 70)
    for t in tabs:
        marker = "👉 [*]" if t["is_current"] else "   [ ]"
        print(f"{marker} [{t['index']}] {t['title']}")
        print(f"         URL: {t['url']}")
    print("-" * 70)


def start_interactive_session(driver, port: int):
    """進入互動式管理與 Python REPL 模式."""
    tabs = list_tabs(driver)
    print_tabs_summary(tabs)

    print("\n💡【操作提示】")
    print("  • 輸入數字 (例如 1, 2)   : 切換至指定分頁")
    print("  • tabs                   : 重新整理並列出所有分頁")
    print("  • goto <網址>            : 當前分頁開啟指定網址")
    print("  • new <網址>             : 開啟新分頁並導向網址")
    print("  • shot [檔名.png]        : 當前分頁畫面截圖")
    print("  • title                  : 顯示當前分頁標題與 URL")
    print("  • repl                   : 進入完整 Python 互動模式 (可直接調用 driver 物件)")
    print("  • exit / quit / q        : 安全脫離接入 (⚠️ Chrome 保持運行不關閉)")
    print("  • close-browser          : 關閉整台 Chrome 瀏覽器並退出")
    print("=" * 70 + "\n")

    while True:
        try:
            prompt_str = f"Chrome[{port}] ({driver.title[:15]}...) > "
        except Exception:
            prompt_str = f"Chrome[{port}] > "

        try:
            user_input = input(prompt_str).strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n👋 已安全中斷連線。Chrome 保持運行狀態！")
            break

        if not user_input:
            continue

        cmd_lower = user_input.lower()

        if cmd_lower in ("exit", "quit", "q"):
            print("👋 已安全退出接入工具。Chrome 保持在背景運行中！")
            break

        elif cmd_lower == "close-browser":
            confirm = input("⚠️ 確定要關閉整台 Chrome 瀏覽器嗎？(y/N): ").strip().lower()
            if confirm in ("y", "yes"):
                try:
                    driver.quit()
                    print("🛑 Chrome 已關閉。")
                except Exception as e:
                    print(f"關閉 Chrome 失敗: {e}")
                break
            else:
                print("操作已取消。")
                continue

        elif cmd_lower == "tabs":
            tabs = list_tabs(driver)
            print_tabs_summary(tabs)

        elif cmd_lower == "title":
            try:
                print(f"標題: {driver.title}")
                print(f"網址: {driver.current_url}")
            except Exception as e:
                print(f"讀取失敗: {e}")

        elif cmd_lower.startswith("goto "):
            url = user_input[5:].strip()
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            try:
                driver.get(url)
                print(f"✅ 已前往: {url}")
            except Exception as e:
                print(f"❌ 導向失敗: {e}")

        elif cmd_lower.startswith("new "):
            url = user_input[4:].strip()
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            try:
                driver.switch_to.new_window('tab')
                driver.get(url)
                print(f"✅ 已開啟新分頁並前往: {url}")
            except Exception as e:
                print(f"❌ 開啟失敗: {e}")

        elif cmd_lower.startswith("shot"):
            parts = user_input.split(maxsplit=1)
            filename = parts[1] if len(parts) > 1 else f"screenshot_{int(time.time())}.png"
            try:
                driver.save_screenshot(filename)
                print(f"📸 截圖已儲存至: {os.path.abspath(filename)}")
            except Exception as e:
                print(f"❌ 截圖失敗: {e}")

        elif cmd_lower == "repl":
            print("\n🐍【進入 Python 互動式 REPL】")
            print("  可直接調用 `driver` 變數 (例如: `driver.title`, `driver.page_source`)")
            print("  輸入 `exit()` 或按 Ctrl+Z / Ctrl+D 即可返回上一層控制台。\n")
            local_env = {
                "driver": driver,
                "WebDriverUtil": WebDriverUtil,
                "tabs": tabs
            }
            code.interact(banner="", local=local_env)
            print("⬅️ 已退出 REPL，返回 Chrome 控制台。\n")

        elif user_input.isdigit():
            target_idx = int(user_input)
            handles = driver.window_handles
            if 1 <= target_idx <= len(handles):
                target_handle = handles[target_idx - 1]
                driver.switch_to.window(target_handle)
                print(f"✅ 已切換至分頁 [{target_idx}]: {driver.title}")
            else:
                print(f"❌ 無效的分頁編號: {target_idx} (可用範圍: 1 ~ {len(handles)})")

        else:
            # 支援直接執行單行 Python 表達式或命令
            try:
                # 優先嘗試作為表達式求值 (eval)
                res = eval(user_input, {"driver": driver, "WebDriverUtil": WebDriverUtil})
                if res is not None:
                    print(res)
            except SyntaxError:
                # 若為語句 (如賦值或多語句)，嘗試 exec
                try:
                    exec(user_input, {"driver": driver, "WebDriverUtil": WebDriverUtil})
                except Exception as ex:
                    print(f"❌ 執行錯誤: {ex}")
            except Exception as ex:
                print(f"❌ 指令或語法無效: {ex}")
                print("   (輸入 'tabs' 查看分頁，輸入 'repl' 進入 Python 環境，或輸入 'exit' 退出)")


def main():
    parser = argparse.ArgumentParser(description="Video RPA - Chrome 執行時期快速接入工具")
    parser.add_argument("--port", type=int, default=WebDriverUtil.DEFAULT_DEBUG_PORT, help="Chrome 遠端除錯埠號 (預設: 9222)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Chrome 遠端主機位址 (預設: 127.0.0.1)")
    parser.add_argument("--data-dir", type=str, default=None, help="指定 Chrome Profile 目錄 (預設: 專案專用 chrome-data 目錄)")
    parser.add_argument("--no-auto-launch", action="store_true", help="若除錯埠未啟動，不自動啟動 Chrome (預設會自動啟動)")
    parser.add_argument("--repl", action="store_true", help="連線成功後直接進入 Python REPL 環境")
    args = parser.parse_args()

    port = args.port
    host = args.host
    data_dir = args.data_dir or WebDriverUtil.CHROME_DATA_DIR

    print("=" * 70)
    print(f"🔍 正在檢查 Chrome 遠端除錯連線 ({host}:{port})...")
    print("=" * 70)

    # 1. 檢查除錯埠是否開放，若未開放則自動使用專案 Profile 啟動 Chrome
    if not WebDriverUtil.is_debug_port_open(host, port):
        if args.no_auto_launch:
            print(f"\n⚠️ 尚未偵測到在 {host}:{port} 運行的 Chrome！")
            print("如需手動啟動，請於終端機執行：")
            print(f'  chrome.exe --remote-debugging-port={port} --user-data-dir="{data_dir}"')
            sys.exit(0)

        print(f"\n💡 偵測到當前未開啟 Chrome，正在使用本專案專用 Profile 自動啟動 Chrome (Port {port})...")
        print(f"📁 Profile 路徑: {os.path.normpath(data_dir)}")
        WebDriverUtil.launch_debug_chrome(port=port, data_dir=data_dir)

        # 等待埠就緒
        print("⏳ 等待 Chrome 初始化中...", end="", flush=True)
        for _ in range(20):
            time.sleep(0.5)
            print(".", end="", flush=True)
            if WebDriverUtil.is_debug_port_open(host, port):
                print(" 就緒！")
                break
        else:
            print("\n❌ 啟動超時，無法連線至 Chrome 除錯埠。請手動檢查環境。")
            sys.exit(1)
    else:
        print(f"✅ 偵測到現有 Chrome 實例正在運行中，正在直接接入...")

    # 2. 接入運行中的 Chrome
    try:
        driver = WebDriverUtil.attach_driver(host, port)
    except Exception as e:
        print(f"\n❌ 接入失敗: {e}")
        sys.exit(1)

    print(f"\n🎉 成功接入 Chrome 實例！")
    print(f"   • 當前視窗標題 : {driver.title}")
    print(f"   • 當前網址     : {driver.current_url}")

    if args.repl:
        print("\n🐍 直接進入 Python REPL (已掛載 `driver` 物件):")
        local_env = {"driver": driver, "WebDriverUtil": WebDriverUtil}
        code.interact(banner="", local=local_env)
        print("👋 已退出 REPL。Chrome 保持在背景運行中！")
    else:
        start_interactive_session(driver, port)


if __name__ == "__main__":
    main()
