"""Unit tests for BilibiliService and YouTubeService upload completion and publish workflows."""

import unittest
from unittest.mock import MagicMock, patch
from selenium.webdriver.common.by import By

from video_rpa.services.bilibili_service import BilibiliService
from video_rpa.services.youtube_service import YouTubeService


class TestBilibiliServiceWorkflow(unittest.TestCase):
    def setUp(self):
        self.service = BilibiliService()
        self.mock_driver = MagicMock()
        self.service.smart_driver = MagicMock()

    def test_bilibili_has_wait_for_upload_complete(self):
        """Verify _wait_for_upload_complete exists and callable on BilibiliService."""
        self.assertTrue(hasattr(self.service, "_wait_for_upload_complete"))
        self.assertTrue(callable(getattr(self.service, "_wait_for_upload_complete")))

    def test_wait_for_upload_complete_detects_finished(self):
        """Verify _wait_for_upload_complete exits when complete elements detected."""
        mock_el = MagicMock()
        mock_el.is_displayed.return_value = True

        def find_elements_side_effect(by, query):
            if "上传中" in query:
                return []
            if "上传完成" in query:
                return [mock_el]
            return []

        self.mock_driver.find_elements.side_effect = find_elements_side_effect
        # Should return without exception
        self.service._wait_for_upload_complete(self.mock_driver, timeout=5)

    def test_wait_for_upload_complete_detects_submit_button_enabled(self):
        """Verify _wait_for_upload_complete exits when submit button becomes enabled."""
        mock_btn = MagicMock()
        mock_btn.is_displayed.return_value = True
        mock_btn.get_attribute.side_effect = lambda attr: "submit-add" if attr == "class" else None

        def find_elements_side_effect(by, query):
            if "上传中" in query or "上传完成" in query:
                return []
            if "立即投稿" in query:
                return [mock_btn]
            return []

        self.mock_driver.find_elements.side_effect = find_elements_side_effect
        self.service._wait_for_upload_complete(self.mock_driver, timeout=5)

    @patch.object(BilibiliService, "_wait_for_success")
    @patch.object(BilibiliService, "_click_submit")
    @patch.object(BilibiliService, "_select_cover")
    @patch.object(BilibiliService, "_set_creation_declaration")
    @patch.object(BilibiliService, "_wait_for_upload_complete")
    def test_wait_and_publish_calls_sequence(self, mock_wait, mock_decl, mock_cover, mock_submit, mock_success):
        """Verify wait_and_publish coordinates full publishing sequence."""
        self.service.wait_and_publish(self.mock_driver)
        mock_wait.assert_called_once_with(self.mock_driver)
        mock_decl.assert_called_once_with(self.mock_driver)
        mock_cover.assert_called_once_with(self.mock_driver)
        mock_submit.assert_called_once_with(self.mock_driver)
        mock_success.assert_called_once_with(self.mock_driver)


class TestYouTubeServiceWorkflow(unittest.TestCase):
    def setUp(self):
        self.service = YouTubeService()
        self.mock_driver = MagicMock()
        self.service.smart_driver = MagicMock()

    def test_wait_for_upload_complete_on_edit_page(self):
        """Verify _wait_for_upload_complete detects completion on /video/{id}/edit page."""
        self.mock_driver.current_url = "https://studio.youtube.com/video/HuBXygXdM_k/edit"
        status_el = MagicMock()
        status_el.is_displayed.return_value = True

        def find_elements_side_effect(by, query):
            if "上傳中" in query:
                return []
            if "ytcp-uploads-dialog" in query or by == By.TAG_NAME:
                return []
            if "上傳完畢" in query:
                return [status_el]
            return []

        self.mock_driver.find_elements.side_effect = find_elements_side_effect
        self.service._wait_for_upload_complete(self.mock_driver, timeout=5)

    @patch.object(YouTubeService, "_save_edit_page")
    @patch.object(YouTubeService, "_save_and_close")
    @patch.object(YouTubeService, "_navigate_wizard_pages")
    @patch.object(YouTubeService, "_wait_for_upload_complete")
    def test_wait_and_publish_branches_edit_page(self, mock_wait, mock_wiz, mock_close, mock_edit_save):
        """When dialog is closed and on edit page, wait_and_publish calls _save_edit_page."""
        # No dialogs displayed
        self.mock_driver.find_elements.return_value = []
        self.service.wait_and_publish(self.mock_driver)

        mock_wait.assert_called_once_with(self.mock_driver)
        mock_wiz.assert_not_called()
        mock_close.assert_not_called()
        mock_edit_save.assert_called_once_with(self.mock_driver)

    @patch.object(YouTubeService, "_set_visibility")
    @patch.object(YouTubeService, "_save_edit_page")
    @patch.object(YouTubeService, "_save_and_close")
    @patch.object(YouTubeService, "_navigate_wizard_pages")
    @patch.object(YouTubeService, "_wait_for_upload_complete")
    def test_wait_and_publish_branches_dialog(self, mock_wait, mock_wiz, mock_close, mock_edit_save, mock_vis):
        """When dialog is open, wait_and_publish calls wizard navigation."""
        mock_dialog = MagicMock()
        mock_dialog.is_displayed.return_value = True
        self.mock_driver.find_elements.return_value = [mock_dialog]

        self.service.wait_and_publish(self.mock_driver)

        mock_wait.assert_called_once_with(self.mock_driver)
        mock_wiz.assert_called_once_with(self.mock_driver)
        mock_vis.assert_called_once()
        mock_close.assert_called_once_with(self.mock_driver)
        mock_edit_save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
