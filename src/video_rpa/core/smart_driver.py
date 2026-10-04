"""Video RPA 智慧自癒驅動器 (SmartDriver) - 結合知識庫、四層自癒與軌跡記錄."""

import logging
import time
from typing import Any, Dict, List, Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from video_rpa.core.hitl_handler import HitlHandler
from video_rpa.core.knowledge_store import KnowledgeStore
from video_rpa.core.trail_tracker import OperationTrailTracker
from video_rpa.core.vision_analyzer import VisionAnalyzer
from video_rpa.utils.webdriver_util import WebDriverUtil

logger = logging.getLogger(__name__)


class SmartDriver:
    """Intelligent wrapper over Selenium WebDriver with multi-tiered self-healing,
    screen prompt detection, Vision AI analysis, and Human-in-the-Loop recovery."""

    def __init__(self, driver: WebDriver, knowledge_store: KnowledgeStore,
                 vision_analyzer: Optional[VisionAnalyzer] = None):
        self.driver = driver
        self.store = knowledge_store
        self.vision = vision_analyzer or VisionAnalyzer()
        self.platform = self.store.get_platform()
        self.tracker = OperationTrailTracker.get_instance()

    def check_and_dismiss_known_popups(self) -> bool:
        """Checks for known blocking dialogs and dismisses them if present."""
        popups = self.store.get_known_popups()
        handled_any = False
        for p in popups:
            detect_xpath = p.get("detect_xpath")
            target_xpath = p.get("target_xpath")
            try:
                # Short check without blocking
                elems = self.driver.find_elements(By.XPATH, detect_xpath)
                if elems and any(e.is_displayed() for e in elems):
                    logger.info(f"Known popup detected: {p.get('name')}. Attempting dismiss...")
                    target_btn = WebDriverWait(self.driver, 3).until(
                        EC.element_to_be_clickable((By.XPATH, target_xpath))
                    )
                    WebDriverUtil.dispatch_click_events(self.driver, target_btn)
                    logger.info(f"Dismissed popup: {p.get('name')}")
                    time.sleep(1)
                    handled_any = True
            except Exception:
                pass
        return handled_any

    def find_smart_element(self, step_id: str, fallback_locators: Optional[List[Dict[str, Any]]] = None,
                           clickable: bool = False, timeout: Optional[int] = None,
                           custom_timeout: Optional[int] = None,
                           retry_count: int = 0) -> Optional[WebElement]:
        """Finds an element using tiered self-healing strategies:
        Level 0: Check & dismiss known popups
        Level 1: Try stored locators from KnowledgeStore (ordered by weight)
        Level 2: Multimodal Vision AI prompt & screen analysis (Gemini Vision)
        Level 3: Human-in-the-loop (Inspector click or CLI prompt)
        Level 4: Knowledge persistence
        """
        step_def = self.store.get_step(step_id) or {}
        step_name = step_def.get("name", step_id)
        effective_timeout = timeout or custom_timeout or step_def.get("timeout", 8)
        is_optional = step_def.get("optional", False)

        # Level 0: Dismiss known popups
        self.check_and_dismiss_known_popups()

        # Level 1: Try candidate locators
        locators = self.store.get_locators(step_id)
        if fallback_locators:
            locators.extend(fallback_locators)

        logger.info(f"步驟 [{step_name}]: 正在依權重嘗試 {len(locators)} 個候選選擇器 (超時: {effective_timeout}s)...")
        condition = EC.element_to_be_clickable if clickable else EC.presence_of_element_located

        primary_locator = locators[0].get("value") if locators else None

        start_time = time.time()
        while time.time() - start_time < effective_timeout:
            for idx, loc in enumerate(locators):
                by_str = loc.get("by", "xpath").lower()
                by_type = By.XPATH if by_str == "xpath" else (By.ID if by_str == "id" else By.CSS_SELECTOR)
                val = loc.get("value")

                try:
                    elem = WebDriverWait(self.driver, 1.5).until(condition((by_type, val)))
                    if idx == 0:
                        logger.info(f"✅ 步驟 [{step_name}] 首選選擇器第 1 次命中: {val}")
                        self.store.record_success(step_id, val, is_secondary=False)
                    else:
                        logger.warning(
                            f"⚠️ 步驟 [{step_name}] 首選未命中，命中第 {idx + 1}/{len(locators)} 個選擇器: {val} (原首選: {primary_locator})"
                        )
                        # Record operation trail
                        self.tracker.record_secondary_hit(
                            platform=self.platform,
                            step_id=step_id,
                            step_name=step_name,
                            hit_index=idx + 1,
                            total_candidates=len(locators),
                            original_primary=primary_locator,
                            hit_locator=val,
                            by_type=by_str
                        )
                        # Promote to primary in knowledge store for 1st attempt hit next time
                        self.store.promote_locator_to_primary(step_id, val)

                    return elem
                except Exception:
                    continue
            time.sleep(0.5)

        if is_optional:
            logger.info(f"步驟 [{step_name}] 為可選步驟且未出現，略過。")
            return None

        logger.warning(f"⚠️ 步驟 [{step_name}] 原定選擇器均未匹配，進入自癒與 AI 診斷模式...")

        # Level 2: Multimodal Vision AI Analysis
        ai_diagnosis = None
        if self.vision and self.vision.is_available():
            try:
                screenshot_bytes = self.driver.get_screenshot_as_png()
                ai_diagnosis = self.vision.analyze_screen_state(
                    screenshot_png_bytes=screenshot_bytes,
                    current_step_name=step_name,
                    context_url=self.driver.current_url
                )

                # Check if AI detected a blocker popup
                if ai_diagnosis.get("status") == "POPUP_DETECTED":
                    logger.info(f"🤖 AI 偵測到畫面遮蔽彈窗: {ai_diagnosis.get('description')}")
                    clicked_popup = False
                    resolved_xpath = None

                    # 1. Try suggested_xpath
                    if ai_diagnosis.get("suggested_xpath"):
                        try:
                            s_xpath = ai_diagnosis["suggested_xpath"]
                            btn = WebDriverWait(self.driver, 4).until(
                                EC.element_to_be_clickable((By.XPATH, s_xpath))
                            )
                            WebDriverUtil.dispatch_click_events(self.driver, btn)
                            clicked_popup = True
                            resolved_xpath = s_xpath
                        except Exception as e:
                            logger.warning(f"嘗試點擊 AI 識別之彈窗按鈕失敗: {e}")

                    # 2. Try target_text fallback
                    if not clicked_popup and ai_diagnosis.get("target_text"):
                        target_t = ai_diagnosis["target_text"].strip()
                        text_xpath = f"//*[contains(text(), '{target_t}')]/ancestor::ytcp-button | //*[contains(text(), '{target_t}')]/ancestor::button | //*[contains(text(), '{target_t}')]"
                        try:
                            btn = WebDriverWait(self.driver, 4).until(
                                EC.element_to_be_clickable((By.XPATH, text_xpath))
                            )
                            WebDriverUtil.dispatch_click_events(self.driver, btn)
                            clicked_popup = True
                            resolved_xpath = text_xpath
                            logger.info(f"透過文字標籤 '{target_t}' 成功點擊彈窗按鈕")
                        except Exception as e:
                            logger.warning(f"嘗試依文字標籤點擊彈窗按鈕失敗: {e}")

                    if clicked_popup:
                        logger.info("AI 建議之彈窗關閉按鈕已點擊，重新搜尋目標...")
                        time.sleep(1)
                        # Record AI popup dismissal trail
                        self.tracker.record_ai_action(
                            platform=self.platform,
                            step_id=step_id,
                            step_name=step_name,
                            action_type="AI_POPUP_DISMISS",
                            suggested_xpath=resolved_xpath or "",
                            original_primary=primary_locator,
                            details=f"AI 偵測到畫面遮蔽彈窗並點擊排解: {ai_diagnosis.get('description')}"
                        )
                        # Add to known popups
                        if resolved_xpath:
                            self.store.add_known_popup(
                                name=ai_diagnosis.get("blocker_name") or f"Popup_{int(time.time())}",
                                detect_xpath=resolved_xpath,
                                action="click",
                                target_xpath=resolved_xpath
                            )
                        # Retry finding the original element
                        if retry_count < 5:
                            return self.find_smart_element(step_id, fallback_locators, clickable, timeout=effective_timeout, retry_count=retry_count + 1)

                # Check if AI detected that background processing/upload is ongoing
                if ai_diagnosis.get("status") == "PROCESSING_WAIT":
                    wait_time = int(ai_diagnosis.get("suggested_wait_seconds", 8))
                    logger.info(f"⏳ AI 診斷畫面處於處理等待狀態: {ai_diagnosis.get('description')}，等待 {wait_time} 秒後重試...")
                    time.sleep(wait_time)
                    if retry_count < 60:
                        return self.find_smart_element(step_id, fallback_locators, clickable, timeout=effective_timeout, retry_count=retry_count + 1)

                # Check if AI found the target element with high confidence
                if ai_diagnosis.get("status") == "ELEMENT_FOUND" and ai_diagnosis.get("confidence", 0) >= 0.75:
                    if ai_diagnosis.get("suggested_xpath"):
                        try:
                            s_xpath = ai_diagnosis["suggested_xpath"]
                            elem = WebDriverWait(self.driver, 3).until(condition((By.XPATH, s_xpath)))
                            logger.info(f"🤖 AI 推論選擇器成功定位: {s_xpath}")
                            # Record AI element location trail
                            self.tracker.record_ai_action(
                                platform=self.platform,
                                step_id=step_id,
                                step_name=step_name,
                                action_type="AI_ELEMENT_LOCATE",
                                suggested_xpath=s_xpath,
                                original_primary=primary_locator,
                                details=f"AI 視覺推論定位成功 (置信度: {ai_diagnosis.get('confidence')})"
                            )
                            # Promote learned locator to primary
                            self.store.add_or_update_locator(step_id, "xpath", s_xpath)
                            return elem
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"AI 視覺分析過程發生非致命錯誤: {e}")

        # If step is optional and failed both local & AI, can skip without blocking if user didn't ask
        if is_optional:
            logger.info(f"步驟 [{step_name}] 為選填步驟 (optional)，自動跳過。")
            return None

        # Level 3: Human-In-The-Loop
        resolution = HitlHandler.resolve_stuck_step(
            driver=self.driver,
            step_id=step_id,
            step_name=step_name,
            ai_diagnosis=ai_diagnosis
        )

        if resolution.get("status") == "RESOLVED":
            new_val = resolution.get("value")
            by_type_str = resolution.get("by", "xpath")
            is_new_step = resolution.get("is_new_step", False)

            # Record HITL intervention trail
            self.tracker.record_hitl_action(
                platform=self.platform,
                step_id=step_id,
                step_name=step_name,
                new_xpath=new_val,
                original_primary=primary_locator,
                is_new_step=is_new_step
            )

            if is_new_step:
                new_step_id = f"{step_id}_new_{int(time.time())}"
                new_step_name = resolution.get("new_step_name", new_step_id)
                self.store.add_step(
                    step_id=new_step_id,
                    name=new_step_name,
                    locators=[{"by": by_type_str, "value": new_val, "weight": 20}]
                )
            else:
                self.store.add_or_update_locator(step_id, by_type_str, new_val)

            # Locate element with the newly learned rule
            by_const = By.XPATH if by_type_str == "xpath" else By.CSS_SELECTOR
            try:
                elem = WebDriverWait(self.driver, 5).until(condition((by_const, new_val)))
                return elem
            except Exception as e:
                logger.error(f"使用新規則仍無法定位元素: {e}")
                return None

        elif resolution.get("status") == "SKIPPED":
            logger.info(f"使用者選擇略過步驟 [{step_name}]。")
            return None

        return None

    def click_step(self, step_id: str, fallback_locators: Optional[List[Dict[str, Any]]] = None,
                   timeout: Optional[int] = None, custom_timeout: Optional[int] = None) -> bool:
        """Finds and clicks an element defined by step_id."""
        elem = self.find_smart_element(step_id, fallback_locators=fallback_locators, clickable=True, timeout=timeout or custom_timeout)
        if elem:
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
                WebDriverUtil.dispatch_click_events(self.driver, elem)
                logger.info(f"Dispatched click on step [{step_id}]")
                return True
            except Exception as e:
                logger.warning(f"Dispatch click failed on [{step_id}], trying native click: {e}")
                try:
                    elem.click()
                    return True
                except Exception as e2:
                    logger.error(f"Native click failed on [{step_id}]: {e2}")
                    return False
        return False

    def input_step(self, step_id: str, text: str, fallback_locators: Optional[List[Dict[str, Any]]] = None,
                   timeout: Optional[int] = None, custom_timeout: Optional[int] = None) -> bool:
        """Finds an input box and inputs text."""
        elem = self.find_smart_element(step_id, fallback_locators=fallback_locators, clickable=False, timeout=timeout or custom_timeout)
        if elem:
            try:
                from selenium.webdriver.common.keys import Keys
                elem.send_keys(Keys.CONTROL + "a")
                elem.send_keys(Keys.BACK_SPACE)
                elem.send_keys(text)
                return True
            except Exception as e:
                logger.error(f"Failed to input text for step [{step_id}]: {e}")
                return False
        return False
