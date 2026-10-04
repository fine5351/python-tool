"""Video RPA 小紅書 (Rednote) 上傳服務模組."""

import logging
import os
import re
import time
from typing import List, Optional

import opencc
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


class rednoteService:
    """Xiaohongshu (rednote) upload service integrated with SmartDriver self-healing."""

    def __init__(self, knowledge_file: Optional[str] = None):
        self.converter = opencc.OpenCC('t2s')
        default_file = get_knowledge_path("rednote")
        self.store = KnowledgeStore(knowledge_file or default_file)
        self.vision = VisionAnalyzer()
        self.smart_driver: Optional[SmartDriver] = None

    def _ensure_smart_driver(self, driver):
        if self.smart_driver is None or self.smart_driver.driver != driver:
            self.smart_driver = SmartDriver(driver, self.store, self.vision)

    def upload_video(self, file_path: str, title: str, description: str,
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
            logger.error(f"Error during rednote upload: {e}", exc_info=True)
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
        simplified_title = self.converter.convert(title) if title else ""
        final_description = self._build_description(title, description, hashtags)
        simplified_description = self.converter.convert(final_description)

        logger.info(f"Simplified Title: {simplified_title}")
        logger.info(f"Simplified Description: {simplified_description}")

        self._navigate_to_creator_studio(driver)
        self._upload_file(driver, file_path)
        self._set_title(driver, simplified_title)
        self._set_description(driver, simplified_description)

    def wait_and_publish(self, driver):
        self._ensure_smart_driver(driver)
        self._wait_for_upload_complete(driver)
        self._wait_for_publish_complete(driver)
        self._click_publish(driver)

    def _build_description(self, title: str, description: str, hashtags: List[str]) -> str:
        desc = ""
        if description:
            desc += f"{description}\n"

        if title:
            for keyword in AutoAppendHashtag.AUTO_HASHTAG_KEYWORDS:
                if keyword in title:
                    desc += f" #{keyword}"

        if hashtags:
            for tag in hashtags:
                hashtag = f" #{tag}"
                if hashtag not in desc:
                    desc += hashtag

        return desc.strip()

    def _navigate_to_creator_studio(self, driver):
        logger.info("步驟 : 前往創作者中心 (https://creator.rednote.com/new/note-manager)...")
        driver.get("https://creator.rednote.com/new/note-manager")
        self.smart_driver.check_and_dismiss_known_popups()

        time.sleep(2)
        current_url = driver.current_url.lower()
        if "login" in current_url or "401" in current_url:
            print("\n" + "=" * 64)
            print("🚨 [登入檢查] 檢測到小紅書尚未登入或憑證已失效！")
            print("瀏覽器已停留在登入頁面，請在開啟的視窗中完成登入（掃碼或驗證碼）。")
            print("系統正即時偵測中，登入成功後將自動無縫接續上傳與發佈流程...")
            print("=" * 64 + "\n")
            logger.warning("檢測到小紅書尚未登入，等待使用者在瀏覽器完成登入中 (最長等待 5 分鐘)...")

            login_start = time.time()
            while time.time() - login_start < 300:
                time.sleep(3)
                current_url = driver.current_url.lower()
                if "login" not in current_url and "401" not in current_url:
                    print("\n✅ 檢測到小紅書登入成功！繼續執行發佈流程...\n")
                    logger.info("✅ 檢測到小紅書登入成功，繼續執行發佈流程。")
                    time.sleep(2)
                    break
            else:
                raise RuntimeError("小紅書登入等待逾時 (5分鐘)，請重新執行。")

        logger.info("步驟 : 進入影片發佈頁面 (https://creator.rednote.com/publish/publish)...")
        driver.get("https://creator.rednote.com/publish/publish")
        self.smart_driver.check_and_dismiss_known_popups()
        time.sleep(2)

    def _upload_file(self, driver, file_path: str):
        logger.info(f"步驟 : 上傳檔案 {file_path}...")
        self.smart_driver.check_and_dismiss_known_popups()
        file_input = self.smart_driver.find_smart_element("file_input", timeout=15)
        if file_input:
            file_input.send_keys(file_path)
            logger.info("檔案路徑已送出。")
        else:
            raise RuntimeError("無法定位小紅書檔案上傳輸入框。")

    def _wait_for_upload_complete(self, driver):
        logger.info("步驟 : 等待影片上傳完成...")
        start_time = time.time()
        timeout = 3600  # Up to 60 minutes

        while time.time() - start_time < timeout:
            is_uploading = False
            try:
                progress_elements = driver.find_elements(By.XPATH, "//*[contains(text(), '%')]")
                for el in progress_elements:
                    try:
                        text = el.text
                        if re.match(r".*\d+%.*", text) and "100%" not in text:
                            is_uploading = True
                            logger.info(f"rednote 上傳進度: {text}")
                            break
                    except Exception:
                        continue
            except Exception:
                pass

            if not is_uploading:
                try:
                    success_elements = driver.find_elements(
                        By.XPATH, "//*[contains(text(), '上传成功') or contains(text(), 'Upload success') or contains(text(), '检测为高清视频') or contains(text(), '视频分辨率较低')]"
                    )
                    if success_elements:
                        logger.info("Upload complete.")
                        return
                except Exception:
                    pass

            time.sleep(2)

        raise RuntimeError("小紅書影片上傳逾時，未能在時限內完成上傳。")

    def _set_title(self, driver, title: str):
        if not title:
            return
        logger.info(f"步驟 : 設定標題: {title}")
        self.smart_driver.input_step("title_input", title, timeout=15)

    def _set_description(self, driver, description: str):
        if not description:
            return
        logger.info("步驟 : 設定說明內容與標籤...")
        try:
            desc_input = self.smart_driver.find_smart_element("description_input", timeout=15)
            if not desc_input:
                logger.warning("未找到說明輸入框，跳過說明設定。")
                return

            desc_input.click()
            parts = description.split(" ")
            for part in parts:
                desc_input.send_keys(part)
                time.sleep(1.5)
                if part.startswith("#"):
                    try:
                        suggestion_selector = "//div[contains(@class, 'item') and .//span[contains(@class, 'name')] and .//span[contains(@class, 'num')]]"
                        all_suggestions = WebDriverWait(driver, 4).until(
                            EC.presence_of_all_elements_located((By.XPATH, suggestion_selector))
                        )
                        suggestions = [item for item in all_suggestions if item.is_displayed()]

                        if suggestions:
                            clean_part = part.replace("#", "").strip().lower()
                            best_match = None
                            exact_match = None
                            max_views = -1

                            for item in suggestions:
                                try:
                                    name = item.find_element(By.CLASS_NAME, "name").text.strip()
                                    num_text = item.find_element(By.CLASS_NAME, "num").text.strip()
                                    views = self._parse_views(num_text)
                                    if name.replace("#", "").strip().lower() == clean_part:
                                        exact_match = item
                                    if views > max_views:
                                        max_views = views
                                        best_match = item
                                except Exception:
                                    pass

                            target = exact_match or best_match or suggestions[0]
                            target.click()
                            logger.info(f"選取標籤建議: {target.text.strip().replace(chr(10), ' ')}")

                        desc_input.send_keys(" ")
                    except Exception as e:
                        logger.debug(f"標籤彈出選單選擇略過: {e}")

            logger.info("Description set.")
        except Exception as e:
            logger.warning(f"Could not set description: {e}")

    def _parse_views(self, num_text: str) -> int:
        if not num_text:
            return 0
        num_text = num_text.replace("人浏览", "").strip()
        multiplier = 1
        if num_text.endswith("亿"):
            multiplier = 100000000
            num_text = num_text.replace("亿", "")
        elif num_text.endswith("万"):
            multiplier = 10000
            num_text = num_text.replace("万", "")
        try:
            return int(float(num_text) * multiplier)
        except ValueError:
            return 0

    def _wait_for_publish_complete(self, driver):
        logger.info("步驟 : 等待發佈前準備完成...")
        for _ in range(30):
            try:
                progress_elements = driver.find_elements(By.XPATH, "//div[contains(text(), '上传中')]")
                if progress_elements:
                    try:
                        if progress_elements[0].is_displayed():
                            logger.info(f"rednote publish progress: {progress_elements[0].text.strip()}")
                            time.sleep(2)
                            continue
                    except Exception:
                        pass
                break
            except Exception:
                break

    def _click_publish(self, driver):
        logger.info("步驟 : 點擊發佈按鈕...")
        self.smart_driver.check_and_dismiss_known_popups()

        publish_elem = self.smart_driver.find_smart_element("publish_button", timeout=20, clickable=True)
        if not publish_elem:
            raise RuntimeError("無法定位小紅書發佈按鈕。")

        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", publish_elem)
        time.sleep(1)

        # Wait up to 60s for submit-disabled to become false/cleared
        logger.info("等待小紅書發佈按鈕啟用 (submit-disabled='false')...")
        for _ in range(60):
            try:
                disabled = driver.execute_script("return arguments[0].getAttribute('submit-disabled');", publish_elem)
                if disabled != "true":
                    logger.info("發佈按鈕已就緒 (啟用狀態)！")
                    break
            except Exception:
                break
            time.sleep(1)

        from selenium.webdriver.common.action_chains import ActionChains
        try:
            if publish_elem.tag_name.lower() == "xhs-publish-btn":
                actions = ActionChains(driver)
                actions.move_to_element(publish_elem).move_by_offset(72, 0).click().perform()
                logger.info("已點擊 xhs-publish-btn 發佈區域 (offset 72, 0)。")
            else:
                publish_elem.click()
                logger.info(f"已點擊發佈按鈕 ({publish_elem.tag_name})。")
        except Exception as click_err:
            logger.warning(f"原生點擊失敗: {click_err}，嘗試 dispatch/JS 點擊...")
            try:
                WebDriverUtil.dispatch_click_events(driver, publish_elem)
            except Exception:
                driver.execute_script("arguments[0].click();", publish_elem)

        logger.info("已送出點擊發佈，等待發佈結果確認...")

        # Wait for publish success indicator or redirect (up to 90s for large files)
        start_time = time.time()
        last_click = time.time()
        while time.time() - start_time < 90:
            self.smart_driver.check_and_dismiss_known_popups()
            current_url = driver.current_url.lower()
            if "note-manager" in current_url:
                logger.info("檢測到頁面已成功跳轉至筆記管理，發佈完成！")
                time.sleep(3)
                return

            success_elem = self.smart_driver.find_smart_element("success_indicator", timeout=3)
            if success_elem and success_elem.is_displayed():
                logger.info(f"檢測到小紅書發佈成功指示標籤: '{success_elem.text.strip()}'！")
                time.sleep(3)
                return

            try:
                body_text = driver.find_element(By.TAG_NAME, "body").text
                if "发布成功" in body_text or "已发布" in body_text:
                    logger.info("頁面文字檢測到發佈成功。")
                    time.sleep(3)
                    return
            except Exception:
                pass

            # Retry click after 8 seconds if still on page and button is enabled
            if time.time() - last_click > 8:
                try:
                    disabled = driver.execute_script("return arguments[0].getAttribute('submit-disabled');", publish_elem)
                    if disabled != "true":
                        actions = ActionChains(driver)
                        actions.move_to_element(publish_elem).move_by_offset(72, 0).click().perform()
                        logger.info("重試點擊 xhs-publish-btn (offset 72, 0)...")
                        last_click = time.time()
                except Exception:
                    pass

            time.sleep(2)

        raise RuntimeError("小紅書發佈未在時間內確認成功，請檢查畫面或草稿箱。")
