import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure src directory is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_dir = os.path.join(root_dir, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from video_rpa.utils.webdriver_util import WebDriverUtil
from script.attach_chrome import list_tabs


class TestAttachChrome(unittest.TestCase):
    def test_default_debug_port(self):
        """驗證預設遠端除錯埠號為 9222."""
        self.assertEqual(WebDriverUtil.DEFAULT_DEBUG_PORT, 9222)

    def test_create_options_contains_debug_port_when_specified(self):
        """驗證當指定 debug_port 時 Chrome options 包含 remote-debugging-port 參數."""
        options = WebDriverUtil._create_options("some_dir", debug_port=9222)
        args = options.arguments
        self.assertTrue(any("--remote-debugging-port=9222" in arg for arg in args))

    def test_create_options_no_debug_port_by_default(self):
        """驗證預設情況下不包含 remote-debugging-port 參數."""
        options = WebDriverUtil._create_options("some_dir")
        args = options.arguments
        self.assertFalse(any("--remote-debugging-port" in arg for arg in args))

    @patch("socket.create_connection")
    def test_is_debug_port_open_true(self, mock_conn):
        """驗證當 socket 連線成功時回傳 True."""
        mock_conn.return_value.__enter__.return_value = MagicMock()
        self.assertTrue(WebDriverUtil.is_debug_port_open("127.0.0.1", 9222))

    @patch("socket.create_connection")
    def test_is_debug_port_open_false(self, mock_conn):
        """驗證當 socket 連線失敗時回傳 False."""
        mock_conn.side_effect = ConnectionRefusedError()
        self.assertFalse(WebDriverUtil.is_debug_port_open("127.0.0.1", 9222))

    @patch("video_rpa.utils.webdriver_util.WebDriverUtil.is_debug_port_open", return_value=False)
    def test_attach_driver_raises_when_port_closed(self, mock_is_open):
        """驗證當除錯埠未開啟時，attach_driver 拋出 ConnectionError."""
        with self.assertRaises(ConnectionError) as ctx:
            WebDriverUtil.attach_driver("127.0.0.1", 9222)
        self.assertIn("無法連線至 Chrome 遠端除錯埠", str(ctx.exception))

    @patch("video_rpa.utils.webdriver_util.WebDriverUtil.get_chrome_version", return_value=None)
    @patch("video_rpa.utils.webdriver_util.ChromeDriverManager")
    @patch("video_rpa.utils.webdriver_util.Service")
    @patch("video_rpa.utils.webdriver_util.webdriver.Chrome")
    @patch("video_rpa.utils.webdriver_util.WebDriverUtil.is_debug_port_open", return_value=True)
    def test_attach_driver_success(self, mock_is_open, mock_chrome, mock_service, mock_cdm, mock_ver):
        """驗證當除錯埠開放時，attach_driver 正確設定 debuggerAddress 並接入."""
        mock_driver_instance = MagicMock()
        mock_driver_instance.title = "Test Page"
        mock_chrome.return_value = mock_driver_instance

        driver = WebDriverUtil.attach_driver("127.0.0.1", 9222)
        self.assertEqual(driver, mock_driver_instance)

        # 檢查傳給 Chrome 的 options 包含 debuggerAddress
        _, kwargs = mock_chrome.call_args
        options = kwargs.get("options")
        self.assertIsNotNone(options)
        self.assertEqual(options.experimental_options.get("debuggerAddress"), "127.0.0.1:9222")

    def test_list_tabs(self):
        """驗證 list_tabs 能正確解析分頁與標記當前分頁."""
        mock_driver = MagicMock()
        mock_driver.window_handles = ["handle_1", "handle_2"]
        mock_driver.current_window_handle = "handle_1"

        def switch_side_effect(handle):
            if handle == "handle_1":
                mock_driver.title = "Page 1"
                mock_driver.current_url = "https://example.com/1"
            else:
                mock_driver.title = "Page 2"
                mock_driver.current_url = "https://example.com/2"

        mock_driver.switch_to.window.side_effect = switch_side_effect

        tabs = list_tabs(mock_driver)
        self.assertEqual(len(tabs), 2)
        self.assertEqual(tabs[0]["title"], "Page 1")
        self.assertEqual(tabs[0]["url"], "https://example.com/1")
        self.assertTrue(tabs[0]["is_current"])

        self.assertEqual(tabs[1]["title"], "Page 2")
        self.assertEqual(tabs[1]["url"], "https://example.com/2")
        self.assertFalse(tabs[1]["is_current"])

    @patch("video_rpa.utils.webdriver_util.WebDriverUtil.attach_driver")
    @patch("video_rpa.utils.webdriver_util.WebDriverUtil.is_debug_port_open", return_value=True)
    def test_get_or_create_driver_when_already_running(self, mock_is_open, mock_attach):
        """驗證 Chrome 已在運行時，get_or_create_driver 直接接入而不重複啟動."""
        mock_driver = MagicMock()
        mock_attach.return_value = mock_driver

        driver = WebDriverUtil.get_or_create_driver("127.0.0.1", 9222)
        self.assertEqual(driver, mock_driver)
        mock_attach.assert_called_once_with("127.0.0.1", 9222)

    @patch("video_rpa.utils.webdriver_util.WebDriverUtil.attach_driver")
    @patch("video_rpa.utils.webdriver_util.WebDriverUtil.launch_debug_chrome")
    @patch("video_rpa.utils.webdriver_util.WebDriverUtil.is_debug_port_open")
    def test_get_or_create_driver_auto_launches_when_not_running(self, mock_is_open, mock_launch, mock_attach):
        """驗證當 Chrome 未運行時，get_or_create_driver 自動啟動並接入."""
        # 第一次檢查未開，啟動後第二次檢查已開
        mock_is_open.side_effect = [False, True]
        mock_driver = MagicMock()
        mock_attach.return_value = mock_driver

        driver = WebDriverUtil.get_or_create_driver("127.0.0.1", 9222, data_dir="test_profile")
        self.assertEqual(driver, mock_driver)
        mock_launch.assert_called_once_with(port=9222, data_dir="test_profile")
        mock_attach.assert_called_once_with("127.0.0.1", 9222)

    @patch("video_rpa.utils.webdriver_util.WebDriverUtil.launch_debug_chrome")
    @patch("video_rpa.utils.webdriver_util.WebDriverUtil.is_debug_port_open", return_value=False)
    def test_get_or_create_driver_timeout(self, mock_is_open, mock_launch):
        """驗證啟動超時會拋出 TimeoutError."""
        with self.assertRaises(TimeoutError):
            WebDriverUtil.get_or_create_driver("127.0.0.1", 9222, timeout=0.1)


if __name__ == "__main__":
    unittest.main()

