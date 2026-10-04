"""Video RPA 人機協同介入 (HITL) 互動式元素拾取器."""

import logging
import sys
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class HitlHandler:
    """Handles Human-In-The-Loop interactive resolution when automated RPA steps get stuck."""

    INSPECTOR_JS = """
    (function() {
        if (window.__rpa_inspector_active) return;
        window.__rpa_inspector_active = true;
        window.__rpa_selected_element = null;

        // Create top banner
        const banner = document.createElement('div');
        banner.id = '__rpa_banner';
        banner.textContent = '⚠️ RPA 協助模式：請用滑鼠直接點擊目標元素，或按 ESC 取消';
        banner.style = 'position:fixed;top:10px;left:50%;transform:translateX(-50%);background:#e53935;color:#fff;padding:12px 24px;z-index:9999999;font-size:15px;font-family:sans-serif;border-radius:8px;box-shadow:0 4px 15px rgba(0,0,0,0.4);pointer-events:none;';
        document.body.appendChild(banner);

        let lastHovered = null;

        function getXPath(el) {
            if (el.id) return `//*[@id="${el.id}"]`;
            if (el === document.body) return '/html/body';
            let ix = 0;
            const siblings = el.parentNode ? el.parentNode.childNodes : [];
            for (let i = 0; i < siblings.length; i++) {
                const sibling = siblings[i];
                if (sibling === el) {
                    const parentPath = el.parentNode ? getXPath(el.parentNode) : '';
                    return `${parentPath}/${el.tagName.toLowerCase()}[${ix + 1}]`;
                }
                if (sibling.nodeType === 1 && sibling.tagName === el.tagName) {
                    ix++;
                }
            }
            return '';
        }

        function onMouseOver(e) {
            if (e.target.id === '__rpa_banner') return;
            if (lastHovered) lastHovered.style.outline = '';
            lastHovered = e.target;
            lastHovered.style.outline = '3px solid #00e676';
        }

        function onClick(e) {
            e.preventDefault();
            e.stopPropagation();
            const target = e.target;
            const xpath = getXPath(target);
            const text = (target.innerText || target.textContent || '').trim().slice(0, 50);

            window.__rpa_selected_element = {
                xpath: xpath,
                tagName: target.tagName,
                text: text
            };

            cleanup();
        }

        function cleanup() {
            if (lastHovered) lastHovered.style.outline = '';
            const b = document.getElementById('__rpa_banner');
            if (b) b.remove();
            document.removeEventListener('mouseover', onMouseOver, true);
            document.removeEventListener('click', onClick, true);
            window.__rpa_inspector_active = false;
        }

        document.addEventListener('mouseover', onMouseOver, true);
        document.addEventListener('click', onClick, true);
    })();
    """

    CLEANUP_JS = """
    (function() {
        const b = document.getElementById('__rpa_banner');
        if (b) b.remove();
        window.__rpa_inspector_active = false;
        window.__rpa_selected_element = null;
    })();
    """

    @classmethod
    def resolve_stuck_step(cls, driver, step_id: str, step_name: str,
                           ai_diagnosis: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Prompts user through browser click and console to resolve a stuck step."""
        print("\n" + "=" * 60)
        print(f"🚨 [RPA 人機協同介入通知] 步驟【{step_name}】(ID: {step_id}) 無法自動完成！")
        if ai_diagnosis and ai_diagnosis.get("description"):
            print(f"🤖 [AI 視覺診斷建議]: {ai_diagnosis.get('description')}")
            if ai_diagnosis.get("target_text"):
                print(f"   建議標籤/文字: {ai_diagnosis.get('target_text')}")
        print("-" * 60)
        print("已在開啟的瀏覽器視窗中啟動【元素拾取器】（頁面頂部出現紅色標籤）。")
        print("您可以直接在網頁上【點擊目標元素】，系統將自動讀取 XPath。")
        print("或者您可以在此終端機選擇以下操作：")
        print("  [1] 等待網頁點擊（預設，點選畫面即可）")
        print("  [2] 手動輸入新的 XPath / 文字")
        print("  [3] 我已在網頁上手動完成操作，請跳過此步驟繼續")
        print("  [4] 這是新版多出的【新增中介步驟】，記錄為新步驟")
        print("  [5] 放棄並中斷程式")
        print("=" * 60)

        # Inject browser inspector
        try:
            driver.execute_script(cls.INSPECTOR_JS)
        except Exception as e:
            logger.warning(f"Could not inject browser inspector: {e}")

        # Polling loop for browser click with non-blocking check
        timeout_seconds = 60
        start_time = time.time()

        print("\n正在等待操作（可直接在瀏覽器點擊目標，或按 Enter 切換至終端輸入）...")

        while time.time() - start_time < timeout_seconds:
            try:
                selected = driver.execute_script("return window.__rpa_selected_element;")
                if selected:
                    xpath = selected.get("xpath")
                    text = selected.get("text", "")
                    print(f"\n✅ 成功從網頁拾取元素！")
                    print(f"   XPath: {xpath}")
                    if text:
                        print(f"   文字: {text}")
                    return {
                        "status": "RESOLVED",
                        "by": "xpath",
                        "value": xpath,
                        "text": text,
                        "is_new_step": False
                    }
            except Exception:
                pass

            time.sleep(1)

        # If inspector timed out or user wants terminal input
        print("\n[提示] 拾取等待逾時，切換至終端機輸入模式。")
        return cls._terminal_prompt(driver, step_id, step_name)

    @classmethod
    def _terminal_prompt(cls, driver, step_id: str, step_name: str) -> Dict[str, Any]:
        try:
            driver.execute_script(cls.CLEANUP_JS)
        except Exception:
            pass

        while True:
            choice = input("\n請選擇操作 [1:手動輸入XPath / 2:跳過此步驟 / 3:新增為新步驟 / 4:結束]: ").strip()
            if choice == "1":
                xpath = input("請輸入目標元素的 XPath: ").strip()
                if xpath:
                    return {
                        "status": "RESOLVED",
                        "by": "xpath",
                        "value": xpath,
                        "is_new_step": False
                    }
            elif choice == "2":
                return {"status": "SKIPPED"}
            elif choice == "3":
                new_name = input(f"請輸入新步驟名稱 (例如: '點擊新版活動確認'): ").strip() or f"{step_name}_new"
                xpath = input("請輸入該新步驟的點擊 XPath: ").strip()
                return {
                    "status": "RESOLVED",
                    "by": "xpath",
                    "value": xpath,
                    "is_new_step": True,
                    "new_step_name": new_name
                }
            elif choice == "4":
                print("使用者選擇中斷執行。")
                sys.exit(0)
            else:
                print("無效選項，請重新輸入。")
