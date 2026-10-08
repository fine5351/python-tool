import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import unittest
from unittest.mock import MagicMock, patch
from PIL import Image

from PyQt6.QtWidgets import QApplication

from game_assistant.core.config import (
    GameType, AssistCapability, AnalysisMode, PROMPTS,
    HOTKEY_VOICE_TRANSLATE, HOTKEY_TRANSLATE_SCREEN, DEFAULT_TARGET_LANGUAGE
)
from game_assistant.engines.ai_engine import GeminiAuxiliaryEngine
from game_assistant.utils.input_actuator import ScreenActuator
from game_assistant.core.agent import UniversalGameAgent
from game_assistant.ui.gui import FloatingSubtitleOverlay, GameAssistantOverlay, HotkeyListener
from game_assistant.app import (
    GameAssistantController, ScreenTranslationWorker, VoiceTranslationWorker
)
from game_assistant.audio.stt_engine import STTEngine


class TestTranslationConfig(unittest.TestCase):
    """測試翻譯模組之常數、列舉與 Prompt 範本配置"""

    def test_assist_capability_translation_enum(self):
        self.assertTrue(hasattr(AssistCapability, "TRANSLATION"))
        self.assertEqual(AssistCapability.TRANSLATION.value, "語文翻譯 (Translation & Subtitles)")

    def test_analysis_mode_translation_enum(self):
        self.assertTrue(hasattr(AnalysisMode, "TRANSLATION"))
        self.assertEqual(AnalysisMode.TRANSLATION.value, "外文畫面與對話翻譯 (Translation)")

    def test_hotkey_configuration(self):
        self.assertEqual(HOTKEY_VOICE_TRANSLATE, "f6", "語音翻譯熱鍵必須為 F6")
        self.assertEqual(HOTKEY_TRANSLATE_SCREEN, "f7", "畫面翻譯熱鍵必須為 F7")
        self.assertEqual(DEFAULT_TARGET_LANGUAGE, "英文")

    def test_prompts_have_translation_mode(self):
        for game in (GameType.GENSHIN, GameType.STAR_RAIL, GameType.ZZZ, GameType.GENERAL):
            self.assertIn(AnalysisMode.TRANSLATION, PROMPTS[game], f"{game} 缺少 TRANSLATION 提示詞範本")
            prompt_text = PROMPTS[game][AnalysisMode.TRANSLATION]
            self.assertIn("繁體中文", prompt_text)
            self.assertIn("介面", prompt_text)


class TestGeminiAuxiliaryEngineTranslation(unittest.TestCase):
    """測試 Gemini 輔助引擎之多模態畫面翻譯與語音雙向翻譯方法"""

    def setUp(self):
        self.engine = GeminiAuxiliaryEngine(api_key="")
        self.dummy_img = Image.new("RGB", (320, 240), color="purple")

    def test_offline_screen_translation(self):
        report = self.engine.translate_screen(self.dummy_img, game_type=GameType.GENSHIN)
        self.assertIn("遊戲畫面外文翻譯", report)
        self.assertIn("介面與選單對照", report)
        self.assertIn("Settings", report)
        self.assertIn("系統設定", report)

    def test_offline_chat_subtitles(self):
        report, subtitles = self.engine.translate_chat_subtitles(self.dummy_img)
        self.assertIn("遊戲字幕與對話即時翻譯", report)
        self.assertIsInstance(subtitles, list)
        self.assertGreater(len(subtitles), 0)
        first = subtitles[0]
        self.assertIn("sender", first)
        self.assertIn("original", first)
        self.assertIn("translated", first)

    def test_offline_voice_translation_gaming_vocab(self):
        # 測試常用遊戲短語本地對照
        self.assertEqual(self.engine.translate_voice_text("救我", "英文"), "Help me!")
        self.assertEqual(self.engine.translate_voice_text("大家集合", "英文"), "Group up here!")
        self.assertEqual(self.engine.translate_voice_text("快打boss", "英文"), "Let's attack the boss!")
        self.assertEqual(self.engine.translate_voice_text("注意閃避", "英文"), "Watch out! Dodge!")
        self.assertEqual(self.engine.translate_voice_text("謝謝各位", "英文"), "Thanks! / GG!")

    def test_offline_voice_translation_empty_input(self):
        self.assertEqual(self.engine.translate_voice_text(""), "")
        self.assertEqual(self.engine.translate_voice_text("   "), "")

    def test_offline_voice_translation_fallback_formatting(self):
        # 測試未收錄短語之語言標記輸出
        res_ja = self.engine.translate_voice_text("這把武器如何", "日文")
        self.assertIn("這把武器如何", res_ja)
        res_ko = self.engine.translate_voice_text("這把武器如何", "韓文")
        self.assertIn("這把武器如何", res_ko)

    def test_mock_client_screen_translation(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "### 🌐 測試畫面翻譯\n- Attack -> 攻擊"
        mock_client.models.generate_content.return_value = mock_resp

        self.engine.client = mock_client
        res = self.engine.translate_screen(self.dummy_img, GameType.GENERAL)
        self.assertEqual(res, "### 🌐 測試畫面翻譯\n- Attack -> 攻擊")

    def test_mock_client_chat_subtitles_json_extraction(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = (
            "### 💬 字幕翻譯\n\n"
            "```json\n"
            '[\n'
            '  {"sender": "NPC", "original": "Hold the line!", "translated": "堅守陣線！"}\n'
            ']\n'
            "```"
        )
        mock_client.models.generate_content.return_value = mock_resp

        self.engine.client = mock_client
        text, subs = self.engine.translate_chat_subtitles(self.dummy_img)
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["sender"], "NPC")
        self.assertEqual(subs[0]["original"], "Hold the line!")
        self.assertEqual(subs[0]["translated"], "堅守陣線！")

    def test_mock_client_voice_translation(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = '  "Need assistance on the left flank!"  '
        mock_client.models.generate_content.return_value = mock_resp

        self.engine.client = mock_client
        res = self.engine.translate_voice_text("左翼請求支援", "英文")
        self.assertEqual(res, "Need assistance on the left flank!")
        self.assertTrue(mock_client.models.generate_content.called)
    def test_offline_voice_translation_multilingual(self):
        # 測試日文、韓文、俄文快速溝通術語降級
        self.assertEqual(self.engine.translate_voice_text("救我", "日文"), "助けて！")
        self.assertEqual(self.engine.translate_voice_text("撤退", "日文"), "撤退！")
        self.assertEqual(self.engine.translate_voice_text("救我", "韓文"), "살려주세요!")
        self.assertEqual(self.engine.translate_voice_text("謝謝", "韓文"), "감사합니다! GG!")
        self.assertEqual(self.engine.translate_voice_text("救我", "俄文"), "Помогите!")
        self.assertEqual(self.engine.translate_voice_text("謝謝", "俄文"), "Спасибо! GG!")

    def test_extract_subtitles_from_json_edge_cases(self):
        # 1. 無 json 語言標註之代碼區塊
        t_no_tag = "```\n[{\"sender\": \"隊友\", \"original\": \"Help!\", \"translated\": \"救命！\"}]\n```"
        subs = self.engine._extract_subtitles_from_json(t_no_tag)
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["sender"], "隊友")

        # 2. 原始未用代碼區塊包裹之 JSON 陣列
        t_raw_arr = "以下是字幕：\n[{\"sender\": \"NPC\", \"original\": \"Welcome\", \"translated\": \"歡迎\"}]"
        subs_raw = self.engine._extract_subtitles_from_json(t_raw_arr)
        self.assertEqual(len(subs_raw), 1)
        self.assertEqual(subs_raw[0]["original"], "Welcome")

        # 3. 字典包裹格式 {"subtitles": [...]}
        t_dict = "```json\n{\"subtitles\": [{\"sender\": \"Boss\", \"original\": \"Rage!\", \"translated\": \"狂暴！\"}]}\n```"
        subs_dict = self.engine._extract_subtitles_from_json(t_dict)
        self.assertEqual(len(subs_dict), 1)
        self.assertEqual(subs_dict[0]["translated"], "狂暴！")

        # 4. Markdown 對話清單正則解析 (驗證前綴正確剝離，非粗暴歸為「對話」)
        t_md = "- **System / NPC**：`Warning!` ➔ **【警告！】**"
        subs_md = self.engine._extract_subtitles_from_json(t_md)
        self.assertEqual(len(subs_md), 1)
        self.assertEqual(subs_md[0]["sender"], "System / NPC")
        self.assertEqual(subs_md[0]["original"], "Warning!")
        self.assertEqual(subs_md[0]["translated"], "警告！")


class TestScreenActuatorChatPaste(unittest.TestCase):
    """測試致動器之剪貼簿複製與遊戲文字聊天框模擬輸入"""

    def setUp(self):
        self.actuator = ScreenActuator(action_cooldown=0.01)

    def test_copy_to_clipboard(self):
        res = self.actuator.copy_to_clipboard("Test Clipboard 繁中文字")
        self.assertTrue(res)

    def test_copy_to_clipboard_win32_ctypes_fallback(self):
        # 模擬 pyperclip 模組遺失或異常時，Win32 64-bit ctypes 降級是否正常運作
        with patch.dict("sys.modules", {"pyperclip": None}):
            res = self.actuator.copy_to_clipboard("Win32 Ctypes 剪貼簿測試")
            self.assertTrue(res, "Win32 ctypes 剪貼簿降級必須成功")

    def test_paste_text_to_chat_custom_enter_key(self):
        # 測試支援自訂開啟聊天鍵 (如 '/' 鍵或 None)
        res_slash = self.actuator.paste_text_to_chat("Team message", enter_chat_key="/", submit=False)
        self.assertTrue(res_slash)
        res_none = self.actuator.paste_text_to_chat("Direct paste", enter_chat_key=None, submit=True)
        self.assertTrue(res_none)

    def test_paste_text_to_chat_invalid_key_graceful(self):
        # 傳入未知按鍵不應崩潰抛出例外
        res = self.actuator.paste_text_to_chat("Safe paste", enter_chat_key="invalid_unknown_key_xyz")
        self.assertTrue(res)

    def test_paste_text_to_chat_empty(self):
        self.assertFalse(self.actuator.paste_text_to_chat(""))
        self.assertFalse(self.actuator.paste_text_to_chat("   "))

    def test_paste_text_to_chat_execution(self):
        # 測試 paste_text_to_chat 在啟用狀態或 force=True 下皆能成功模擬
        res = self.actuator.paste_text_to_chat("Need help!", enter_chat_key="enter", submit=True, force=True)
        self.assertTrue(res)

        history = self.actuator.get_recent_history()
        self.assertGreater(len(history), 0)
        last_item = history[-1]
        self.assertEqual(last_item["type"], "CHAT_PASTE")
        self.assertEqual(last_item["details"]["text"], "Need help!")
        self.assertTrue(last_item["details"]["submit"])

    def test_paste_text_to_chat_disabled_without_force(self):
        self.actuator.disable()
        res = self.actuator.paste_text_to_chat("Hello", force=False)
        self.assertFalse(res)

    def test_type_text(self):
        res = self.actuator.type_text("Hello World", auto_enter=False)
        self.assertTrue(res)
        history = self.actuator.get_recent_history()
        self.assertEqual(history[-1]["type"], "TYPE_TEXT")


class TestUniversalGameAgentTranslation(unittest.TestCase):
    """測試 UniversalGameAgent 整合翻譯協調能力"""

    def setUp(self):
        self.agent = UniversalGameAgent(
            game_type=GameType.GENSHIN,
            capability=AssistCapability.TRANSLATION
        )
        self.dummy_img = Image.new("RGB", (320, 240), color="black")

    def test_set_capability_translation(self):
        self.assertEqual(self.agent.capability, AssistCapability.TRANSLATION)

    def test_translate_screen(self):
        report_md, subtitles = self.agent.translate_screen(self.dummy_img, target_lang="繁體中文")
        self.assertIsInstance(report_md, str)
        self.assertIn("外文翻譯", report_md)
        self.assertIsInstance(subtitles, list)

    def test_translate_voice_to_chat(self):
        foreign_text, was_typed = self.agent.translate_voice_to_chat(
            chinese_voice_text="救我",
            target_lang="英文",
            auto_submit=True
        )
        self.assertEqual(foreign_text, "Help me!")
        self.assertTrue(was_typed)

    def test_translate_voice_to_chat_empty(self):
        foreign_text, was_typed = self.agent.translate_voice_to_chat("")
        self.assertEqual(foreign_text, "")
        self.assertFalse(was_typed)

    def test_translate_voice_to_chat_custom_key(self):
        foreign_text, was_typed = self.agent.translate_voice_to_chat(
            chinese_voice_text="快跑",
            target_lang="英文",
            auto_submit=False,
            enter_chat_key="/"
        )
        self.assertEqual(foreign_text, "Run! / Retreat!")
        self.assertTrue(was_typed)

    def test_step_in_translation_mode(self):
        decision = self.agent.step(image=self.dummy_img)
        self.assertIsNotNone(decision)
        self.assertIsNotNone(decision.guidance_text)


class TestTranslationUIComponents(unittest.TestCase):
    """測試置頂浮動字幕視窗與主 Overlay 介面之翻譯功能"""

    @classmethod
    def setUpClass(cls):
        # 確保 QApplication 實例存在
        cls.app = QApplication.instance() or QApplication([])

    def test_floating_subtitle_overlay_creation_and_show(self):
        subtitle_overlay = FloatingSubtitleOverlay()
        self.assertIsNotNone(subtitle_overlay)

        # 驗證防焦點奪取旗標與不啟用視窗屬性已配置 (確保遊戲操作不被中斷)
        from PyQt6.QtCore import Qt
        flags = subtitle_overlay.windowFlags()
        self.assertTrue(flags & Qt.WindowType.WindowDoesNotAcceptFocus)

        subtitle_overlay.show_subtitle(
            translated="【NPC】前方有高能反應！",
            original="Warning! High energy signature ahead.",
            duration_ms=2000
        )
        self.assertEqual(subtitle_overlay.lbl_translated.text(), "【NPC】前方有高能反應！")
        self.assertIn("Warning", subtitle_overlay.lbl_original.text())

        # 清除字幕
        subtitle_overlay.clear_subtitle()
        self.assertEqual(subtitle_overlay.lbl_translated.text(), "")
        subtitle_overlay.close()

    def test_floating_subtitle_show_subtitles_list(self):
        subtitle_overlay = FloatingSubtitleOverlay()
        sub_list = [
            {"sender": "NPC", "original": "Look out!", "translated": "小心！"},
            {"sender": "隊友", "original": "Got your back.", "translated": "掩護你。"}
        ]
        subtitle_overlay.show_subtitles_list(sub_list, duration_ms=2000)
        trans_text = subtitle_overlay.lbl_translated.text()
        self.assertIn("【NPC】小心！", trans_text)
        self.assertIn("【隊友】掩護你。", trans_text)
        subtitle_overlay.close()

    def test_game_assistant_overlay_translation_elements(self):
        overlay = GameAssistantOverlay()
        self.assertIsNotNone(overlay.btn_screen_translate)
        self.assertIsNotNone(overlay.btn_voice_translate)
        self.assertIsNotNone(overlay.combo_target_lang)

        # 驗證目標語言切換
        self.assertEqual(overlay.get_target_language(), "英文")
        overlay.combo_target_lang.setCurrentIndex(1)
        self.assertEqual(overlay.get_target_language(), "日文")

        # 驗證展示翻譯畫面
        test_md = "### 🌐 畫面翻譯結果\n\n- Start Game ➔ 開始遊戲"
        overlay.show_translation_view(test_md, capture_ms=15.0)
        self.assertEqual(overlay._active_display_mode, "translation")
        self.assertIn("開始遊戲", overlay.output_browser.toPlainText())

        # 驗證按鈕狀態管理
        overlay.set_status_voice_translating()
        self.assertFalse(overlay.btn_voice_translate.isEnabled())
        overlay.reset_voice_translate_button()
        self.assertTrue(overlay.btn_voice_translate.isEnabled())

        overlay.close()

    def test_hotkey_listener_translation_signals(self):
        listener = HotkeyListener()
        self.assertTrue(hasattr(listener, "screen_translate_signal"))
        self.assertTrue(hasattr(listener, "voice_translate_signal"))


class TestTranslationWorkers(unittest.TestCase):
    """測試非同步翻譯執行緒 Workers"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.agent = UniversalGameAgent()
        self.stt_engine = STTEngine()

    def test_screen_translation_worker_run(self):
        worker = ScreenTranslationWorker(self.agent)
        self.assertFalse(worker.is_busy())

        result_box = []
        worker.translation_finished.connect(lambda md, subs, ms: result_box.append((md, subs, ms)))

        # 直接在當前執行緒執行 run() 進行同步驗證
        worker.run()
        self.assertEqual(len(result_box), 1)
        md, subs, elapsed_ms = result_box[0]
        self.assertIn("外文翻譯", md)
        self.assertIsInstance(subs, list)

    def test_voice_translation_worker_run_success(self):
        mock_stt = MagicMock()
        mock_stt.listen_and_recognize.return_value = (True, "救我")

        worker = VoiceTranslationWorker(self.agent, mock_stt)
        finished_box = []
        worker.voice_trans_finished.connect(lambda zh, fr, typed: finished_box.append((zh, fr, typed)))

        worker.run()
        self.assertEqual(len(finished_box), 1)
        zh, fr, typed = finished_box[0]
        self.assertEqual(zh, "救我")
        self.assertEqual(fr, "Help me!")
        self.assertTrue(typed)

    def test_voice_translation_worker_run_stt_failure(self):
        mock_stt = MagicMock()
        mock_stt.listen_and_recognize.return_value = (False, "未辨識到語音")

        worker = VoiceTranslationWorker(self.agent, mock_stt)
        error_box = []
        worker.voice_trans_error.connect(lambda err: error_box.append(err))

        worker.run()
        self.assertEqual(len(error_box), 1)
        self.assertIn("未辨識到語音", error_box[0])

    def test_voice_translation_worker_custom_key(self):
        mock_stt = MagicMock()
        mock_stt.listen_and_recognize.return_value = (True, "集合")

        worker = VoiceTranslationWorker(self.agent, mock_stt)
        worker.target_lang = "英文"
        worker.auto_submit = False
        worker.enter_chat_key = "/"

        finished_box = []
        worker.voice_trans_finished.connect(lambda zh, fr, typed: finished_box.append((zh, fr, typed)))
        worker.run()

        self.assertEqual(len(finished_box), 1)
        zh, fr, typed = finished_box[0]
        self.assertEqual(zh, "集合")
        self.assertEqual(fr, "Group up here!")
        self.assertTrue(typed)
        self.assertEqual(worker.enter_chat_key, "/")
        self.assertFalse(worker.auto_submit)


if __name__ == "__main__":
    unittest.main()
