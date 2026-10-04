import unittest
import os
from video_rpa.utils.webdriver_util import WebDriverUtil


class TestWebDriverUtilOptions(unittest.TestCase):
    def test_create_options_does_not_contain_remote_debugging_port(self):
        data_dir = "d:/dummy/path"
        options = WebDriverUtil._create_options(data_dir)
        args = options.arguments
        # Verify no --remote-debugging-port is present which causes ChromeDriver hang/failure
        self.assertFalse(any("--remote-debugging-port" in arg for arg in args),
                         "Options should not contain --remote-debugging-port")
        # Verify user-data-dir is present
        self.assertTrue(any(f"--user-data-dir={data_dir}" in arg for arg in args),
                        "Options should contain specified user-data-dir")


if __name__ == "__main__":
    unittest.main()
