import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_dir = os.path.join(root_dir, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from video_rpa.core.knowledge_store import KnowledgeStore
from video_rpa.core.smart_driver import SmartDriver
from video_rpa.core.vision_analyzer import VisionAnalyzer


class TestAgentScreenExploration(unittest.TestCase):
    def test_vision_explore_fallback_when_no_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            analyzer = VisionAnalyzer(api_key=None)
            res = analyzer.explore_and_decide_next_step(
                screenshot_png_bytes=b"dummy_bytes",
                current_step_name="等待 YouTube 影片上傳完成",
                user_instruction="請幫我點關閉"
            )
            self.assertEqual(res["status"], "HEURISTIC_MODE")
            self.assertEqual(res["action"], "CLICK_ELEMENT")
            self.assertIn("關閉", res["suggested_xpath"])

    def test_vision_explore_with_gemini_response(self):
        analyzer = VisionAnalyzer(api_key="fake_key")
        analyzer.client = MagicMock()

        mock_json_response = {
            "status": "STEP_COMPLETED",
            "description": "畫面上已顯示影片已發布對話框，右下角有關閉按鈕",
            "action": "CLICK_ELEMENT",
            "target_text": "關閉",
            "suggested_xpath": "//ytcp-button[@id='close-button']",
            "completed": True,
            "confidence": 0.98,
            "next_step_recommendation": "點擊關閉按鈕完成流程"
        }

        mock_content = MagicMock()
        mock_content.text = f"```json\n{json.dumps(mock_json_response)}\n```"
        analyzer.client.models.generate_content.return_value = mock_content

        res = analyzer.explore_and_decide_next_step(
            screenshot_png_bytes=b"fake_screenshot",
            current_step_name="等待 YouTube 影片上傳完成",
            context_url="https://studio.youtube.com",
            user_instruction="分析畫面並決定下一步"
        )

        self.assertEqual(res["status"], "STEP_COMPLETED")
        self.assertTrue(res["completed"])
        self.assertEqual(res["suggested_xpath"], "//ytcp-button[@id='close-button']")
        self.assertEqual(res["target_text"], "關閉")

    def test_smart_driver_execute_agent_exploration_click_and_complete(self):
        mock_driver = MagicMock()
        mock_driver.get_screenshot_as_png.return_value = b"fake_png"
        mock_driver.current_url = "https://studio.youtube.com"

        mock_elem = MagicMock()
        mock_elem.is_displayed.return_value = True
        mock_driver.find_elements.return_value = [mock_elem]

        mock_store = MagicMock()
        mock_store.get_platform.return_value = "youtube"

        mock_vision = MagicMock()
        mock_vision.explore_and_decide_next_step.return_value = {
            "status": "STEP_COMPLETED",
            "description": "檢測到影片已發布對話框，建議點擊關閉按鈕",
            "action": "CLICK_ELEMENT",
            "suggested_xpath": "//ytcp-button[@id='close-button']",
            "target_text": "關閉",
            "completed": True,
            "confidence": 0.95
        }

        smart_driver = SmartDriver(mock_driver, mock_store, mock_vision)

        with patch("video_rpa.core.smart_driver.WebDriverUtil.dispatch_click_events") as mock_click:
            result = smart_driver.execute_agent_screen_exploration(
                current_step_name="等待 YouTube 影片上傳完成",
                user_instruction="請點擊關閉"
            )

            self.assertTrue(result["success"])
            self.assertTrue(result["completed"])
            self.assertTrue(result["clicked"])
            mock_click.assert_called_once_with(mock_driver, mock_elem)


if __name__ == "__main__":
    unittest.main()
