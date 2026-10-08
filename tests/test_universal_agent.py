import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import unittest
import time
from PIL import Image

import game_assistant
from game_assistant.core.config import (
    GameType, AssistCapability, AnalysisMode, MODEL_NAME, DEFAULT_POLL_INTERVAL,
    HOTKEY_EMERGENCY_STOP, HOTKEY_TOGGLE_POLL, ThinkingEffortLevel
)
from game_assistant.engines.jev_engine import (
    Choice, Noul, Score, JevDecisionEngine, JevResponse,
    ChoiceResult, NoulResult, ScoreResult
)
from game_assistant.utils.input_actuator import ScreenActuator
from game_assistant.strategies.base import (
    BaseGameStrategy, TelemetryData, StrategyDecision, ActionResult
)
from game_assistant.strategies.genshin import GenshinStrategy
from game_assistant.strategies.star_rail import StarRailStrategy
from game_assistant.strategies.zzz import ZZZStrategy
from game_assistant.strategies.general import GeneralGameStrategy
from game_assistant.strategies.registry import StrategyRegistry, get_game_strategy
from game_assistant.engines.ai_engine import GeminiAuxiliaryEngine, GeminiAIEngine
from game_assistant.core.agent import UniversalGameAgent


class TestConfig(unittest.TestCase):
    """測試系統配置與版本升級"""

    def test_gemini_model_upgrade(self):
        self.assertEqual(MODEL_NAME, "gemini-3.8-flash", "Gemini 模型必須升級為 gemini-3.8-flash")

    def test_fixed_poll_interval(self):
        self.assertEqual(DEFAULT_POLL_INTERVAL, 0.25, "畫面傳輸與決策輪詢間隔必須為 0.25 秒")

    def test_emergency_stop_hotkey(self):
        self.assertEqual(HOTKEY_EMERGENCY_STOP, "f8", "緊急急停熱鍵必須配置為 F8")

    def test_assist_capability_enum(self):
        self.assertTrue(hasattr(AssistCapability, "GUIDANCE"))
        self.assertTrue(hasattr(AssistCapability, "AUTONOMOUS"))
        self.assertTrue(hasattr(AssistCapability, "DATA_ANALYSIS"))
        self.assertTrue(hasattr(AssistCapability, "VOICE_QA"))


class TestJevEngine(unittest.TestCase):
    """測試 TypeSafe Jev (System 1) 決策引擎"""

    def setUp(self):
        self.engine = JevDecisionEngine()

    def test_primitives_serialization(self):
        c = Choice(instructions="選擇動作", criteria={"atk": None, "def": None})
        n = Noul(instructions="是否危險")
        s = Score(instructions="緊急度", criteria=["低", "中", "高"])

        self.assertEqual(c.to_dict()["type"], "choice")
        self.assertIn("atk", c.to_dict()["criteria"])
        self.assertEqual(n.to_dict()["type"], "noul")
        self.assertEqual(s.to_dict()["type"], "score")

    def test_local_heuristics_evaluation(self):
        state = "[Game]: 原神\n[ALERT]: 敵方攻擊前搖/紅圈警示！危險！\n[Player]: energy_full"
        questions = {
            "tactical_action": Choice(
                instructions="選擇動作",
                criteria={"dash_dodge": None, "burst_q": None, "idle": None}
            ),
            "should_evade": Noul(instructions="是否需要閃避攻擊警示？"),
            "combat_urgency": Score(instructions="緊急評分", criteria=["低", "中", "高"])
        }

        response = self.engine.evaluate(state, questions)
        self.assertIsInstance(response, JevResponse)
        self.assertIn("tactical_action", response.choices)
        self.assertIn("should_evade", response.nouls)
        self.assertIn("combat_urgency", response.scores)

        # 驗證啟發式命中
        self.assertTrue(response.nouls["should_evade"].noul, "在敵方攻擊前搖下，閃避判定應為 True")
        self.assertGreaterEqual(response.scores["combat_urgency"].score, 0.7, "緊急度打分應偏高")


class TestScreenActuator(unittest.TestCase):
    """測試螢幕操作致動器與安全急停"""

    def setUp(self):
        self.actuator = ScreenActuator(action_cooldown=0.01)

    def test_enable_disable(self):
        self.assertFalse(self.actuator.is_enabled)
        self.actuator.enable()
        self.assertTrue(self.actuator.is_enabled)
        self.actuator.disable()
        self.assertFalse(self.actuator.is_enabled)

    def test_emergency_stop(self):
        self.actuator.enable()
        self.assertTrue(self.actuator.is_enabled)
        self.actuator.emergency_stop()
        self.assertFalse(self.actuator.is_enabled, "急停後必須立即禁用操作")

    def test_action_execution_when_disabled(self):
        # 禁用時不發送實體按鍵
        res = self.actuator.press_key("e")
        self.assertFalse(res)

    def test_action_execution_when_enabled(self):
        self.actuator.enable()
        res = self.actuator.press_key("e")
        self.assertTrue(res)
        history = self.actuator.get_recent_history()
        self.assertGreater(len(history), 0)
        self.assertEqual(history[-1]["type"], "KEY_PRESS")


class TestGameStrategies(unittest.TestCase):
    """測試原神、星穹鐵道、絕區零、泛用遊戲策略與動態擴充"""

    def setUp(self):
        self.dummy_img = Image.new("RGB", (320, 240), color="blue")
        self.actuator = ScreenActuator(action_cooldown=0.01)

    def test_genshin_strategy(self):
        strategy = GenshinStrategy()
        self.assertEqual(strategy.game_type, GameType.GENSHIN)

        telemetry = strategy.extract_telemetry(self.dummy_img, visual_context="紅光前搖")
        self.assertTrue(telemetry.danger_detected)

        questions = strategy.build_jev_questions(AssistCapability.GUIDANCE, {})
        self.assertIn("tactical_action", questions)
        self.assertIn("should_evade", questions)

        state_str = strategy.build_jev_state(telemetry, "切換2號位", "幫我打反應", AssistCapability.GUIDANCE)
        self.assertIn("原神", state_str)

        # 模擬 Jev 決策
        jev_resp = JevResponse(
            choices={"tactical_action": ChoiceResult(choice="burst_q", confidence=0.92)},
            nouls={"should_evade": NoulResult(noul=False, confidence=0.9)},
            scores={"combat_urgency": ScoreResult(score=0.8, confidence=0.9)}
        )
        decision = strategy.interpret_decision(jev_resp, telemetry, AssistCapability.GUIDANCE)
        self.assertEqual(decision.primary_action, "burst_q")
        self.assertIn("Q", decision.guidance_text)

        # 測試代替操作 (開啓前)
        res_disabled = strategy.execute_action(decision, self.actuator)
        self.assertFalse(res_disabled.executed)

        # 測試代替操作 (開啓後)
        self.actuator.enable()
        res_enabled = strategy.execute_action(decision, self.actuator)
        self.assertTrue(res_enabled.executed)
        self.assertEqual(res_enabled.target_key_or_button, "q")

    def test_star_rail_strategy(self):
        strategy = StarRailStrategy()
        self.assertEqual(strategy.game_type, GameType.STAR_RAIL)

        telemetry = strategy.extract_telemetry(self.dummy_img, visual_context="SP不足 終結技滿")
        self.assertTrue(telemetry.energy_ready)

        questions = strategy.build_jev_questions(AssistCapability.AUTONOMOUS, {})
        self.assertIn("should_interrupt_ultimate", questions)

        jev_resp = JevResponse(
            choices={"tactical_action": ChoiceResult(choice="ultimate_1", confidence=0.95)},
            nouls={"should_interrupt_ultimate": NoulResult(noul=True, confidence=0.95)},
            scores={"sp_urgency": ScoreResult(score=0.9, confidence=0.9)}
        )
        decision = strategy.interpret_decision(jev_resp, telemetry, AssistCapability.AUTONOMOUS)
        self.assertEqual(decision.primary_action, "ultimate_1")

        self.actuator.enable()
        res = strategy.execute_action(decision, self.actuator)
        self.assertTrue(res.executed)
        self.assertEqual(res.target_key_or_button, "1")

    def test_zzz_strategy(self):
        strategy = ZZZStrategy()
        self.assertEqual(strategy.game_type, GameType.ZZZ)

        # 測試黃光極限招架
        telemetry_yellow = strategy.extract_telemetry(self.dummy_img, visual_context="敵方黃光前搖")
        self.assertTrue(telemetry_yellow.features["yellow_flash"])

        jev_resp = JevResponse(
            choices={"tactical_action": ChoiceResult(choice="parry_assist_space", confidence=0.98)},
            nouls={"yellow_flash": NoulResult(noul=True, confidence=0.98), "red_flash": NoulResult(noul=False)},
            scores={"reaction_urgency": ScoreResult(score=0.99, confidence=0.99)}
        )
        decision = strategy.interpret_decision(jev_resp, telemetry_yellow, AssistCapability.AUTONOMOUS)
        self.assertEqual(decision.primary_action, "parry_assist_space")

        self.actuator.enable()
        res = strategy.execute_action(decision, self.actuator)
        self.assertTrue(res.executed)
        self.assertEqual(res.target_key_or_button, "space")

    def test_general_strategy(self):
        strategy = GeneralGameStrategy()
        self.assertEqual(strategy.game_type, GameType.GENERAL)

        telemetry = strategy.extract_telemetry(self.dummy_img, visual_context="一般戰況")
        questions = strategy.build_jev_questions(AssistCapability.GUIDANCE, {})
        self.assertIn("tactical_action", questions)

        jev_resp = JevResponse(
            choices={"tactical_action": ChoiceResult(choice="use_skill_1", confidence=0.88)},
            nouls={"threat_alert": NoulResult(noul=False)},
            scores={"action_confidence": ScoreResult(score=0.8)}
        )
        decision = strategy.interpret_decision(jev_resp, telemetry, AssistCapability.AUTONOMOUS)
        self.assertEqual(decision.primary_action, "use_skill_1")

        self.actuator.enable()
        res = strategy.execute_action(decision, self.actuator)
        self.assertTrue(res.executed)
        self.assertEqual(res.target_key_or_button, "e")

    def test_strategy_registry_and_future_extension(self):
        """測試 Strategy 工廠與未來擴充能力"""
        # 測試取得已存在的預設策略
        genshin_strat = StrategyRegistry.get(GameType.GENSHIN)
        self.assertIsInstance(genshin_strat, GenshinStrategy)

        # 測試動態擴充一個全新自訂遊戲策略 (例如鳴潮 / 艾爾登法環)
        class CustomNewGameStrategy(BaseGameStrategy):
            @property
            def game_type(self) -> str:
                return "CustomNewGame"

            @property
            def name(self) -> str:
                return "新擴充遊戲 (Custom New Game)"

            def extract_telemetry(self, image, visual_context=""):
                return TelemetryData(timestamp=time.time(), game_type=GameType.GENERAL)

            def build_jev_questions(self, capability, context):
                return {"action": Choice(instructions="自訂遊戲動作", criteria={"jump": None})}

            def build_jev_state(self, telemetry, gemini_directive, user_demand, capability):
                return "[Custom Game State]"

            def interpret_decision(self, jev_response, telemetry, capability):
                return StrategyDecision(
                    primary_action="jump",
                    confidence=1.0,
                    urgency=0.5,
                    should_evade=False,
                    guidance_text="跳躍！",
                    telemetry=telemetry,
                    raw_jev=jev_response
                )

            def execute_action(self, decision, actuator):
                return ActionResult("jump", "space", True)

            def format_analysis(self, history):
                return "Custom Analysis"

        # 註冊新遊戲
        try:
            StrategyRegistry.register("CustomNewGame", CustomNewGameStrategy())
            retrieved = StrategyRegistry.get("CustomNewGame")
            self.assertEqual(retrieved.name, "新擴充遊戲 (Custom New Game)")
        finally:
            StrategyRegistry.initialize_default_strategies()


class TestUniversalGameAgent(unittest.TestCase):
    """測試 UniversalGameAgent 整合管線與 0.25 秒迴圈步驟"""

    def setUp(self):
        self.dummy_img = Image.new("RGB", (320, 240), color="green")
        self.agent = UniversalGameAgent(
            game_type=GameType.GENSHIN,
            capability=AssistCapability.GUIDANCE
        )

    def test_agent_initialization(self):
        self.assertEqual(self.agent.game_type, GameType.GENSHIN)
        self.assertEqual(self.agent.capability, AssistCapability.GUIDANCE)
        self.assertFalse(self.agent.actuator.is_enabled)

    def test_user_demand_and_directive(self):
        self.agent.set_user_demand("幫我打過這隻Boss，注意閃避")
        self.assertEqual(self.agent.current_user_demand, "幫我打過這隻Boss，注意閃避")
        self.assertTrue(len(self.agent.current_gemini_directive) > 0)

    def test_0_25s_step_pipeline(self):
        """測試 0.25 秒固定迴圈之執行步驟"""
        decision = self.agent.step(image=self.dummy_img)
        self.assertIsInstance(decision, StrategyDecision)
        self.assertIsNotNone(decision.primary_action)
        self.assertGreater(decision.confidence, 0.0)
        self.assertIsNotNone(decision.guidance_text)

    def test_autonomous_takeover_step(self):
        """測試代替操作模式下的螢幕自動操作"""
        self.agent.set_capability(AssistCapability.AUTONOMOUS)
        self.assertTrue(self.agent.actuator.is_enabled)

        decision = self.agent.step(image=self.dummy_img)
        self.assertIsNotNone(decision.action_result)
        self.assertTrue(decision.action_result.executed)

    def test_emergency_stop(self):
        """測試 F8 緊急急停中斷"""
        self.agent.set_capability(AssistCapability.AUTONOMOUS)
        self.assertTrue(self.agent.actuator.is_enabled)

        self.agent.emergency_stop()
        self.assertFalse(self.agent.actuator.is_enabled)
        self.assertEqual(self.agent.capability, AssistCapability.GUIDANCE)

    def test_data_analysis_generation(self):
        # 執行幾次 step 產生遙測取樣
        for _ in range(5):
            self.agent.step(image=self.dummy_img)
        report = self.agent.generate_data_analysis_report()
        self.assertIn("實時戰況遙測分析", report)


class TestEdgeCasesAndRobustness(unittest.TestCase):
    """邊界情境與強健性測試"""

    def setUp(self):
        self.agent = UniversalGameAgent()
        self.agent.nervous_system.reflex_registry.clear()

    def test_empty_state_and_empty_questions(self):
        engine = JevDecisionEngine()
        res_empty = engine.evaluate(state="", questions={})
        self.assertIsInstance(res_empty, JevResponse)
        self.assertEqual(len(res_empty.choices), 0)
        self.assertEqual(len(res_empty.nouls), 0)

    def test_unknown_game_fallback_to_general(self):
        strat = StrategyRegistry.get("NonExistentGame_12345")
        self.assertIsInstance(strat, GeneralGameStrategy)
        self.assertEqual(strat.game_type, GameType.GENERAL)

    def test_empty_user_demand(self):
        self.agent.set_user_demand("")
        self.assertEqual(self.agent.current_user_demand, "")
        self.assertEqual(self.agent.current_gemini_directive, "")

    def test_consecutive_emergency_stops(self):
        self.agent.set_capability(AssistCapability.AUTONOMOUS)
        self.agent.emergency_stop()
        self.assertFalse(self.agent.actuator.is_enabled)
        # 連續多次急停不應報錯
        self.agent.emergency_stop()
        self.agent.emergency_stop()
        self.assertFalse(self.agent.actuator.is_enabled)

    def test_custom_prompt_empty(self):
        img = Image.new("RGB", (100, 100))
        # 離線狀態下應傳回友善提示而非 crash
        res = self.agent.trigger_deep_analysis(img, custom_prompt="")
        self.assertIsInstance(res, str)
        self.assertTrue(len(res) > 0)

    def test_emergency_stop_releases_held_keys(self):
        """測試 F8 急停能確實釋放所有記錄中的按鍵與滑鼠狀態"""
        actuator = ScreenActuator()
        actuator.enable()
        actuator._held_keys.add("shift")
        actuator._held_keys.add("space")
        self.assertEqual(len(actuator._held_keys), 2)

        actuator.emergency_stop()
        self.assertFalse(actuator.is_enabled)
        self.assertEqual(len(actuator._held_keys), 0, "急停後 held_keys 必須被清空")

    def test_screen_actuator_cooldown_enforcement(self):
        """測試致動器在冷卻時間內不會發送重複按鍵"""
        actuator = ScreenActuator(action_cooldown=0.5)
        actuator.enable()
        first_act = actuator.press_key("e")
        self.assertTrue(first_act)
        # 立即再次調用，應受限於 0.5s 冷卻而拒絕
        second_act = actuator.press_key("e")
        self.assertFalse(second_act, "未過冷卻期應拒絕操作")

    def test_data_analysis_questions_for_all_strategies(self):
        """測試所有策略在 DATA_ANALYSIS 模式下皆注入專屬遙測問題"""
        strategies = [
            GenshinStrategy(),
            StarRailStrategy(),
            ZZZStrategy(),
            GeneralGameStrategy()
        ]
        for strat in strategies:
            questions = strat.build_jev_questions(AssistCapability.DATA_ANALYSIS, {})
            self.assertIn("combat_phase", questions, f"{strat.name} 應包含 combat_phase 問題")
            self.assertIn("rotation_efficiency", questions, f"{strat.name} 應包含 rotation_efficiency 問題")
            self.assertIn("needs_optimization", questions, f"{strat.name} 應包含 needs_optimization 問題")

    def test_user_demand_pipeline_with_image(self):
        """測試 Requirement 4: 由 Gemini 處理使用者需求(含影像)後無縫傳遞給 Jev 決策"""
        dummy_img = Image.new("RGB", (320, 240), color="red")
        self.agent.set_user_demand("幫我打過這隻怪物，注意黃光招架", image=dummy_img)
        self.assertIn("招架", self.agent.current_gemini_directive)

        # 緊接著接入 Jev 決策迴圈
        decision = self.agent.step(image=dummy_img)
        self.assertIsNotNone(decision)
        self.assertIsNotNone(decision.guidance_text)

    def test_tts_engine_stop_safe_call(self):
        """測試 TTSEngine.stop() 可安全呼叫且不崩潰"""
        from game_assistant.audio.tts_engine import TTSEngine
        tts = TTSEngine()
        tts.stop()  # 無作用時不應拋錯
        self.assertIsNone(tts._current_engine)

    def test_jev_primitives_dual_compatibility(self):
        """測試 Choice/Noul/Score 同時相容 options 列表與 criteria 字典"""
        c1 = Choice(instructions="動作", criteria={"atk": None, "def": None})
        self.assertIn("atk", c1.options)
        self.assertEqual(c1.to_dict()["type"], "choice")

        c2 = Choice(instructions="動作2", options=["dodge", "parry"])
        self.assertIn("dodge", c2.criteria)
        self.assertEqual(c2.to_dict()["options"], ["dodge", "parry"])

        s = Score(instructions="評分", criteria=["低", "高"])
        self.assertEqual(s.to_dict()["type"], "score")


class TestPackageStructureAndExports(unittest.TestCase):
    """測試重構後 src/ layout 與各 Package 之匯出介面與跨模組引用完整性"""

    def test_package_root_metadata(self):
        self.assertEqual(game_assistant.__version__, "0.2.0")
        self.assertTrue(hasattr(game_assistant, "UniversalGameAgent"))
        self.assertTrue(hasattr(game_assistant, "JevDecisionEngine"))
        self.assertTrue(hasattr(game_assistant, "GeminiAuxiliaryEngine"))
        self.assertTrue(hasattr(game_assistant, "ScreenCapturer"))
        self.assertTrue(hasattr(game_assistant, "ScreenActuator"))
        self.assertTrue(hasattr(game_assistant, "TTSEngine"))
        self.assertTrue(hasattr(game_assistant, "STTEngine"))
        self.assertIn("UniversalGameAgent", game_assistant.__all__)

    def test_cli_console_scripts_entrypoint(self):
        from game_assistant.cli import main as cli_main
        self.assertTrue(callable(cli_main))

    def test_app_controller_exports(self):
        from game_assistant.app import (
            GameAssistantController,
            JevLoopWorker,
            GeminiIntentWorker,
            DeepVisionWorker,
            STTWorker,
            TTSWorker,
        )
        self.assertIsNotNone(GameAssistantController)
        self.assertIsNotNone(JevLoopWorker)
        self.assertIsNotNone(GeminiIntentWorker)
        self.assertIsNotNone(DeepVisionWorker)
        self.assertIsNotNone(STTWorker)
        self.assertIsNotNone(TTSWorker)

    def test_core_package_exports(self):
        from game_assistant import core
        self.assertTrue(hasattr(core, "UniversalGameAgent"))
        self.assertTrue(hasattr(core, "GameType"))
        self.assertTrue(hasattr(core, "AnalysisMode"))
        self.assertTrue(hasattr(core, "AssistCapability"))
        self.assertTrue(hasattr(core, "DEFAULT_POLL_INTERVAL"))
        self.assertTrue(hasattr(core, "POLL_INTERVAL"))
        self.assertTrue(hasattr(core, "DEFAULT_OPACITY"))
        self.assertTrue(hasattr(core, "MAX_IMAGE_SIZE"))
        self.assertTrue(hasattr(core, "HOTKEY_EMERGENCY_STOP"))
        self.assertTrue(hasattr(core, "HOTKEY_TOGGLE_POLL"))
        self.assertTrue(hasattr(core, "HOTKEY_MANUAL_TRIGGER"))
        self.assertTrue(hasattr(core, "HOTKEY_CAPTURE_NOW"))
        self.assertTrue(hasattr(core, "HOTKEY_VOICE_PROMPT"))
        self.assertTrue(hasattr(core, "TTS_ENABLED"))
        self.assertTrue(hasattr(core, "TTS_RATE"))
        self.assertTrue(hasattr(core, "TTS_VOLUME"))
        self.assertTrue(hasattr(core, "STT_LANGUAGE"))
        self.assertTrue(hasattr(core, "STT_TIMEOUT"))
        self.assertTrue(hasattr(core, "STT_PHRASE_TIME_LIMIT"))
        self.assertTrue(hasattr(core, "PROMPTS"))
        # 驗證 __all__ 包含核心成員
        self.assertIn("HOTKEY_MANUAL_TRIGGER", core.__all__)
        self.assertIn("DEFAULT_OPACITY", core.__all__)
        self.assertIn("UniversalGameAgent", core.__all__)

    def test_engines_package_exports(self):
        from game_assistant import engines
        self.assertTrue(hasattr(engines, "Choice"))
        self.assertTrue(hasattr(engines, "Noul"))
        self.assertTrue(hasattr(engines, "Score"))
        self.assertTrue(hasattr(engines, "JevDecisionEngine"))
        self.assertTrue(hasattr(engines, "GeminiAuxiliaryEngine"))
        self.assertTrue(hasattr(engines, "GeminiAIEngine"))
        self.assertTrue(hasattr(engines, "OFFICIAL_SDK_AVAILABLE"))
        self.assertIn("JevDecisionEngine", engines.__all__)
        self.assertIn("GeminiAuxiliaryEngine", engines.__all__)

    def test_audio_package_exports(self):
        from game_assistant import audio
        self.assertTrue(hasattr(audio, "TTSEngine"))
        self.assertTrue(hasattr(audio, "clean_markdown_for_tts"))
        self.assertTrue(hasattr(audio, "STTEngine"))
        self.assertIn("TTSEngine", audio.__all__)
        self.assertIn("clean_markdown_for_tts", audio.__all__)
        self.assertIn("STTEngine", audio.__all__)

    def test_utils_package_exports(self):
        from game_assistant import utils
        self.assertTrue(hasattr(utils, "ScreenCapturer"))
        self.assertTrue(hasattr(utils, "ScreenActuator"))
        self.assertIn("ScreenCapturer", utils.__all__)
        self.assertIn("ScreenActuator", utils.__all__)

    def test_ui_package_exports(self):
        from game_assistant import ui
        self.assertTrue(hasattr(ui, "GameAssistantOverlay"))
        self.assertTrue(hasattr(ui, "HotkeyListener"))
        self.assertIn("GameAssistantOverlay", ui.__all__)
        self.assertIn("HotkeyListener", ui.__all__)

    def test_gui_half_width_and_font_scaling(self):
        """測試 GameAssistantOverlay 半寬全高佈局與字體 1.5 倍放大屬性"""
        import os
        from PyQt6.QtWidgets import QApplication
        from game_assistant.ui.gui import GameAssistantOverlay

        app = QApplication.instance() or QApplication(["-platform", "offscreen"])
        overlay = GameAssistantOverlay()

        # 1. 檢驗視窗尺寸：左右寬度一半、上下佔滿（至少為最低安全寬度 400）
        self.assertGreaterEqual(overlay.width(), 400)
        self.assertGreaterEqual(overlay.height(), 350)

        # 2. 檢驗按鈕放大 1.5 倍
        self.assertEqual(overlay.btn_collapse.width(), 36)
        self.assertEqual(overlay.btn_collapse.height(), 36)

        # 3. 檢驗狀態標籤與 HUD 字體樣式放大 1.5 倍
        self.assertIn("font-size: 17px;", overlay.status_badge.styleSheet())
        self.assertIn("font-size: 15px;", overlay.lbl_nervous_hud.styleSheet())
        self.assertIn("font-size: 15px;", overlay.status_footer.styleSheet())

        # 4. 檢驗收合與展開邏輯
        overlay.toggle_collapse()
        self.assertTrue(overlay.is_collapsed)
        self.assertEqual(overlay.height(), 75)
        overlay.toggle_collapse()
        self.assertFalse(overlay.is_collapsed)
        self.assertGreaterEqual(overlay.height(), 350)

    def test_hotkey_listener_dual_track_and_debounce(self):
        """測試 HotkeyListener 雙軌監聽、虛擬鍵碼對映與 250ms 防抖機制"""
        import time
        from unittest.mock import MagicMock
        from game_assistant.ui.gui import HotkeyListener
        from pynput import keyboard

        listener = HotkeyListener()

        # 1. 驗證虛擬鍵碼 (VK) 映射表涵蓋 F6 ~ F12
        expected_vks = {117, 118, 119, 120, 121, 122, 123}
        self.assertEqual(set(listener._vk_map.keys()), expected_vks)

        # 2. 測試信號槽與防抖 (debounce)
        received_signals = []
        listener.toggle_poll_signal.connect(lambda: received_signals.append("toggle_poll"))

        # 首次觸發應成功發射信號
        listener._trigger_signal("toggle_poll_signal")
        self.assertEqual(len(received_signals), 1)

        # 在 250ms 內連續重複觸發，防抖應攔截
        listener._trigger_signal("toggle_poll_signal")
        listener._trigger_signal("toggle_poll_signal")
        self.assertEqual(len(received_signals), 1)

        # 手動將上次觸發時間往前推移 0.3 秒，模擬時間流逝
        listener._last_trigger_times["toggle_poll_signal"] = time.time() - 0.3
        listener._trigger_signal("toggle_poll_signal")
        self.assertEqual(len(received_signals), 2)

        # 3. 測試 pynput 事件帶 vk 屬性 (原神 DirectInput / 虛擬鍵碼場景)
        class DummyKeyWithVk:
            def __init__(self, vk):
                self.vk = vk

        f10_signals = []
        listener.manual_trigger_signal.connect(lambda: f10_signals.append("manual_f10"))
        listener._pynput_on_press(DummyKeyWithVk(121))  # VK_F10 = 121
        self.assertEqual(len(f10_signals), 1)

        # 4. 測試 pynput Key 枚舉備援匹配
        f11_signals = []
        listener.voice_prompt_signal.connect(lambda: f11_signals.append("voice_f11"))
        listener._pynput_on_press(keyboard.Key.f11)
        self.assertEqual(len(f11_signals), 1)

        # 5. 測試停止
        listener.stop()
        self.assertTrue(listener._stop_event.is_set())

    def test_strategies_package_exports(self):
        from game_assistant import strategies
        self.assertTrue(hasattr(strategies, "BaseGameStrategy"))
        self.assertTrue(hasattr(strategies, "GenshinStrategy"))
        self.assertTrue(hasattr(strategies, "StarRailStrategy"))
        self.assertTrue(hasattr(strategies, "ZZZStrategy"))
        self.assertTrue(hasattr(strategies, "GeneralGameStrategy"))
        self.assertTrue(hasattr(strategies, "StrategyRegistry"))
        self.assertTrue(hasattr(strategies, "get_game_strategy"))

    def test_main_entrypoint_imports(self):
        from main import (
            GameAssistantController,
            JevLoopWorker,
            GeminiIntentWorker,
            DeepVisionWorker,
            STTWorker,
            TTSWorker,
            main as main_entry
        )
        self.assertTrue(callable(main_entry))
        self.assertIsNotNone(GameAssistantController)
        self.assertIsNotNone(STTWorker)
        self.assertIsNotNone(TTSWorker)

    def test_cli_argparse_parser(self):
        from game_assistant.cli import build_parser
        parser = build_parser()
        self.assertIsNotNone(parser)
        # 測試 --version 參數解析
        with self.assertRaises(SystemExit) as cm:
            parser.parse_args(["--version"])
        self.assertEqual(cm.exception.code, 0)

        # 測試 --help 參數解析
        with self.assertRaises(SystemExit) as cm_help:
            parser.parse_args(["--help"])
        self.assertEqual(cm_help.exception.code, 0)

    def test_pyproject_toml_configuration(self):
        toml_path = _PROJECT_ROOT / "pyproject.toml"
        self.assertTrue(toml_path.exists())
        content = toml_path.read_text(encoding="utf-8")
        self.assertIn('name = "game-assistant"', content)
        self.assertIn('game-assistant = "game_assistant.cli:main"', content)
        self.assertIn('where = ["src"]', content)
        self.assertIn("sys_platform == 'win32'", content)


class TestJevOfficialProtocolAndSafety(unittest.TestCase):
    """測試 TypeSafe AI Jev 官方規格協議、Noul 浮點數機率解析與信心度安全閘控"""

    def setUp(self):
        self.engine = JevDecisionEngine()

    def test_official_api_response_parsing(self):
        """測試符合 TypeSafe 官方 HTTP API 規格的 answers 映射結構解析"""
        official_data = {
            "model": "jev-latest",
            "answers": {
                "tactical_action": {
                    "type": "choice",
                    "choice": "burst_q",
                    "confidence": 0.92,
                    "probabilities": {"burst_q": 0.92, "skill_e": 0.08}
                },
                "should_evade": {
                    "type": "noul",
                    "noul": 0.88
                },
                "combat_urgency": {
                    "type": "score",
                    "score": 1.6,
                    "legend": {"0": "安全", "1": "普通對峙", "2": "爆發危險"},
                    "probabilities": {"0": 0.05, "1": 0.3, "2": 0.65},
                    "confidence": 0.78
                }
            },
            "usage": {"input_tokens": 312, "output_tokens": 48}
        }

        resp = self.engine._parse_api_response(official_data)
        self.assertIn("tactical_action", resp.choices)
        self.assertEqual(resp.choices["tactical_action"].choice, "burst_q")
        self.assertAlmostEqual(resp.choices["tactical_action"].confidence, 0.92)
        self.assertEqual(resp.choices["tactical_action"].probabilities.get("burst_q"), 0.92)

        self.assertIn("should_evade", resp.nouls)
        self.assertAlmostEqual(resp.nouls["should_evade"].noul, 0.88)
        self.assertTrue(resp.nouls["should_evade"].is_positive(threshold=0.5))
        self.assertTrue(bool(resp.nouls["should_evade"]))

        self.assertIn("combat_urgency", resp.scores)
        self.assertAlmostEqual(resp.scores["combat_urgency"].score, 1.6)
        self.assertAlmostEqual(resp.scores["combat_urgency"].confidence, 0.78)
        self.assertEqual(resp.scores["combat_urgency"].legend.get("1"), "普通對峙")

    def test_noul_probability_thresholds(self):
        """測試 Noul 機率浮點數閾值防禦，杜絕非零 float 在 Python 中誤判為真"""
        # 低機率 (0.05): 表示非危險 / 不需閃避
        n_safe = NoulResult(noul=0.05)
        self.assertAlmostEqual(n_safe.noul, 0.05)
        self.assertFalse(n_safe.is_positive(threshold=0.5))
        self.assertFalse(bool(n_safe), "低機率 0.05 在 bool() 判定下必須為 False")

        # 高機率 (0.85): 表示高度危險 / 需閃避
        n_danger = NoulResult(noul=0.85)
        self.assertAlmostEqual(n_danger.noul, 0.85)
        self.assertTrue(n_danger.is_positive(threshold=0.5))
        self.assertTrue(bool(n_danger), "高機率 0.85 在 bool() 判定下必須為 True")

        # 向下相容 bool 傳入
        n_legacy_true = NoulResult(noul=True)
        self.assertAlmostEqual(n_legacy_true.noul, 1.0)
        self.assertTrue(bool(n_legacy_true))

        n_legacy_false = NoulResult(noul=False)
        self.assertAlmostEqual(n_legacy_false.noul, 0.0)
        self.assertFalse(bool(n_legacy_false))

    def test_confidence_gated_routing_genshin(self):
        """測試原神策略在代替操作模式下的信心度閘門 (Confidence-Gated Routing)"""
        strat = GenshinStrategy()
        dummy_img = Image.new("RGB", (100, 100))
        telemetry = strat.extract_telemetry(dummy_img)

        # 1. 低信心度 (0.35) 的高風險動作 -> 應安全降級為 idle
        low_conf_resp = JevResponse(
            choices={"tactical_action": ChoiceResult(choice="burst_q", confidence=0.35)},
            nouls={"should_evade": NoulResult(noul=0.1)},
            scores={"combat_urgency": ScoreResult(score=0.3)}
        )
        decision_low = strat.interpret_decision(low_conf_resp, telemetry, AssistCapability.AUTONOMOUS)
        self.assertEqual(decision_low.primary_action, "idle", "代替操作模式下，低置信度動作應被安全門禁降級為 idle")

        # 2. 高信心度 (0.88) 的高風險動作 -> 正常採納
        high_conf_resp = JevResponse(
            choices={"tactical_action": ChoiceResult(choice="burst_q", confidence=0.88)},
            nouls={"should_evade": NoulResult(noul=0.1)},
            scores={"combat_urgency": ScoreResult(score=0.8)}
        )
        decision_high = strat.interpret_decision(high_conf_resp, telemetry, AssistCapability.AUTONOMOUS)
        self.assertEqual(decision_high.primary_action, "burst_q", "高置信度動作應正常被採納")

    def test_primitives_serialization_official_spec(self):
        """測試 Primitives 序列化嚴格遵循 TypeSafe 官方 JSON 規格"""
        c = Choice(
            instructions="選擇戰術動作",
            options=["burst_q", "skill_e"]
        )
        c_dict = c.to_dict()
        self.assertEqual(c_dict["type"], "choice")
        self.assertEqual(c_dict["instructions"], "選擇戰術動作")
        self.assertIn("burst_q", c_dict["criteria"])
        self.assertNotIn("name", c_dict)
        self.assertIn("burst_q", c_dict["options"])

        n = Noul(
            instructions="是否有危險",
            criteria={"true": "存在紅圈", "false": "安全"}
        )
        n_dict = n.to_dict()
        self.assertEqual(n_dict["type"], "noul")
        self.assertEqual(n_dict["criteria"]["true"], "存在紅圈")

        s = Score(
            instructions="評分緊急度",
            criteria=["平穩", "緊張", "爆發"]
        )
        s_dict = s.to_dict()
        self.assertEqual(s_dict["type"], "score")
        self.assertEqual(len(s_dict["criteria"]), 3)


class TestMultiScenarioExpansion(unittest.TestCase):
    """測試擴充之多情境功能：大世界探索蒐集、裝備調整與強化分析"""

    def setUp(self):
        self.dummy_img = Image.new("RGB", (320, 240), color="blue")
        self.actuator = ScreenActuator(action_cooldown=0.01)
        self.actuator.enable()

    def test_new_assist_capabilities_and_modes(self):
        """驗證新枚舉能力與分析模式"""
        self.assertTrue(hasattr(AssistCapability, "EXPLORATION"))
        self.assertTrue(hasattr(AssistCapability, "EQUIPMENT_BUILD"))
        self.assertEqual(AssistCapability.EXPLORATION.value, "探索蒐集 (Exploration & Gathering)")
        self.assertEqual(AssistCapability.EQUIPMENT_BUILD.value, "裝備調整與強化 (Gear Tuning & Upgrade)")

        self.assertTrue(hasattr(AnalysisMode, "EQUIPMENT_ENHANCE"))
        self.assertTrue(hasattr(AnalysisMode, "EXPLORATION_MAP"))

    def test_genshin_exploration_and_gear_upgrade(self):
        """測試原神策略在大世界探索與聖遺物雙暴強化下的 Jev 決策"""
        strat = GenshinStrategy()

        # 1. 探索模式
        telemetry_exp = strat.extract_telemetry(self.dummy_img, visual_context="發現散失的神瞳與珍貴寶箱")
        self.assertFalse(telemetry_exp.in_combat)
        self.assertTrue(telemetry_exp.has_interactive_target)
        self.assertIn("寶箱", telemetry_exp.target_name)

        q_exp = strat.build_jev_questions(AssistCapability.EXPLORATION, {})
        self.assertIn("exploration_action", q_exp)
        self.assertIn("has_interactive_target", q_exp)
        self.assertIn("exploration_priority", q_exp)

        resp_exp = JevResponse(
            choices={"exploration_action": ChoiceResult(choice="open_chest", confidence=0.92)},
            nouls={"has_interactive_target": NoulResult(noul=0.95)},
            scores={"exploration_priority": ScoreResult(score=0.9)}
        )
        dec_exp = strat.interpret_decision(resp_exp, telemetry_exp, AssistCapability.EXPLORATION)
        self.assertEqual(dec_exp.primary_action, "open_chest")
        self.assertIn("按 【F】 開啟", dec_exp.guidance_text)

        # 測試探索代替操作
        action_res = strat.execute_action(dec_exp, self.actuator)
        self.assertEqual(action_res.target_key_or_button, "f")
        self.assertTrue(action_res.executed)

        # 2. 聖遺物強化模式
        telemetry_gear = strat.extract_telemetry(self.dummy_img, visual_context="聖遺物暴擊傷害30分雙暴極品胚子")
        self.assertGreater(telemetry_gear.gear_score, 30.0)

        q_gear = strat.build_jev_questions(AssistCapability.EQUIPMENT_BUILD, {})
        self.assertIn("enhancement_action", q_gear)
        self.assertIn("is_worth_upgrading", q_gear)
        self.assertIn("should_lock", q_gear)
        self.assertIn("gear_score", q_gear)

        resp_gear = JevResponse(
            choices={"enhancement_action": ChoiceResult(choice="lock_and_keep", confidence=0.95)},
            nouls={"is_worth_upgrading": NoulResult(noul=0.95), "should_lock": NoulResult(noul=0.98)},
            scores={"gear_score": ScoreResult(score=0.85), "upgrade_potential": ScoreResult(score=0.9)}
        )
        dec_gear = strat.interpret_decision(resp_gear, telemetry_gear, AssistCapability.EQUIPMENT_BUILD)
        self.assertEqual(dec_gear.primary_action, "lock_and_keep")
        self.assertIn("上鎖", dec_gear.guidance_text)

    def test_star_rail_exploration_and_relic_upgrade(self):
        """測試星穹鐵道在次元撲滿抓捕與遺器配速/自塑塵脂下的 Jev 決策"""
        strat = StarRailStrategy()

        # 1. 銀河探索：次元撲滿
        telemetry_trotter = strat.extract_telemetry(self.dummy_img, visual_context="警告：前方發現次元撲滿")
        self.assertTrue(telemetry_trotter.has_interactive_target)
        self.assertIn("撲滿", telemetry_trotter.target_name)

        q_exp = strat.build_jev_questions(AssistCapability.EXPLORATION, {})
        self.assertIn("catch_trotter", q_exp["exploration_action"].criteria)
        self.assertIn("is_urgent_trotter", q_exp)

        resp_trotter = JevResponse(
            choices={"exploration_action": ChoiceResult(choice="catch_trotter", confidence=0.96)},
            nouls={"is_urgent_trotter": NoulResult(noul=0.9)},
            scores={"exploration_priority": ScoreResult(score=1.0)}
        )
        dec_trotter = strat.interpret_decision(resp_trotter, telemetry_trotter, AssistCapability.EXPLORATION)
        self.assertEqual(dec_trotter.primary_action, "catch_trotter")
        self.assertIn("次元撲滿", dec_trotter.guidance_text)

        # 撲滿秘技先手操作
        act_res = strat.execute_action(dec_trotter, self.actuator)
        self.assertEqual(act_res.target_key_or_button, "e")
        self.assertTrue(act_res.executed)

        # 2. 遺器自塑塵脂推薦
        telemetry_relic = strat.extract_telemetry(self.dummy_img, visual_context="遺器 134 速度鞋與充能繩")
        q_relic = strat.build_jev_questions(AssistCapability.EQUIPMENT_BUILD, {})
        self.assertIn("craft_with_resin", q_relic["enhancement_action"].criteria)
        self.assertIn("meets_speed_threshold", q_relic)

        resp_relic = JevResponse(
            choices={"enhancement_action": ChoiceResult(choice="craft_with_resin", confidence=0.91)},
            nouls={"meets_speed_threshold": NoulResult(noul=0.85), "is_worth_upgrading": NoulResult(noul=0.9)},
            scores={"gear_score": ScoreResult(score=0.7), "upgrade_potential": ScoreResult(score=0.8)}
        )
        dec_relic = strat.interpret_decision(resp_relic, telemetry_relic, AssistCapability.EQUIPMENT_BUILD)
        self.assertEqual(dec_relic.primary_action, "craft_with_resin")
        self.assertIn("自塑塵脂", dec_relic.guidance_text)

    def test_zzz_exploration_and_drive_disc_upgrade(self):
        """測試絕區零在六分街物資與驅動光碟調律拆解下的 Jev 決策"""
        strat = ZZZStrategy()

        # 1. 街區探索：小卡格車
        telemetry_cargo = strat.extract_telemetry(self.dummy_img, visual_context="發現遺失的小卡格車與喵吉委託")
        self.assertTrue(telemetry_cargo.has_interactive_target)
        self.assertIn("小卡格車", telemetry_cargo.target_name)

        q_exp = strat.build_jev_questions(AssistCapability.EXPLORATION, {})
        self.assertIn("collect_cargo_truck", q_exp["exploration_action"].criteria)

        resp_cargo = JevResponse(
            choices={"exploration_action": ChoiceResult(choice="collect_cargo_truck", confidence=0.9)},
            nouls={"has_interactive_target": NoulResult(noul=0.9)},
            scores={"exploration_priority": ScoreResult(score=0.8)}
        )
        dec_cargo = strat.interpret_decision(resp_cargo, telemetry_cargo, AssistCapability.EXPLORATION)
        self.assertEqual(dec_cargo.primary_action, "collect_cargo_truck")
        self.assertIn("按 【F】 拾取", dec_cargo.guidance_text)

        # 2. 驅動光碟調律校音器
        telemetry_disc = strat.extract_telemetry(self.dummy_img, visual_context="S級驅動光碟調律校音器主詞條")
        q_disc = strat.build_jev_questions(AssistCapability.EQUIPMENT_BUILD, {})
        self.assertIn("tune_with_calibrator", q_disc["enhancement_action"].criteria)

        resp_disc = JevResponse(
            choices={"enhancement_action": ChoiceResult(choice="tune_with_calibrator", confidence=0.92)},
            nouls={"is_worth_upgrading": NoulResult(noul=0.8), "should_lock": NoulResult(noul=0.5)},
            scores={"gear_score": ScoreResult(score=0.75), "upgrade_potential": ScoreResult(score=0.8)}
        )
        dec_disc = strat.interpret_decision(resp_disc, telemetry_disc, AssistCapability.EQUIPMENT_BUILD)
        self.assertEqual(dec_disc.primary_action, "tune_with_calibrator")
        self.assertIn("校音器", dec_disc.guidance_text)

    def test_general_game_exploration_and_gear(self):
        """測試泛用遊戲模式在拾取與裝等比對下的決策"""
        strat = GeneralGameStrategy()

        # 1. 探索拾取
        telemetry_loot = strat.extract_telemetry(self.dummy_img, visual_context="地面掉落物與寶箱拾取")
        self.assertTrue(telemetry_loot.has_interactive_target)

        q_exp = strat.build_jev_questions(AssistCapability.EXPLORATION, {})
        self.assertIn("interact_pickup", q_exp["exploration_action"].criteria)

        resp_loot = JevResponse(
            choices={"exploration_action": ChoiceResult(choice="interact_pickup", confidence=0.88)},
            nouls={"has_interactive_target": NoulResult(noul=0.85)},
            scores={"exploration_priority": ScoreResult(score=0.7)}
        )
        dec_loot = strat.interpret_decision(resp_loot, telemetry_loot, AssistCapability.EXPLORATION)
        self.assertEqual(dec_loot.primary_action, "interact_pickup")

        # 2. 裝備比對
        q_gear = strat.build_jev_questions(AssistCapability.EQUIPMENT_BUILD, {})
        self.assertIn("compare_and_equip", q_gear["enhancement_action"].criteria)

    def test_ai_engine_equipment_and_exploration_fallback(self):
        """測試 Gemini 認知引擎在無金鑰時的裝備與探索離線啟發降級"""
        engine = GeminiAuxiliaryEngine()

        # 1. 裝備評估
        res_genshin_gear = engine.evaluate_equipment_screen(self.dummy_img, GameType.GENSHIN)
        self.assertTrue(any(kw in res_genshin_gear for kw in ["聖遺物", "雙暴", "詞條", "原神", "裝備"]))

        res_hsr_gear = engine.evaluate_equipment_screen(self.dummy_img, GameType.STAR_RAIL)
        self.assertTrue(any(kw in res_hsr_gear for kw in ["自塑塵脂", "遺器", "星穹鐵道", "詞條", "裝備"]))

        res_zzz_gear = engine.evaluate_equipment_screen(self.dummy_img, GameType.ZZZ)
        self.assertTrue(any(kw in res_zzz_gear for kw in ["調律", "校音器", "驅動盤", "音擎", "絕區零", "裝備"]))

        # 2. 探索指引
        res_genshin_exp = engine.guide_exploration_screen(self.dummy_img, GameType.GENSHIN)
        self.assertTrue(any(kw in res_genshin_exp for kw in ["神瞳", "探索", "採集", "原神", "素材"]))

        res_hsr_exp = engine.guide_exploration_screen(self.dummy_img, GameType.STAR_RAIL)
        self.assertTrue(any(kw in res_hsr_exp for kw in ["次元撲滿", "撲滿", "星穹鐵道", "寶箱", "探索"]))

        res_zzz_exp = engine.guide_exploration_screen(self.dummy_img, GameType.ZZZ)
        self.assertTrue(any(kw in res_zzz_exp for kw in ["喵吉", "空洞", "卡格車", "絕區零", "探索"]))

    def test_universal_agent_new_capabilities(self):
        """測試 UniversalGameAgent 在新能力下的運作與便捷方法"""
        agent = UniversalGameAgent(game_type=GameType.GENSHIN, capability=AssistCapability.EXPLORATION)
        agent.nervous_system.reflex_registry.clear()
        dec = agent.step(image=self.dummy_img)
        self.assertIsNotNone(dec)
        self.assertIn(dec.primary_action, ["gather_specialty", "open_chest", "collect_oculus", "solve_puzzle", "follow_route", "idle"])

        # 測試便捷方法
        gear_md = agent.evaluate_equipment(image=self.dummy_img)
        self.assertTrue(any(kw in gear_md for kw in ["聖遺物", "詞條", "裝備", "畫面", "原神"]))

        exp_md = agent.guide_exploration(image=self.dummy_img)
        self.assertTrue(any(kw in exp_md for kw in ["大世界", "探索", "採集", "神瞳", "路線", "原神"]))

    def test_universal_agent_evolution_and_organs(self):
        """測試 UniversalGameAgent 的自律器官生長、網路感官與進化報告"""
        from game_assistant.organs.base import OrganType

        agent = UniversalGameAgent(game_type=GameType.GENSHIN)

        # 1. 進化報告產出
        report = agent.get_evolution_report()
        self.assertIn("brain_engine", report)
        self.assertIn("memory_index", report)
        self.assertIn("organs", report)
        self.assertIn("status_line", report)
        self.assertIn("🧠 大腦:", report["status_line"])

        # 2. 網路感官情報查詢
        build = agent.fetch_character_build("那維萊特")
        self.assertEqual(build["character"], "那維萊特")
        self.assertTrue(len(build["best_equipment"]) > 0)

        explore = agent.fetch_exploration_guide("納塔 燃素")
        self.assertIn("納塔", explore["target"])

        # 3. 自律生長器官工具
        new_organ = agent.grow_organ(
            requirement="監測畫面左上方小地圖的紅點警示",
            organ_type=OrganType.SENSORY_EYE,
            name="小地圖敵方雷達眼",
            organ_id="eye_minimap_radar"
        )
        self.assertIsNotNone(new_organ)
        self.assertEqual(new_organ.organ_id, "eye_minimap_radar")

        # 驗證掛載與 Predicates 收集
        preds = agent.organ_registry.collect_all_predicates()
        self.assertIsInstance(preds, dict)


class TestGemini38FlashMigration(unittest.TestCase):
    """測試 Gemini 3.8 Flash 模型遷移、Thinking Level 配置與結構化輸出"""

    def setUp(self):
        self.engine = GeminiAuxiliaryEngine(api_key="")
        self.dummy_img = Image.new("RGB", (100, 100), color="yellow")

    def test_model_name_constant(self):
        self.assertEqual(MODEL_NAME, "gemini-3.8-flash")
        self.assertEqual(self.engine.model_name, "gemini-3.8-flash")

    def test_thinking_effort_levels(self):
        self.assertEqual(ThinkingEffortLevel.MINIMAL.value, "minimal")
        self.assertEqual(ThinkingEffortLevel.LOW.value, "low")
        self.assertEqual(ThinkingEffortLevel.MEDIUM.value, "medium")
        self.assertEqual(ThinkingEffortLevel.MAX.value, "max")
        self.assertEqual(ThinkingEffortLevel.HIGH.value, "high")

    def test_build_generate_config_levels(self):
        cfg_med = self.engine._build_generate_config(thinking_effort="medium")
        if cfg_med is not None:
            self.assertTrue(hasattr(cfg_med, "thinking_config"))

        cfg_high = self.engine._build_generate_config(thinking_effort="high")
        if cfg_high is not None:
            self.assertTrue(hasattr(cfg_high, "thinking_config"))

        cfg_json = self.engine._build_generate_config(
            thinking_effort="minimal",
            response_mime_type="application/json"
        )
        if cfg_json is not None:
            self.assertEqual(getattr(cfg_json, "response_mime_type", None), "application/json")

    def test_gemini_calls_pass_config_properly(self):
        from unittest.mock import MagicMock
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "```python\nclass CustomTool:\n    pass\n```"
        mock_client.models.generate_content.return_value = mock_resp

        self.engine.client = mock_client
        self.engine.active_provider = "gemini_api"

        # 1. synthesize_tool_code
        code = self.engine.synthesize_tool_code("自訂工具需求")
        self.assertIn("class CustomTool", code)
        self.assertTrue(mock_client.models.generate_content.called)
        last_kwargs = mock_client.models.generate_content.call_args.kwargs
        self.assertEqual(last_kwargs["model"], "gemini-3.8-flash")
        self.assertIn("config", last_kwargs)

        # 2. decompose_user_demand
        mock_resp.text = "戰術指示：接管輸出"
        res = self.engine.decompose_user_demand("幫我接管操作", GameType.GENSHIN, AssistCapability.GUIDANCE)
        self.assertIn("接管輸出", res)
        last_kwargs = mock_client.models.generate_content.call_args.kwargs
        self.assertEqual(last_kwargs["model"], "gemini-3.8-flash")
        self.assertIn("config", last_kwargs)

        # 3. translate_voice_text
        mock_resp.text = "Help!"
        trans = self.engine.translate_voice_text("救我", target_lang="英文")
        self.assertEqual(trans, "Help!")
        last_kwargs = mock_client.models.generate_content.call_args.kwargs
        self.assertEqual(last_kwargs["model"], "gemini-3.8-flash")
        self.assertIn("config", last_kwargs)


if __name__ == "__main__":
    unittest.main()


