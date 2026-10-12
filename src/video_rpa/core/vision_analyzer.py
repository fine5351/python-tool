"""Video RPA Gemini Vision AI 視覺畫面分析器."""

import json
import logging
import os
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class VisionAnalyzer:
    """Uses Gemini Vision API to analyze browser screenshots, detect unexpected popups,
    and suggest recovery actions or coordinates when Selenium gets stuck."""

    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-2.5-flash"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model_name = model_name
        self.client = None
        self._init_client()

    def _init_client(self) -> None:
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not found in environment. Vision AI analysis will be disabled.")
            return

        try:
            from google import genai
            self.client = genai.Client(api_key=self.api_key)
            logger.info(f"Initialized Gemini Vision client with model {self.model_name}")
        except Exception as e:
            logger.warning(f"Failed to initialize google-genai client: {e}. Trying google.generativeai fallback...")
            try:
                import google.generativeai as legacy_genai
                legacy_genai.configure(api_key=self.api_key)
                self.client = legacy_genai.GenerativeModel(self.model_name)
                logger.info("Initialized legacy google.generativeai client.")
            except Exception as e2:
                logger.error(f"Could not initialize any Gemini client: {e2}")
                self.client = None

    def is_available(self) -> bool:
        return self.client is not None

    def analyze_screen_state(self, screenshot_png_bytes: bytes, current_step_name: str,
                             context_url: str = "") -> Dict[str, Any]:
        """Analyzes the screenshot to identify obstacles (popups, changes) and suggest actions."""
        if not self.is_available():
            return {
                "available": False,
                "status": "UNKNOWN",
                "reason": "Gemini client not initialized or API key missing",
                "action": "NEED_USER_INPUT"
            }

        prompt = f"""
你是一個自動化 RPA 專家。目前 Selenium 自動化程式正在嘗試執行步驟：【{current_step_name}】，但逾時找不到原本設定的元素。
網址背景：{context_url}

請仔細觀察當前的網頁截圖，診斷目前頁面狀態並提供解法。請以 JSON 格式回應，不要包含任何 markdown 標籤或額外文字。

JSON 回應格式定義如下：
{{
  "status": "POPUP_DETECTED" | "ELEMENT_FOUND" | "PROCESSING_WAIT" | "ERROR_STATE" | "UNKNOWN",
  "description": "簡短描述畫面上看到了什麼（例如：出現了『條款更新』或『發布確認』彈窗遮蔽了背景）",
  "blocker_name": "干擾彈窗或遮蔽元件名稱（若無則為 null）",
  "action": "DISMISS_POPUP" | "CLICK_COORDINATE" | "WAIT" | "NEED_USER_INPUT",
  "target_coordinates": {{"x": 0到1000的整數比例座標, "y": 0到1000的整數比例座標}} (若不需要點擊則為 null),
  "target_text": "若為按鈕或輸入框，該按鈕的文字標籤或特徵（例如：'我知道了' 或 '發布'）",
  "suggested_xpath": "若能推導出 XPath 則提供，否則為 null",
  "confidence": 0.0 到 1.0 的信心度數值
}}
"""

        try:
            response_text = ""
            # Handle google-genai SDK
            if hasattr(self.client, "models"):
                from google.genai import types
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=[
                        types.Part.from_bytes(data=screenshot_png_bytes, mime_type="image/png"),
                        prompt
                    ]
                )
                response_text = response.text or ""
            else:
                # Handle legacy SDK
                import io
                from PIL import Image
                img = Image.open(io.BytesIO(screenshot_png_bytes))
                response = self.client.generate_content([prompt, img])
                response_text = response.text or ""

            cleaned = self._clean_json_output(response_text)
            result = json.loads(cleaned)
            result["available"] = True
            logger.info(f"Vision AI Diagnosis for [{current_step_name}]: {result.get('status')} - {result.get('description')}")
            return result

        except Exception as e:
            logger.error(f"Error during Vision AI screen analysis: {e}", exc_info=True)
            return {
                "available": True,
                "status": "ERROR_STATE",
                "reason": str(e),
                "action": "NEED_USER_INPUT"
            }

    def explore_and_decide_next_step(self, screenshot_png_bytes: bytes, current_step_name: str,
                                     context_url: str = "", user_instruction: str = "") -> Dict[str, Any]:
        """主動探索畫面並決定下一步操作 (Agent Screen Exploration & Decision).

        結合使用者介入指示與截圖分析，判斷畫面是否已完成、是否有彈窗需要關閉、或推薦點擊哪個元素以推進下一步。
        """
        if not self.is_available():
            logger.warning("Gemini Vision AI 未就緒 (無 API Key)，回退至啟發式判斷模式。")
            return {
                "available": False,
                "status": "HEURISTIC_MODE",
                "action": "CLICK_ELEMENT",
                "description": "Vision AI 未就緒，依啟發式規則建議尋找畫面上之『關閉』或『確認』按鈕",
                "target_text": "關閉",
                "suggested_xpath": "//ytcp-button[@id='close-button'] | //*[contains(text(), '關閉')]/ancestor::ytcp-button | //*[contains(text(), '關閉')]",
                "completed": False
            }

        instruction_text = f"\n使用者額外介入指示：【{user_instruction}】" if user_instruction else ""

        prompt = f"""
你是一個具備全方位畫面決策能力的自動化 RPA Agent。
當前自動化流程在執行【{current_step_name}】時疑似停滯或卡住，使用者呼叫了你進行畫面探索與決策。
網址背景：{context_url}{instruction_text}

請仔細審視當前網頁截圖，回答以下核心問題並制定下一步行動方案：
1. 當前畫面是否已經顯示成功完成的標誌（例如「影片已發布」、「上傳完成」、「發布成功」對話框）？
2. 是否有干擾彈窗、完成對話框、關閉按鈕（例如右下角『關閉』、右上角『X』）或確認按鈕需要點擊？
3. 根據使用者指示與畫面現狀，下一步最合理的自動化操作是什麼？

請嚴格以 JSON 格式回應，不要包含任何 markdown 標籤或額外文字：
{{
  "status": "STEP_COMPLETED" | "CLICK_ACTION" | "POPUP_DETECTED" | "WAIT_MORE" | "MANUAL_ACTION_NEEDED",
  "description": "簡潔明確地說明你在畫面上看到了什麼、判斷的依據",
  "action": "CLICK_ELEMENT" | "MARK_COMPLETED" | "WAIT" | "NEED_USER_INPUT",
  "target_text": "若需要點擊元素，請提供該按鈕或標籤的精確文字（例如：'關閉'、'知道了'、'發布'）",
  "suggested_xpath": "若可推導出 XPath 則提供，若多種可能可用 '|' 連接",
  "completed": true 或 false (若畫面表明發布或步驟已達成目標，請設為 true),
  "confidence": 0.0 到 1.0 的信心度數值,
  "next_step_recommendation": "給自動化程式的下一步具體建議"
}}
"""

        try:
            response_text = ""
            if hasattr(self.client, "models"):
                from google.genai import types
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=[
                        types.Part.from_bytes(data=screenshot_png_bytes, mime_type="image/png"),
                        prompt
                    ]
                )
                response_text = response.text or ""
            else:
                import io
                from PIL import Image
                img = Image.open(io.BytesIO(screenshot_png_bytes))
                response = self.client.generate_content([prompt, img])
                response_text = response.text or ""

            cleaned = self._clean_json_output(response_text)
            result = json.loads(cleaned)
            result["available"] = True
            logger.info(f"Agent Screen Exploration Decision: {result.get('status')} - {result.get('description')} (action: {result.get('action')})")
            return result
        except Exception as e:
            logger.error(f"Error during Agent screen exploration: {e}", exc_info=True)
            return {
                "available": True,
                "status": "ERROR_STATE",
                "action": "NEED_USER_INPUT",
                "description": f"畫面分析時發生錯誤: {e}",
                "completed": False
            }

    @staticmethod
    def _clean_json_output(raw_text: str) -> str:
        text = raw_text.strip()
        # Remove markdown code block fences if present
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()

