"""Video RPA WebDriver 輔助工具類."""

import logging
import os
import subprocess
import time
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, SessionNotCreatedException

logger = logging.getLogger(__name__)


class WebDriverUtil:
    CHROME_DATA_DIR = "d:/work/workspace/java/rpa/chrome-data"

    @staticmethod
    def _cleanup_chrome(data_dir: str):
        try:
            norm_dir = os.path.normpath(data_dir).lower()
            temp_dir_name = "chrome_rpa_temp"

            # Surgical kill using psutil first if available
            killed = False
            try:
                import psutil
                for p in psutil.process_iter(['name', 'cmdline']):
                    try:
                        if p.info['name'] and 'chrome' in p.info['name'].lower():
                            cmdline = " ".join(p.info['cmdline'] or []).lower()
                            if norm_dir in cmdline or temp_dir_name in cmdline:
                                p.kill()
                                killed = True
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except ImportError:
                pass

            if not killed:
                alt_dir = data_dir.replace('\\', '/')
                ps_cmd = (
                    f'powershell -Command "Get-CimInstance Win32_Process -Filter \\"Name = \'chrome.exe\'\\" | '
                    f'Where-Object {{ `$_.CommandLine -like \'*--user-data-dir={norm_dir}*\' -or `$_.CommandLine -like \'*--user-data-dir={alt_dir}*\' -or `$_.CommandLine -like \'*chrome_rpa_temp*\' }} | '
                    f'Stop-Process -Force"'
                )
                logger.info(f"Cleanup: Killing existing Chrome processes using {data_dir}...")
                subprocess.run(ps_cmd, shell=True, capture_output=True)

            # Kill any orphaned chromedrivers
            subprocess.run('taskkill /F /IM chromedriver.exe /T', shell=True, capture_output=True)

            # Root lock files in the RPA-specific directory
            lock_files = [
                os.path.join(data_dir, "SingletonLock"),
                os.path.join(data_dir, "DevToolsActivePort")
            ]

            # Profile-specific lock files
            profile_dir = os.path.join(data_dir, "Default")
            if os.path.exists(profile_dir):
                lock_files.extend([
                    os.path.join(profile_dir, "LOCK"),
                    os.path.join(profile_dir, "Parent.lock")
                ])

            for f in lock_files:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                        logger.info(f"Cleanup: Removed {os.path.basename(f)} from RPA profile.")
                    except Exception as e:
                        logger.debug(f"Could not remove {f}: {e}")

            time.sleep(0.3)
        except Exception as ex:
            logger.error(f"Failed to cleanup Chrome environment: {ex}")

    @staticmethod
    def get_chrome_version():
        """Detect actual Chrome version on Windows."""
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon")
            version, _ = winreg.QueryValueEx(key, "version")
            return version
        except Exception:
            try:
                # Fallback to file version
                import subprocess
                cmd = r'(Get-Item "C:\Program Files\Google\Chrome\Application\chrome.exe").VersionInfo.FileVersion'
                res = subprocess.run(["powershell", "-Command", cmd], capture_output=True, text=True)
                return res.stdout.strip()
            except Exception:
                return None

    @staticmethod
    def _create_options(user_data_dir: str, binary_location: Optional[str] = None) -> Options:
        options = Options()
        if binary_location and os.path.exists(binary_location):
            options.binary_location = binary_location

        options.add_argument(f"--user-data-dir={user_data_dir}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-gpu-compositing")
        options.add_argument("--no-zygote")
        options.add_argument("--remote-allow-origins=*")
        options.add_argument("--disable-extensions")
        options.add_argument("--start-maximized")
        return options

    @staticmethod
    def initialize_driver() -> webdriver.Chrome:
        # Normalize path for Windows
        data_dir = os.path.normpath(WebDriverUtil.CHROME_DATA_DIR)

        # Always cleanup before starting
        WebDriverUtil._cleanup_chrome(data_dir)

        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        binary_location = chrome_path if os.path.exists(chrome_path) else None

        options = WebDriverUtil._create_options(data_dir, binary_location)

        # Detect version to avoid WDM downloading wrong version
        chrome_version = WebDriverUtil.get_chrome_version()
        logger.info(f"Detected Chrome version: {chrome_version}")

        driver_path = ChromeDriverManager(driver_version=chrome_version).install() if chrome_version else ChromeDriverManager().install()
        service = Service(driver_path)

        try:
            driver = webdriver.Chrome(service=service, options=options)
            logger.info(f"Successfully started Chrome with persistent profile: {data_dir}")
            return driver
        except Exception as e:
            logger.warning(f"Chrome Driver start FAILED with persistent profile: {e}")

            # Final attempt: Try with a TEMPORARY profile to see if the issue is profile corruption
            temp_dir = os.path.join(os.environ.get('TEMP', 'C:\\temp'), 'chrome_rpa_temp')
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)

            logger.info(f"Attempting launch with TEMPORARY profile: {temp_dir}")
            temp_options = WebDriverUtil._create_options(temp_dir, binary_location)

            try:
                return webdriver.Chrome(service=service, options=temp_options)
            except Exception as e2:
                logger.error(f"Critical failure: Chrome cannot start even with a fresh profile. Error: {e2}")
                raise e2

    @staticmethod
    def find_element(driver: webdriver.Chrome, step_name: str, by: str, value: str, element_name: str, timeout: int = 5) -> WebElement:
        while True:
            try:
                element = WebDriverWait(driver, timeout).until(
                    EC.presence_of_element_located((by, value))
                )
                logger.info(f"已找到 {element_name} : {value}")
                return element
            except TimeoutException:
                logger.info(f"步驟 : {step_name}, 持續尋找中 {element_name}...")
                time.sleep(2)

    @staticmethod
    def find_clickable_element(driver: webdriver.Chrome, step_name: str, by: str, value: str, element_name: str, timeout: int = 5) -> WebElement:
        while True:
            try:
                element = WebDriverWait(driver, timeout).until(
                    EC.element_to_be_clickable((by, value))
                )
                return element
            except TimeoutException:
                logger.info(f"步驟 : {step_name}, 持續尋找中 {element_name}...")
                time.sleep(2)

    @staticmethod
    def dispatch_click_events(driver: webdriver.Chrome, element: WebElement):
        script = """
            var evt1 = new MouseEvent('mousedown', {bubbles: true, cancelable: true, view: window});
            var evt2 = new MouseEvent('mouseup', {bubbles: true, cancelable: true, view: window});
            var evt3 = new MouseEvent('click', {bubbles: true, cancelable: true, view: window});
            arguments[0].dispatchEvent(evt1);
            arguments[0].dispatchEvent(evt2);
            arguments[0].dispatchEvent(evt3);
        """
        driver.execute_script(script, element)
