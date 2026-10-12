import os
import sys
import unittest
from unittest.mock import MagicMock, patch

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_dir = os.path.join(root_dir, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from video_rpa.core.hitl_controller import HitlInterventionController
from video_rpa.services.youtube_service import YouTubeService


class TestYouTubePublishDialog(unittest.TestCase):
    def setUp(self):
        HitlInterventionController.reset_instance()

    def tearDown(self):
        HitlInterventionController.reset_instance()

    def test_wait_for_upload_detects_published_dialog(self):
        service = YouTubeService()
        mock_driver = MagicMock()
        mock_smart = MagicMock()
        service.smart_driver = mock_smart

        mock_published_elem = MagicMock()
        mock_published_elem.is_displayed.return_value = True

        # find_elements returns published_elem on published_elements check
        def mock_find_elements(by, value):
            if "影片已發布" in value or "ytcp-video-share-dialog" in value:
                return [mock_published_elem]
            return []

        mock_driver.find_elements.side_effect = mock_find_elements

        # Should detect the published dialog immediately and return without timing out
        service._wait_for_upload_complete(mock_driver, timeout=5)

    def test_wait_for_upload_hitl_agent_intervention(self):
        service = YouTubeService()
        mock_driver = MagicMock()
        mock_smart = MagicMock()
        service.smart_driver = mock_smart

        # Simulate user triggering agent exploration via HITL input window
        controller = HitlInterventionController.get_instance()
        controller.trigger_agent_exploration("發現畫面卡在發布對話框，請分析並決定下一步")

        # Mock agent exploration returning completed
        mock_smart.execute_agent_screen_exploration.return_value = {
            "success": True,
            "completed": True,
            "clicked": True,
            "action_taken": "點擊關閉發布對話框"
        }

        # _wait_for_upload_complete should process intervention and return cleanly
        service._wait_for_upload_complete(mock_driver, timeout=5)
        mock_smart.execute_agent_screen_exploration.assert_called_once()
        self.assertFalse(controller.is_intervention_requested())

    def test_wait_for_upload_hitl_skip(self):
        service = YouTubeService()
        mock_driver = MagicMock()
        mock_smart = MagicMock()
        service.smart_driver = mock_smart

        # Simulate user triggering manual skip
        controller = HitlInterventionController.get_instance()
        controller.trigger_skip()

        service._wait_for_upload_complete(mock_driver, timeout=5)
        self.assertFalse(controller.is_skip_requested())

    def test_save_and_close_dismisses_dialog(self):
        service = YouTubeService()
        mock_driver = MagicMock()
        mock_smart = MagicMock()
        service.smart_driver = mock_smart
        mock_smart.click_step.return_value = True

        # Mock _wait_for_upload_complete to return immediately
        with patch.object(service, "_wait_for_upload_complete"):
            service._save_and_close(mock_driver)
            mock_smart.click_step.assert_any_call("done_button", timeout=15)
            mock_smart.click_step.assert_any_call("close_dialog_button", timeout=10)


if __name__ == "__main__":
    unittest.main()
