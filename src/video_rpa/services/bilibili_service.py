"""Video RPA Bilibili 上傳服務模組."""

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


class BilibiliService:
    """Bilibili video upload service integrated with SmartDriver self-healing."""

    def __init__(self, knowledge_file: Optional[str] = None):
        self.converter = opencc.OpenCC('t2s')
        default_file = get_knowledge_path("bilibili")
        self.store = KnowledgeStore(knowledge_file or default_file)
        self.vision = VisionAnalyzer()
        self.smart_driver: Optional[SmartDriver] = None

    def _ensure_smart_driver(self, driver):
        if self.smart_driver is None or self.smart_driver.driver != driver:
            self.smart_driver = SmartDriver(driver, self.store, self.vision)

    def upload_video(self, file_path: str, title: str, description: str, category: str,
                     hashtags: List[str], keep_open_on_failure: bool) -> bool:
        driver = None
        success = False
        try:
            driver = WebDriverUtil.initialize_driver()
            self._ensure_smart_driver(driver)
            self.start_upload_form(driver, file_path, title, description, category, hashtags)
            self.wait_and_publish(driver)
            success = True
            return True
        except Exception as e:
            logger.error(f"Error during Bilibili upload: {e}", exc_info=True)
            return False
        finally:
            if driver is not None:
                if success or not keep_open_on_failure:
                    driver.quit()
                    logger.info("Browser closed successfully.")
                else:
                    logger.warning("Browser left open for debugging.")

    def start_upload_form(self, driver, file_path: str, title: str, description: str, category: str, hashtags: List[str]):
        self._ensure_smart_driver(driver)
        simplified_title = self.converter.convert(title) if title else ""
        final_description = self._build_description(title, description, hashtags)

        self._navigate_to_upload(driver)
        self._upload_file(driver, file_path)
        self._set_title(driver, simplified_title)
        self._set_description(driver, final_description)
        self._select_category(driver, category)
        self._set_tags(driver, hashtags)
        self._set_creation_declaration(driver)

    def wait_and_publish(self, driver):
        self._ensure_smart_driver(driver)
        self._wait_for_upload_complete(driver)
        self._set_creation_declaration(driver)
        self._select_cover(driver)
        self._click_submit(driver)
        self._wait_for_success(driver)

    def _build_description(self, title: str, description: str, hashtags: List[str]) -> str:
        desc = ""
        if description:
            desc += f"{description}\n"

        if title:
            for keyword in AutoAppendHashtag.AUTO_HASHTAG_KEYWORDS:
                if keyword in title:
                    desc += f" #{keyword}"
                    if hashtags is not None and keyword not in hashtags:
                        hashtags.append(keyword)

        if hashtags:
            for tag in hashtags:
                hashtag = f" #{tag}"
                if hashtag not in desc:
                    desc += hashtag

        return self.converter.convert(desc.strip())

    def _navigate_to_upload(self, driver):
        logger.info("步驟 : 前往上傳頁面 (https://member.bilibili.com/platform/upload/video/frame)...")
        driver.get("https://member.bilibili.com/platform/upload/video/frame")
        self.smart_driver.check_and_dismiss_known_popups()

        time.sleep(2)
        # Dismiss any leftover local drafts prompt to guarantee clean single video upload
        try:
            cancel_btns = driver.find_elements(By.XPATH, "//*[contains(text(), '不用了') or contains(text(), '放弃') or contains(text(), '放棄')]")
            for btn in cancel_btns:
                if btn.is_displayed():
                    btn.click()
                    logger.info("已關閉舊有的本地草稿提示，維持乾淨上傳狀態。")
                    time.sleep(1)
                    break
        except Exception:
            pass

        current_url = driver.current_url.lower()
        if "passport.bilibili.com" in current_url or "login" in current_url:
            print("\n" + "=" * 64)
            print("🚨 [登入檢查] 檢測到 Bilibili 尚未登入或憑證已失效！")
            print("瀏覽器已停留在登入頁面，請在開啟的視窗中完成登入（掃碼或帳密）。")
            print("系統正即時偵測中，登入成功後將自動無縫接續上傳流程...")
            print("=" * 64 + "\n")
            logger.warning("檢測到 Bilibili 尚未登入，等待使用者在瀏覽器完成登入中 (最長等待 5 分鐘)...")

            login_start = time.time()
            while time.time() - login_start < 300:
                time.sleep(3)
                current_url = driver.current_url.lower()
                if "passport.bilibili.com" not in current_url and "login" not in current_url:
                    print("\n✅ 檢測到 Bilibili 登入成功！繼續執行上傳流程...\n")
                    logger.info("✅ 檢測到 Bilibili 登入成功，繼續執行上傳流程。")
                    driver.get("https://member.bilibili.com/platform/upload/video/frame")
                    time.sleep(3)
                    break
            else:
                raise RuntimeError("Bilibili 登入等待逾時 (5分鐘)，請重新執行。")

    def _upload_file(self, driver, file_path: str):
        logger.info(f"步驟 : 上傳檔案 {file_path}...")
        self.smart_driver.check_and_dismiss_known_popups()

        time.sleep(4)  # Wait for page JS to stabilize
        upload_success = False

        for attempt in range(1, 4):
            logger.info(f"嘗試發送檔案 (第 {attempt} 次)...")
            inputs = driver.find_elements(By.XPATH, "//input[@type='file']")
            if not inputs:
                self.smart_driver.click_step("upload_area", timeout=5)
                time.sleep(1)
                inputs = driver.find_elements(By.XPATH, "//input[@type='file']")

            if inputs:
                try:
                    inputs[0].send_keys(file_path)
                    logger.info("檔案路徑已送出，等待確認上傳進度...")
                except Exception as e:
                    logger.warning(f"send_keys 失敗: {e}")

            # Check for upload progress, complete label, or form appearance
            for _ in range(10):
                time.sleep(1)
                progress_elements = [p for p in driver.find_elements(By.CLASS_NAME, "progress-text") if p.is_displayed()]
                complete_elements = [c for c in driver.find_elements(By.XPATH, "//span[contains(@class, 'success') and contains(text(), '上传完成')]") if c.is_displayed()]
                title_inputs = [t for t in driver.find_elements(By.XPATH, "//input[contains(@placeholder, '标题') or contains(@placeholder, 'Title')]") if t.is_displayed()]
                if progress_elements or complete_elements or title_inputs:
                    logger.info("檢測到上傳進度或編輯表單已生成，上傳成功啟動。")
                    upload_success = True
                    break

            if upload_success:
                break
            logger.warning(f"第 {attempt} 次嘗試未啟動上傳，重新嘗試...")
            time.sleep(2)

        if not upload_success:
            raise RuntimeError("無法成功啟動 Bilibili 檔案上傳。")

    def _wait_for_upload_complete(self, driver):
        logger.info("步驟 : 等待影片上傳完成...")
        start_time = time.time()
        timeout = 3600  # Up to 60 minutes for large video upload

        while time.time() - start_time < timeout:
            try:
                # Check for visible upload completion
                for elem in driver.find_elements(
                    By.XPATH, "//span[contains(@class, 'success') and contains(text(), '上传完成')] | //span[contains(@class, 'text') and contains(text(), '上传完成')]"
                ):
                    try:
                        if elem.is_displayed():
                            logger.info(f"Bilibili 影片上傳完成 ({elem.text.strip()})")
                            return
                    except Exception:
                        continue

                # Check visible progress text
                for el in driver.find_elements(By.XPATH, "//span[contains(@class, 'progress-text')]"):
                    try:
                        if el.is_displayed():
                            text = el.text.strip()
                            if text:
                                logger.info(f"Bilibili 上傳進度: {text}")
                                if "100%" in text:
                                    time.sleep(2)
                                    return
                                break
                    except Exception:
                        continue
            except Exception:
                pass

            time.sleep(2)

        raise RuntimeError("Bilibili 影片上傳逾時，未能在時限內完成上傳。")

    def _set_title(self, driver, title: str):
        if not title:
            return
        logger.info(f"步驟 : 設定標題: {title}")
        title_elem = self.smart_driver.find_smart_element("title_input", timeout=15)
        if title_elem:
            try:
                title_elem.click()
                driver.execute_script("arguments[0].value = '';", title_elem)
                title_elem.send_keys(Keys.CONTROL + "a")
                title_elem.send_keys(Keys.BACK_SPACE)
                title_elem.send_keys(title)
                driver.execute_script(
                    "arguments[0].dispatchEvent(new Event('input', { bubbles: true })); "
                    "arguments[0].dispatchEvent(new Event('change', { bubbles: true }));",
                    title_elem
                )
                time.sleep(0.5)
                logger.info(f"標題已更新為: '{title_elem.get_attribute('value')}'")
            except Exception as e:
                logger.warning(f"輸入標題發生錯誤: {e}")

    def _set_description(self, driver, description: str):
        if not description:
            return
        logger.info(f"步驟 : 設定說明內容: {description}")
        try:
            desc_input = self.smart_driver.find_smart_element("description_input", timeout=10)
            if desc_input:
                desc_input.click()
                time.sleep(0.5)
                desc_input.send_keys(Keys.CONTROL + "a")
                desc_input.send_keys(Keys.BACK_SPACE)
                time.sleep(0.5)
                for line in description.split("\n"):
                    desc_input.send_keys(line)
                    desc_input.send_keys(Keys.ENTER)
                time.sleep(0.5)
                logger.info("Description set.")
        except Exception as e:
            logger.warning(f"設定說明內容失敗: {e}")

    def _select_category(self, driver, category: str):
        if not category:
            category = "游戏"
        target_category = self.converter.convert(category)
        logger.info(f"步驟 : 選擇分區: {target_category}...")
        try:
            self.smart_driver.click_step("category_dropdown", timeout=10)
            time.sleep(1)

            option_selector = (
                f"//div[contains(@class, 'drop-list-v2-item') and @title='{target_category}'] | "
                f"//div[contains(@class, 'drop-list-v2-item')]//p[contains(@class, 'item-cont-main') and contains(text(), '{target_category}')] | "
                f"//*[text()='{target_category}']"
            )
            opt = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, option_selector)))
            opt.click()
            logger.info(f"Category '{target_category}' selected.")
        except Exception as e:
            logger.warning(f"Could not select category: {e}")

    def _set_tags(self, driver, hashtags: List[str]):
        if not hashtags:
            return
        logger.info("步驟 : 設定標籤...")
        try:
            tag_input = self.smart_driver.find_smart_element("tag_input", timeout=10)
            if tag_input:
                for tag in hashtags:
                    simplified_tag = self.converter.convert(tag)
                    tag_input.send_keys(simplified_tag)
                    logger.info(f"標籤輸入: {simplified_tag}")
                    tag_input.send_keys(Keys.ENTER)
                    time.sleep(0.5)
                logger.info("Tags set.")
        except Exception as e:
            logger.warning(f"Could not set tags: {e}")

    def _wait_for_upload_complete(self, driver, timeout: int = 3600):
        logger.info("步驟 : 等待 Bilibili 影片上傳完成...")
        start_time = time.time()
        last_logged = 0

        while time.time() - start_time < timeout:
            self.smart_driver.check_and_dismiss_known_popups()

            # Check 1: Check active uploading status
            uploading_elements = driver.find_elements(
                By.XPATH,
                "//*[contains(text(), '上传中') or contains(text(), '已经上传') or contains(text(), '当前速度')]"
            )
            is_uploading = False
            for el in uploading_elements:
                try:
                    if el.is_displayed():
                        text = el.text.strip()
                        if text:
                            is_uploading = True
                            now = time.time()
                            if now - last_logged > 15:
                                logger.info(f"Bilibili 上傳進度: {text}")
                                last_logged = now
                            break
                except Exception:
                    continue

            if not is_uploading:
                # Check 2: Check explicit completion indicators or submit button active
                complete_elements = driver.find_elements(
                    By.XPATH,
                    "//*[contains(text(), '上传完成') or contains(text(), '转码中') or contains(text(), '重新上传') or contains(text(), '重新上傳')]"
                )
                if any(el.is_displayed() for el in complete_elements):
                    logger.info("檢測到 Bilibili 影片上傳完成/進入轉碼階段！")
                    time.sleep(2)
                    return

                # Check 3: Check if submit button is present and not disabled
                submit_buttons = driver.find_elements(By.XPATH, "//*[contains(@class, 'submit-add') and contains(text(), '立即投稿')]")
                for btn in submit_buttons:
                    try:
                        if btn.is_displayed():
                            btn_class = btn.get_attribute("class") or ""
                            disabled = btn.get_attribute("disabled")
                            if "disabled" not in btn_class and not disabled:
                                logger.info("檢測到 Bilibili 立即投稿按鈕已啟用，影片上傳判定完成！")
                                time.sleep(2)
                                return
                    except Exception:
                        pass

            time.sleep(3)

        raise RuntimeError("Bilibili 影片上傳等待超過超時時間 (3600s)。")

    def _click_submit(self, driver):
        logger.info("步驟 : 點擊立即投稿按鈕...")
        self.smart_driver.check_and_dismiss_known_popups()
        for attempt in range(1, 15):
            submit_btn = self.smart_driver.find_smart_element("submit_button", timeout=10)
            if submit_btn:
                btn_class = submit_btn.get_attribute("class") or ""
                disabled = submit_btn.get_attribute("disabled")
                if "disabled" in btn_class or disabled:
                    logger.info(f"投稿按鈕尚未啟用 (disabled)，等待中... ({attempt}/14)")
                    time.sleep(2)
                    continue
                try:
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", submit_btn)
                    time.sleep(1)
                    # Trigger native click, event dispatch, and JS click
                    try:
                        submit_btn.click()
                    except Exception:
                        pass
                    try:
                        WebDriverUtil.dispatch_click_events(driver, submit_btn)
                    except Exception:
                        pass
                    driver.execute_script("arguments[0].click();", submit_btn)
                    logger.info("已點擊立即投稿按鈕。")
                    return
                except Exception as e:
                    logger.warning(f"點擊投稿按鈕失敗: {e}")
            time.sleep(1)
        raise RuntimeError("無法點擊 Bilibili 立即投稿按鈕 (按鈕可能持續處於禁用狀態)。")

    def _set_creation_declaration(self, driver):
        logger.info("步驟 : 設定創作聲明...")
        try:
            if self.smart_driver.click_step("creation_declaration", timeout=8):
                time.sleep(1)
                self.smart_driver.click_step("creation_declaration_option", timeout=6)
                logger.info("已選擇 '内容无需标注'。")
        except Exception as e:
            logger.warning(f"設定創作聲明失敗: {e}")

    def _wait_for_success(self, driver):
        logger.info("步驟 : 等待發佈成功狀態或頁面跳轉...")
        start_time = time.time()
        timeout = 90  # 90 seconds timeout
        last_click = time.time()

        while time.time() - start_time < timeout:
            # Check 1: URL redirected to manager or result page
            current_url = driver.current_url.lower()
            if "upload-manager" in current_url or "result" in current_url or "success" in current_url:
                logger.info(f"檢測到成功轉跳網址: {current_url}，投稿確認成功！")
                time.sleep(3)
                return

            # Check 2: Success text indicator on screen (must be displayed)
            success_elems = driver.find_elements(
                By.XPATH,
                "//*[contains(text(), '稿件投递成功') or contains(text(), '查看稿件') or contains(text(), '投稿成功') or contains(text(), '再投一个')]"
            )
            for elem in success_elems:
                try:
                    if elem.is_displayed():
                        logger.info(f"檢測到投稿成功訊息元件: '{elem.text.strip()}'，投稿確認成功！")
                        time.sleep(3)
                        return
                except Exception:
                    continue

            # Check 3: Known popups
            self.smart_driver.check_and_dismiss_known_popups()

            # Retry click submit if still on upload frame after 15s
            if time.time() - last_click > 15:
                try:
                    submit_buttons = driver.find_elements(By.XPATH, "//*[contains(@class, 'submit-add') and contains(text(), '立即投稿')]")
                    for b in submit_buttons:
                        if b.is_displayed():
                            logger.info("投稿按鈕仍在畫面中，嘗試再次點擊...")
                            try:
                                b.click()
                            except Exception:
                                pass
                            WebDriverUtil.dispatch_click_events(driver, b)
                            last_click = time.time()
                            break
                except Exception:
                    pass

            time.sleep(2)

        logger.error(f"Bilibili 投稿確認逾時。當前網址: {driver.current_url}")
        try:
            body_snippet = driver.find_element(By.TAG_NAME, "body").text[:500]
            logger.error(f"頁面文字摘錄: {body_snippet}")
        except Exception:
            pass

        raise RuntimeError("Bilibili 稿件未能成功發佈或投稿確認逾時，請確認稿件管理後台。")

    def _select_cover(self, driver):
        logger.info("步驟 : 選擇影片推薦封面...")
        try:
            # Check if a cover is already selected
            selected_covers = driver.find_elements(By.CSS_SELECTOR, ".img-item-box.img-item-cover-selected")
            if any(c.is_displayed() for c in selected_covers):
                logger.info("系統已自動選取推薦封面，無需重複點選。")
                return

            cover_selector = (By.CSS_SELECTOR, ".img-item-box.img-item-cover")
            cover_items = []
            for _ in range(6):
                cover_items = [c for c in driver.find_elements(*cover_selector) if c.is_displayed()]
                if cover_items:
                    break
                time.sleep(1)

            if cover_items:
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", cover_items[0])
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", cover_items[0])
                logger.info("已成功選擇推薦封面。")
            else:
                logger.warning("未找到推薦封面項目，跳過封面選擇。")
        except Exception as e:
            logger.warning(f"選擇封面失敗: {e}")
