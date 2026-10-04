import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Ensure src directory is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_dir = os.path.join(root_dir, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from video_rpa.core.knowledge_store import KnowledgeStore
from video_rpa.core.vision_analyzer import VisionAnalyzer
from video_rpa.core.hitl_handler import HitlHandler
from video_rpa.core.smart_driver import SmartDriver
from video_rpa.services.youtube_service import YouTubeService


class TestKnowledgeStore(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.temp_file.close()
        initial_data = {
            "version": "1.0.0",
            "steps": {
                "test_step": {
                    "name": "測試步驟",
                    "timeout": 5,
                    "locators": [
                        {"by": "xpath", "value": "//button[@id='btn1']", "weight": 5},
                        {"by": "xpath", "value": "//button[@id='btn2']", "weight": 10}
                    ]
                }
            },
            "known_popups": []
        }
        with open(self.temp_file.name, "w", encoding="utf-8") as f:
            json.dump(initial_data, f)
        self.store = KnowledgeStore(self.temp_file.name)

    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            os.remove(self.temp_file.name)

    def test_get_locators_sorted_by_weight(self):
        locators = self.store.get_locators("test_step")
        self.assertEqual(len(locators), 2)
        # btn2 has weight 10, btn1 has weight 5
        self.assertEqual(locators[0]["value"], "//button[@id='btn2']")
        self.assertEqual(locators[1]["value"], "//button[@id='btn1']")

    def test_record_success_boosts_weight(self):
        self.store.record_success("test_step", "//button[@id='btn1']")
        # Reload to verify persistence
        new_store = KnowledgeStore(self.temp_file.name)
        locators = new_store.get_locators("test_step")
        btn1 = next(l for l in locators if l["value"] == "//button[@id='btn1']")
        self.assertEqual(btn1["weight"], 7)

    def test_add_or_update_locator(self):
        self.store.add_or_update_locator("test_step", "xpath", "//button[@id='btn_learned']", weight=15)
        new_store = KnowledgeStore(self.temp_file.name)
        locators = new_store.get_locators("test_step")
        self.assertEqual(locators[0]["value"], "//button[@id='btn_learned']")
        self.assertEqual(locators[0]["weight"], 15)

    def test_add_known_popup(self):
        self.store.add_known_popup("Test Popup", "//div[@class='popup']", "click", "//button[@class='close']")
        popups = self.store.get_known_popups()
        self.assertEqual(len(popups), 1)
        self.assertEqual(popups[0]["name"], "Test Popup")


class TestVisionAnalyzer(unittest.TestCase):
    def test_clean_json_output(self):
        raw_json_md = '```json\n{"status": "POPUP_DETECTED", "action": "DISMISS_POPUP"}\n```'
        cleaned = VisionAnalyzer._clean_json_output(raw_json_md)
        data = json.loads(cleaned)
        self.assertEqual(data["status"], "POPUP_DETECTED")
        self.assertEqual(data["action"], "DISMISS_POPUP")

    def test_unavailable_when_no_key(self):
        with patch.dict(os.environ, {}, clear=True):
            analyzer = VisionAnalyzer(api_key=None)
            self.assertFalse(analyzer.is_available())
            res = analyzer.analyze_screen_state(b"dummy", "測試步驟")
            self.assertEqual(res["status"], "UNKNOWN")
            self.assertEqual(res["action"], "NEED_USER_INPUT")


class TestHitlHandler(unittest.TestCase):
    @patch("builtins.input", side_effect=["1", "//div[@id='manual_xpath']"])
    def test_terminal_prompt_manual_xpath(self, mock_input):
        mock_driver = MagicMock()
        res = HitlHandler._terminal_prompt(mock_driver, "step_1", "測試步驟")
        self.assertEqual(res["status"], "RESOLVED")
        self.assertEqual(res["value"], "//div[@id='manual_xpath']")
        self.assertFalse(res["is_new_step"])

    @patch("builtins.input", return_value="2")
    def test_terminal_prompt_skip(self, mock_input):
        mock_driver = MagicMock()
        res = HitlHandler._terminal_prompt(mock_driver, "step_1", "測試步驟")
        self.assertEqual(res["status"], "SKIPPED")


class TestSmartDriver(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.temp_file.close()
        initial_data = {
            "version": "1.0.0",
            "steps": {
                "upload_btn": {
                    "name": "建立按鈕",
                    "timeout": 2,
                    "locators": [
                        {"by": "xpath", "value": "//button[@id='real_btn']", "weight": 10}
                    ]
                },
                "optional_step": {
                    "name": "可選步驟",
                    "timeout": 1,
                    "optional": True,
                    "locators": [
                        {"by": "xpath", "value": "//div[@id='missing']", "weight": 5}
                    ]
                }
            },
            "known_popups": [
                {
                    "name": "Sample Dialog",
                    "detect_xpath": "//div[@id='modal']",
                    "action": "click",
                    "target_xpath": "//button[@id='close_modal']"
                }
            ]
        }
        with open(self.temp_file.name, "w", encoding="utf-8") as f:
            json.dump(initial_data, f)
        self.store = KnowledgeStore(self.temp_file.name)
        self.mock_driver = MagicMock()
        self.mock_vision = MagicMock()
        self.smart_driver = SmartDriver(self.mock_driver, self.store, self.mock_vision)

    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            os.remove(self.temp_file.name)

    def test_check_and_dismiss_known_popups(self):
        mock_elem = MagicMock()
        mock_elem.is_displayed.return_value = True
        self.mock_driver.find_elements.return_value = [mock_elem]

        with patch("selenium.webdriver.support.ui.WebDriverWait.until", return_value=mock_elem):
            with patch("video_rpa.core.smart_driver.WebDriverUtil.dispatch_click_events") as mock_click:
                dismissed = self.smart_driver.check_and_dismiss_known_popups()
                self.assertTrue(dismissed)
                mock_click.assert_called_once()

    def test_optional_step_returns_none_when_not_found(self):
        self.mock_vision.is_available.return_value = False
        self.mock_driver.find_elements.return_value = []
        with patch("selenium.webdriver.support.ui.WebDriverWait.until", side_effect=Exception("Timeout")):
            elem = self.smart_driver.find_smart_element("optional_step")
            self.assertIsNone(elem)

    def test_ai_element_found_recovery(self):
        self.mock_vision.is_available.return_value = True
        self.mock_driver.get_screenshot_as_png.return_value = b"fake_png"
        self.mock_driver.current_url = "https://studio.youtube.com"
        self.mock_driver.find_elements.return_value = []

        self.mock_vision.analyze_screen_state.return_value = {
            "status": "ELEMENT_FOUND",
            "confidence": 0.95,
            "suggested_xpath": "//button[@id='ai_found_btn']",
            "description": "Found new upload button"
        }

        mock_elem = MagicMock()

        def mock_find_element(by, value):
            if value == "//button[@id='ai_found_btn']":
                return mock_elem
            raise Exception("Element not found")

        self.mock_driver.find_element.side_effect = mock_find_element

        def fake_until(method, message=""):
            return method(self.mock_driver)

        with patch("selenium.webdriver.support.ui.WebDriverWait.until", side_effect=fake_until):
            elem = self.smart_driver.find_smart_element("upload_btn", custom_timeout=0.2)
            self.assertEqual(elem, mock_elem)
            locators = self.store.get_locators("upload_btn")
            self.assertEqual(locators[0]["value"], "//button[@id='ai_found_btn']")

    def test_hitl_recovery(self):
        self.mock_vision.is_available.return_value = False
        self.mock_driver.find_elements.return_value = []

        mock_elem = MagicMock()

        def mock_find_element(by, value):
            if value == "//button[@id='human_picked_btn']":
                return mock_elem
            raise Exception("Element not found")

        self.mock_driver.find_element.side_effect = mock_find_element

        def fake_until(method, message=""):
            return method(self.mock_driver)

        with patch("selenium.webdriver.support.ui.WebDriverWait.until", side_effect=fake_until):
            with patch("video_rpa.core.smart_driver.HitlHandler.resolve_stuck_step", return_value={
                "status": "RESOLVED",
                "by": "xpath",
                "value": "//button[@id='human_picked_btn']",
                "is_new_step": False
            }):
                elem = self.smart_driver.find_smart_element("upload_btn", custom_timeout=0.2)
                self.assertEqual(elem, mock_elem)
                locators = self.store.get_locators("upload_btn")
                self.assertEqual(locators[0]["value"], "//button[@id='human_picked_btn']")


class TestYouTubeServiceIntegration(unittest.TestCase):
    def test_service_initialization(self):
        service = YouTubeService()
        self.assertIsNotNone(service.store)
        self.assertIsNotNone(service.vision)
        # Check that default knowledge loaded
        step = service.store.get_step("upload_button")
        self.assertIsNotNone(step)
        self.assertTrue(len(step["locators"]) > 0)

    def test_build_description(self):
        service = YouTubeService()
        desc = service._build_description("原神 測試影片", "這是測試說明", ["genshin", "rpa"])
        self.assertIn("#genshin", desc)
        self.assertIn("#rpa", desc)
        self.assertIn("這是測試說明", desc)

    def test_wait_for_upload_complete_detects_complete(self):
        service = YouTubeService()
        mock_driver = MagicMock()
        mock_smart = MagicMock()
        service.smart_driver = mock_smart
        mock_complete = MagicMock()
        mock_complete.is_displayed.return_value = True
        mock_driver.find_elements.side_effect = [
            [],  # progress_elements
            [mock_complete]  # complete_elements
        ]
        # Should return cleanly without exception
        service._wait_for_upload_complete(mock_driver, timeout=5)


class TestBilibiliServiceIntegration(unittest.TestCase):
    def test_service_initialization(self):
        from video_rpa.services.bilibili_service import BilibiliService
        service = BilibiliService()
        self.assertIsNotNone(service.store)
        self.assertIsNotNone(service.vision)
        step = service.store.get_step("submit_button")
        self.assertIsNotNone(step)

    def test_build_description(self):
        from video_rpa.services.bilibili_service import BilibiliService
        service = BilibiliService()
        desc = service._build_description("原神 測試", "說明內容", ["tag1"])
        self.assertIn("tag1", desc)


if __name__ == "__main__":
    unittest.main()
