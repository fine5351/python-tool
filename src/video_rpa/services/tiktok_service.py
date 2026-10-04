"""Video RPA TikTok 上傳服務模組."""

import logging
import os
import re
import time
from typing import List, Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from video_rpa.constants import AutoAppendHashtag
from video_rpa.core.knowledge_store import KnowledgeStore
from video_rpa.core.smart_driver import SmartDriver
from video_rpa.core.vision_analyzer import VisionAnalyzer
from video_rpa.knowledge import get_knowledge_path
from video_rpa.utils.webdriver_util import WebDriverUtil

logger = logging.getLogger(__name__)


class TikTokService:
    """TikTok video upload service integrated with SmartDriver self-healing."""

    def __init__(self, knowledge_file: Optional[str] = None):
        default_file = get_knowledge_path("tiktok")
        self.store = KnowledgeStore(knowledge_file or default_file)
        self.vision = VisionAnalyzer()
        self.smart_driver: Optional[SmartDriver] = None

    def _ensure_smart_driver(self, driver):
        if self.smart_driver is None or self.smart_driver.driver != driver:
            self.smart_driver = SmartDriver(driver, self.store, self.vision)

    def upload_video(self, file_path: str, title: str, description: str, visibility: str,
                     hashtags: List[str], keep_open_on_failure: bool) -> bool:
        driver = None
        success = False
        try:
            driver = WebDriverUtil.initialize_driver()
            self._ensure_smart_driver(driver)
            self.start_upload_form(driver, file_path, title, description, hashtags)
            self.wait_and_publish(driver)
            success = True
            return True
        except Exception as e:
            logger.error(f"Error during TikTok upload: {e}", exc_info=True)
            return False
        finally:
            if driver is not None:
                if success or not keep_open_on_failure:
                    driver.quit()
                    logger.info("Browser closed successfully.")
                else:
                    logger.warning("Browser left open for debugging.")

    def start_upload_form(self, driver, file_path: str, title: str, description: str, hashtags: List[str]):
        self._ensure_smart_driver(driver)
        final_caption = self._build_caption(title, description, hashtags)
        logger.info(f"Processed Caption: {final_caption}")

        self._navigate_to_upload(driver)
        self._upload_file(driver, file_path)
        self._set_caption(driver, final_caption)

    def wait_and_publish(self, driver):
        self._ensure_smart_driver(driver)
        self._wait_for_upload_complete(driver)
        self._post_video(driver)

    def _build_caption(self, title: str, description: str, hashtags: List[str]) -> str:
        caption = ""
        if title:
            caption += f"{title}\n"
        if description:
            caption += f"{description}\n"

        if title:
            for keyword in AutoAppendHashtag.AUTO_HASHTAG_KEYWORDS:
                if keyword in title:
                    hashtag = f" #{keyword}"
                    if hashtag not in caption:
                        caption += hashtag

        if hashtags:
            for tag in hashtags:
                hashtag = f" #{tag}"
                if hashtag not in caption:
                    caption += hashtag

        return caption.strip()

    def _navigate_to_upload(self, driver):
        logger.info("步驟 : 前往上傳頁面 (https://www.tiktok.com/tiktokstudio/upload)...")
        driver.get("https://www.tiktok.com/tiktokstudio/upload")
        self.smart_driver.check_and_dismiss_known_popups()

        time.sleep(2)
        current_url = driver.current_url.lower()
        if "login" in current_url:
            print("\n" + "=" * 64)
            print("🚨 [登入檢查] 檢測到 TikTok 尚未登入或憑證已失效！")
            print("瀏覽器已停留在登入頁面，請在開啟的視窗中完成登入。")
            print("系統正即時偵測中，登入成功後將自動無縫接續上傳流程...")
            print("=" * 64 + "\n")
            logger.warning("檢測到 TikTok 尚未登入，等待使用者在瀏覽器完成登入中 (最長等待 5 分鐘)...")

            login_start = time.time()
            while time.time() - login_start < 300:
                time.sleep(3)
                current_url = driver.current_url.lower()
                if "login" not in current_url:
                    print("\n✅ 檢測到 TikTok 登入成功！繼續執行上傳流程...\n")
                    logger.info("✅ 檢測到 TikTok 登入成功，繼續執行上傳流程。")
                    driver.get("https://www.tiktok.com/tiktokstudio/upload")
                    time.sleep(3)
                    break
            else:
                raise RuntimeError("TikTok 登入等待逾時 (5分鐘)，請重新執行。")

    def _upload_file(self, driver, file_path: str):
        logger.info(f"步驟 : 上傳檔案 {file_path}...")
        self.smart_driver.check_and_dismiss_known_popups()
        file_input = self.smart_driver.find_smart_element("file_input", timeout=15)
        if file_input:
            file_input.send_keys(file_path)
            logger.info("檔案路徑已送出。")
        else:
            raise RuntimeError("無法定位 TikTok 檔案上傳輸入框。")

    def _wait_for_upload_complete(self, driver):
        logger.info("步驟 : 等待影片上傳完成...")
        start_time = time.time()
        timeout = 3600  # Up to 60 minutes
        completed = False

        while time.time() - start_time < timeout:
            is_uploading = False
            try:
                progress_elements = driver.find_elements(By.XPATH, "//div[contains(text(), '%')]")
                for el in progress_elements:
                    try:
                        text = el.text
                        if re.match(r".*\d+%.*", text) and "100%" not in text:
                            is_uploading = True
                            logger.info(f"TikTok 上傳進度: {text}")
                            break
                    except Exception:
                        continue
            except Exception:
                pass

            if not is_uploading:
                try:
                    success_elements = driver.find_elements(
                        By.XPATH, "//*[contains(text(), 'Uploaded') or contains(text(), '上傳完畢') or contains(text(), '已上傳')]"
                    )
                    if success_elements:
                        try:
                            logger.info(f"Upload complete indicator found: {success_elements[0].text}")
                        except Exception:
                            logger.info("Upload complete indicator found.")
                        completed = True
                        break
                except Exception:
                    pass

            time.sleep(2)

        if not completed:
            raise RuntimeError("TikTok 影片上傳逾時，未能在時限內完成上傳。")

        logger.info("Upload complete, waiting 3 seconds for UI to stabilize...")
        time.sleep(3)

    def _set_caption(self, driver, caption: str):
        if not caption:
            return
        try:
            logger.info("步驟 : 設定文案內容與標籤...")
            editor = self.smart_driver.find_smart_element("caption_editor", timeout=15, clickable=True)
            if not editor:
                logger.warning("未找到文案輸入框，跳過文案設定。")
                return

            editor.click()
            editor.send_keys(Keys.CONTROL + "a")
            editor.send_keys(Keys.BACK_SPACE)

            parts = caption.split(" ")
            for part in parts:
                editor.send_keys(part)
                time.sleep(1.5)
                if part.startswith("#"):
                    try:
                        mention_lists = driver.find_elements(By.XPATH, "//div[contains(@class, 'mention-list')]")
                        if mention_lists:
                            suggestions = driver.find_elements(By.XPATH, "//div[contains(@class, 'hashtag-suggestion-item')]")
                            target_tag = part.replace("#", "")
                            best_match = None
                            max_count = -1

                            for suggestion in suggestions:
                                try:
                                    topic_el = suggestion.find_element(By.XPATH, ".//span[contains(@class, 'hash-tag-topic')]")
                                    count_el = suggestion.find_element(By.XPATH, ".//span[contains(@class, 'hash-tag-view-count')]")
                                    tag_name = topic_el.text.strip()
                                    count_text = count_el.text.strip()
                                    count = self._parse_count(count_text)

                                    if tag_name.replace("#", "").lower() == target_tag.lower():
                                        if count > max_count:
                                            max_count = count
                                            best_match = suggestion
                                except Exception:
                                    pass

                            if best_match:
                                best_match.click()
                            elif suggestions:
                                suggestions[0].click()
                    except Exception as e:
                        logger.debug(f"標籤彈出選單處理略過: {e}")

                editor.send_keys(" ")

            logger.info("Caption set.")
        except Exception as e:
            logger.warning(f"Could not set caption: {e}")

    def _parse_count(self, count_text: str) -> int:
        s = re.sub(r'[^0-9.KMB]', '', count_text.upper())
        if not s:
            return 0
        multiplier = 1
        if s.endswith("K"):
            multiplier = 1_000
            s = s[:-1]
        elif s.endswith("M"):
            multiplier = 1_000_000
            s = s[:-1]
        elif s.endswith("B"):
            multiplier = 1_000_000_000
            s = s[:-1]
        try:
            return int(float(s) * multiplier)
        except Exception:
            return 0

    def _post_video(self, driver):
        logger.info("步驟 : 點擊發佈按鈕...")
        self.smart_driver.check_and_dismiss_known_popups()

        post_button = self.smart_driver.find_smart_element("post_button", timeout=15, clickable=True)
        if not post_button:
            raise RuntimeError("無法定位 TikTok 發佈按鈕。")

        try:
            post_button.click()
        except Exception as e:
            logger.info(f"Normal click intercepted, trying JS click: {e}")
            driver.execute_script("arguments[0].click();", post_button)

        logger.info("Clicked Post button. Checking for any post confirmation popups...")

        for _ in range(6):
            time.sleep(2)
            # Check if post success indicator is already present
            success_elem = self.smart_driver.find_smart_element("success_indicator", timeout=2)
            if success_elem:
                logger.info("檢測到發佈成功標誌！")
                return

            # Check and dismiss known confirmation modals (like 立即發佈, TUXModal)
            handled = self.smart_driver.check_and_dismiss_known_popups()
            if handled:
                logger.info("已自動確認排除發佈彈窗。")

        logger.info("TikTok 發佈流程全部完成！")
