"""Video RPA YouTube 上傳服務模組."""

import logging
import os
import time
from typing import List, Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from video_rpa.constants import AutoAppendHashtag
from video_rpa.core.knowledge_store import KnowledgeStore
from video_rpa.core.smart_driver import SmartDriver
from video_rpa.core.vision_analyzer import VisionAnalyzer
from video_rpa.knowledge import get_knowledge_path
from video_rpa.utils.webdriver_util import WebDriverUtil

logger = logging.getLogger(__name__)


class YouTubeService:
    """YouTube upload automation service powered by self-healing SmartDriver,
    screen prompt detection, and KnowledgeStore evolution."""

    def __init__(self, knowledge_file: Optional[str] = None):
        default_file = get_knowledge_path("youtube")
        self.store = KnowledgeStore(knowledge_file or default_file)
        self.vision = VisionAnalyzer()
        self.smart_driver: Optional[SmartDriver] = None

    def _ensure_smart_driver(self, driver):
        if self.smart_driver is None or self.smart_driver.driver != driver:
            self.smart_driver = SmartDriver(driver, self.store, self.vision)

    def upload_video(self, file_path: str, title: str, description: str, playlist: str, visibility: str,
                     hashtags: List[str], keep_open_on_failure: bool) -> bool:
        driver = None
        success = False
        try:
            driver = WebDriverUtil.initialize_driver()
            self._ensure_smart_driver(driver)
            self.start_upload_form(driver, file_path, title, description, playlist, visibility, hashtags)
            self.wait_and_publish(driver)
            success = True
            return True
        except Exception as e:
            logger.error(f"Error during YouTube upload: {e}", exc_info=True)
            return False
        finally:
            if driver is not None:
                if success or not keep_open_on_failure:
                    driver.quit()
                    logger.info("Browser closed successfully.")
                else:
                    logger.warning("Browser left open for debugging.")

    def start_upload_form(self, driver, file_path: str, title: str, description: str, playlist: str,
                          visibility: str, hashtags: List[str]):
        self._ensure_smart_driver(driver)
        self.visibility = visibility or "PUBLIC"
        final_description = self._build_description(title, description, hashtags)
        self._navigate_to_studio(driver)
        self._click_create_button(driver)
        self._select_upload_option(driver)
        self._upload_file(driver, file_path)
        self._enter_title_and_description(driver, title, final_description)
        self._select_playlist(driver, playlist)
        self._set_kids_restriction(driver)

    def wait_and_publish(self, driver):
        self._ensure_smart_driver(driver)
        self._wait_for_upload_complete(driver)
        dialogs = driver.find_elements(By.TAG_NAME, "ytcp-uploads-dialog")
        if any(d.is_displayed() for d in dialogs):
            self._navigate_wizard_pages(driver)
            self._set_visibility(driver, getattr(self, "visibility", "PUBLIC"))
            self._save_and_close(driver)
        else:
            self._save_edit_page(driver)

    def _build_description(self, title: str, description: str, hashtags: List[str]) -> str:
        if not description:
            description = ""
        description += "\n\n"

        if hashtags:
            for tag in hashtags:
                if tag not in description:
                    description += f"#{tag} "

        if title:
            for keyword in AutoAppendHashtag.AUTO_HASHTAG_KEYWORDS:
                if keyword in title:
                    description += f"#{keyword} "

        return description

    def _navigate_to_studio(self, driver):
        logger.info("步驟 : 前往 YouTube Studio (https://studio.youtube.com)...")
        driver.get("https://studio.youtube.com")
        self.smart_driver.check_and_dismiss_known_popups()

        time.sleep(2)
        current_url = driver.current_url.lower()
        if "accounts.google.com" in current_url or "signin" in current_url:
            print("\n" + "=" * 64)
            print("🚨 [登入檢查] 檢測到 YouTube / Google 尚未登入或憑證已失效！")
            print("瀏覽器已停留在登入頁面，請在開啟的視窗中完成 Google 登入。")
            print("系統正即時偵測中，登入成功後將自動無縫接續上傳流程...")
            print("=" * 64 + "\n")
            logger.warning("檢測到 YouTube 尚未登入，等待使用者在瀏覽器完成登入中 (最長等待 5 分鐘)...")

            login_start = time.time()
            while time.time() - login_start < 300:
                time.sleep(3)
                current_url = driver.current_url.lower()
                if "accounts.google.com" not in current_url and "signin" not in current_url:
                    print("\n✅ 檢測到 YouTube 登入成功！繼續執行上傳流程...\n")
                    logger.info("✅ 檢測到 YouTube 登入成功，繼續執行上傳流程。")
                    driver.get("https://studio.youtube.com")
                    time.sleep(3)
                    break
            else:
                raise RuntimeError("YouTube 登入等待逾時 (5分鐘)，請重新執行。")

        # Handle optional 'Continue' button if present
        continue_elem = self.smart_driver.find_smart_element("continue_button", custom_timeout=3)
        if continue_elem:
            try:
                continue_elem.click()
                logger.info("Clicked Studio Continue button.")
            except Exception:
                pass

    def _click_create_button(self, driver):
        logger.info("步驟 : 點擊建立按鈕...")
        self.smart_driver.check_and_dismiss_known_popups()
        if not self.smart_driver.click_step("upload_button", timeout=10):
            raise RuntimeError("無法定位或點擊建立/上傳按鈕 (Create Button)。")
        time.sleep(2)

    def _select_upload_option(self, driver):
        logger.info("步驟 : 選擇上傳影片選項...")
        # Check if file input is already present without clicking menu
        try:
            if driver.find_elements(By.XPATH, "//ytcp-uploads-dialog//input[@type='file'] | //input[@type='file']"):
                return
        except Exception:
            pass

        self.smart_driver.click_step("select_upload_option", timeout=8)
        time.sleep(2)

    def _upload_file(self, driver, file_path: str):
        if not file_path:
            raise ValueError("File path cannot be null or empty")
        logger.info(f"步驟 : 上傳檔案 {file_path}...")
        self.smart_driver.check_and_dismiss_known_popups()
        file_input = self.smart_driver.find_smart_element("file_input", timeout=15)
        if file_input:
            file_input.send_keys(file_path)
            logger.info(f"Sent file path: {file_path}")
            time.sleep(4)
        else:
            raise RuntimeError("無法定位上傳檔案輸入框 (File input)。")

    def _enter_title_and_description(self, driver, title: str, description: str):
        if title:
            logger.info(f"步驟 : 設定標題: {title}")
            self.smart_driver.input_step("title_input", title)

        if description:
            logger.info("步驟 : 設定說明內容...")
            self.smart_driver.input_step("description_input", description)

    def _select_playlist(self, driver, playlist: str):
        if not playlist:
            return
        logger.info(f"步驟 : 選擇播放清單: {playlist}")
        try:
            self.smart_driver.click_step("playlist_trigger", timeout=8)
            time.sleep(1)

            item_selector = (
                f"//li[contains(@class, 'ytcp-checkbox-group') and "
                f".//span[contains(@class, 'label-text') and normalize-space(text())='{playlist}']]//div[@id='checkbox-container']"
            )
            item = WebDriverWait(driver, 6).until(EC.element_to_be_clickable((By.XPATH, item_selector)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", item)
            item.click()
            logger.info(f"Selected playlist: {playlist}")

            self.smart_driver.click_step("playlist_done_button", timeout=6)
        except Exception as e:
            logger.warning(f"Could not select playlist '{playlist}': {e}")
            try:
                self.smart_driver.click_step("playlist_done_button", timeout=3)
            except Exception:
                pass

    def _set_kids_restriction(self, driver):
        logger.info("步驟 : 設定兒童限制選項 (非兒童專屬)...")
        elem = self.smart_driver.find_smart_element("kids_restriction_not_for_kids", timeout=10)
        if elem:
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", elem)
            time.sleep(0.5)
            try:
                elem.click()
            except Exception:
                pass
            WebDriverUtil.dispatch_click_events(driver, elem)

    def _navigate_wizard_pages(self, driver):
        logger.info("步驟 : 推進嚮導頁面...")
        for i in range(3):
            logger.info(f"推進嚮導步驟 {i + 1}/3...")
            time.sleep(2)
            self.smart_driver.click_step("next_button", timeout=20)

    def _set_visibility(self, driver, visibility: str):
        vis = "PUBLIC"
        if visibility and visibility.upper() in ["PUBLIC", "UNLISTED", "PRIVATE"]:
            vis = visibility.upper()

        step_id = f"visibility_{vis.lower()}"
        logger.info(f"步驟 : 設定公開性為 {vis} (step_id: {step_id})...")
        self.smart_driver.click_step(step_id, timeout=8)

    def _wait_for_upload_complete(self, driver, timeout: int = 3600):
        logger.info("步驟 : 等待 YouTube 影片上傳完成...")
        start_time = time.time()
        last_logged = 0

        while time.time() - start_time < timeout:
            self.smart_driver.check_and_dismiss_known_popups()

            is_uploading = False
            # Check 1: Check active uploading status inside dialog or bottom progress drawer
            try:
                progress_elements = driver.find_elements(
                    By.XPATH,
                    "//*[contains(@class, 'progress-label') or contains(@class, 'progress-bar') or contains(@class, 'ytcp-video-upload-progress')] | "
                    "//*[contains(text(), '上傳中') or contains(text(), 'Uploading') or contains(text(), '已上傳')]"
                )
                for el in progress_elements:
                    try:
                        if not el.is_displayed():
                            continue
                        text = el.text.strip()
                        if text and any(char.isdigit() for char in text) and "100%" not in text:
                            is_uploading = True
                            now = time.time()
                            if now - last_logged > 15:
                                logger.info(f"YouTube 上傳進度: {text}")
                                last_logged = now
                            break
                    except Exception:
                        continue
            except Exception:
                pass

            if not is_uploading:
                # Check 2: Check explicit completion indicators specifically within active dialog or bottom drawer
                try:
                    complete_elements = driver.find_elements(
                        By.XPATH,
                        "//ytcp-uploads-dialog//*[contains(text(), '上傳完畢') or contains(text(), '上傳完成') or "
                        "contains(text(), 'Upload complete') or contains(text(), '即將開始處理') or "
                        "contains(text(), '處理中') or contains(text(), '檢查完畢') or contains(text(), 'No issues found') or contains(text(), '100%')] | "
                        "//ytcp-video-upload-progress//*[contains(text(), '上傳完畢') or contains(text(), 'Upload complete') or contains(text(), '即將開始處理') or contains(text(), '100%')] | "
                        "//div[contains(@class, 'progress-label') and (contains(text(), '上傳完畢') or contains(text(), 'Upload complete') or contains(text(), '即將開始處理') or contains(text(), '100%'))]"
                    )
                    if any(el.is_displayed() for el in complete_elements):
                        logger.info("檢測到 YouTube 影片上傳完成/進入處理階段！")
                        time.sleep(2)
                        return
                except Exception:
                    pass

                # Check 3: Check if dialog has closed (e.g. redirected to /video/{id}/edit or studio video list)
                try:
                    dialogs = driver.find_elements(By.TAG_NAME, "ytcp-uploads-dialog")
                    if not any(d.is_displayed() for d in dialogs):
                        current_url = driver.current_url.lower()
                        if "/video/" in current_url and "/edit" in current_url:
                            status_elements = driver.find_elements(
                                By.XPATH,
                                "//*[contains(text(), '上傳完畢') or contains(text(), '100%') or contains(text(), '即將開始處理') or contains(text(), '處理中') or contains(text(), '公開')]"
                            )
                            if any(s.is_displayed() for s in status_elements):
                                logger.info("YouTube 處於影片編輯頁面且確認上傳完成！")
                                return
                        elif "videos" in current_url:
                            first_video_status = driver.find_elements(
                                By.XPATH,
                                "//ytcp-video-row[1]//div[contains(@class, 'status')] | "
                                "//ytcp-video-row[1]//*[contains(text(), '處理中') or contains(text(), '即將開始處理') or contains(text(), '公開') or contains(text(), '完整版')]"
                            )
                            if any(s.is_displayed() for s in first_video_status):
                                logger.info("YouTube 稿件列表首部影片狀態確認完成！")
                                return
                except Exception:
                    pass

            time.sleep(3)

        raise RuntimeError("YouTube 影片上傳等待超過超時時間 (3600s)。")

    def _save_edit_page(self, driver):
        logger.info("步驟 : 於 YouTube 編輯頁面儲存並確認公開發布...")
        save_buttons = driver.find_elements(By.XPATH, "//ytcp-button[@id='save'] | //*[@id='save-button']")
        for btn in save_buttons:
            try:
                if btn.is_displayed() and btn.is_enabled() and btn.get_attribute("disabled") is None:
                    logger.info("點擊 YouTube 編輯頁面之儲存按鈕...")
                    WebDriverUtil.dispatch_click_events(driver, btn)
                    time.sleep(3)
                    break
            except Exception:
                pass
        logger.info("YouTube 影片發布/儲存確認完成。")

    def _save_and_close(self, driver):
        logger.info("步驟 : 點擊發布/完成按鈕...")
        self.smart_driver.check_and_dismiss_known_popups()
        self.smart_driver.click_step("done_button", timeout=15)
        logger.info("已點擊 Done/Publish 按鈕。")

        # Check for potential 'Publish anyway' popup
        time.sleep(2)
        self.smart_driver.check_and_dismiss_known_popups()

        # Wait for upload to complete before closing dialog and returning
        self._wait_for_upload_complete(driver)

        # Dismiss final success dialog if present
        self.smart_driver.click_step("close_dialog_button", timeout=15)
        logger.info("YouTube 影片發布流程全部完成！")
