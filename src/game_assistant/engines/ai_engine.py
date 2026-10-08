if __name__ == "__main__" and not __package__:
    import sys
    from pathlib import Path
    _src = str(Path(__file__).resolve().parents[2])
    if _src not in sys.path:
        sys.path.insert(0, _src)

import os
import re
from typing import Optional, Dict, Any, List
from PIL import Image
from google import genai
from google.genai import types
from enum import Enum
from game_assistant.core.config import GEMINI_API_KEY, MODEL_NAME, GameType, AnalysisMode, AssistCapability, PROMPTS
from game_assistant.engines.antigravity_engine import AntigravityCliEngine


class BrainProviderType(str, Enum):
    """大腦推論後端提供者"""
    AUTO = "auto"                              # 自動探測 (優先 agy CLI -> Gemini API -> 離線啟發)
    ANTIGRAVITY_CLI = "antigravity_cli"        # 本機已授權之 Antigravity CLI (免金鑰)
    GEMINI_API = "gemini_api"                  # 遠端 Google Gemini API (需有效 API Key)
    OFFLINE_HEURISTIC = "offline_heuristic"    # 本地離線確定性啟發式戰術庫


class GeminiAuxiliaryEngine:
    """
    Gemini 3.8 Flash / Antigravity CLI 輔助認知引擎 (System 2 - 大腦慢思考)
    作為人類神經系統架構之「大腦」：
    1. 具備多後端 Provider (Antigravity CLI 免金鑰大腦 / Google Gemini SDK / 本地啟發)
    2. 具備思考深度分級 (Thinking Effort):
       - 簡單相似問題: 快速思考 (effort: medium)
       - 從未遇過的新問題: 深度慢思考 (effort: max / Deep Thinking)
    3. 負責將玩家語音/文字需求 (User Demand) 拆解為 Jev 可執行的結構化戰術指令 (Strategy Directive)
    4. 產出滿足 Jev 反射固化需求之結構化記憶特徵
    5. 負責深度多模態視覺畫面剖析與自律工具代碼合成
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: BrainProviderType = BrainProviderType.AUTO,
        antigravity_cli: Optional[AntigravityCliEngine] = None
    ):
        self.api_key = api_key if api_key is not None else GEMINI_API_KEY
        self.model_name = MODEL_NAME
        self.client = None
        self._key_invalid = False
        self.provider_preference = provider
        self.antigravity_cli = antigravity_cli or AntigravityCliEngine()
        self.active_provider = BrainProviderType.OFFLINE_HEURISTIC
        self._init_providers()

    def _init_providers(self):
        self._key_invalid = False
        placeholder_keys = ("", "your_gemini_api_key_here", "your_api_key_here")
        key_val = (self.api_key or "").strip()
        has_valid_key = bool(key_val and key_val not in placeholder_keys)

        if has_valid_key:
            try:
                self.client = genai.Client(api_key=key_val)
            except Exception as e:
                print(f"[GeminiAuxiliaryEngine] Client 初始化異常: {e}")
                self.client = None
        else:
            self.client = None

        # 依據偏好判定作用中大腦 Provider
        if self.provider_preference == BrainProviderType.ANTIGRAVITY_CLI:
            if self.antigravity_cli.is_available():
                self.active_provider = BrainProviderType.ANTIGRAVITY_CLI
            else:
                self.active_provider = BrainProviderType.OFFLINE_HEURISTIC
        elif self.provider_preference == BrainProviderType.GEMINI_API:
            if self.client:
                self.active_provider = BrainProviderType.GEMINI_API
            else:
                self.active_provider = BrainProviderType.OFFLINE_HEURISTIC
        else:
            # AUTO 模式：優先檢查本地已授權 Antigravity CLI，免金鑰即可高智力推論
            if self.antigravity_cli.is_available():
                self.active_provider = BrainProviderType.ANTIGRAVITY_CLI
            elif self.client and not self._key_invalid:
                self.active_provider = BrainProviderType.GEMINI_API
            else:
                self.active_provider = BrainProviderType.OFFLINE_HEURISTIC

    def update_api_key(self, api_key: str):
        """動態更新 API Key"""
        self.api_key = api_key
        self._init_providers()

    def _build_generate_config(
        self,
        thinking_effort: str = "medium",
        response_mime_type: Optional[str] = None,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> Optional[Any]:
        """
        為 Gemini 3.8 Flash 建構 GenerateContentConfig
        原生支援 Gemini 3.x 之語意化 thinking_level (MINIMAL / LOW / MEDIUM / HIGH)
        與結構化輸出 response_mime_type
        """
        config_kwargs: Dict[str, Any] = {}

        if response_mime_type:
            config_kwargs["response_mime_type"] = response_mime_type
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if temperature is not None:
            config_kwargs["temperature"] = temperature

        effort_str = str(thinking_effort).lower()
        if hasattr(types, "ThinkingConfig"):
            try:
                if hasattr(types, "ThinkingLevel"):
                    if effort_str in ("minimal", "off", "none", "zero"):
                        t_level = getattr(types.ThinkingLevel, "MINIMAL", types.ThinkingLevel.LOW)
                    elif effort_str in ("low", "fast"):
                        t_level = types.ThinkingLevel.LOW
                    elif effort_str in ("max", "high", "deep"):
                        t_level = types.ThinkingLevel.HIGH
                    else:
                        t_level = types.ThinkingLevel.MEDIUM
                    config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=t_level)
                else:
                    t_val = "high" if effort_str in ("max", "high", "deep") else ("minimal" if effort_str in ("minimal", "off", "zero") else "medium")
                    config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=t_val)
            except Exception:
                pass

        if config_kwargs and hasattr(types, "GenerateContentConfig"):
            try:
                return types.GenerateContentConfig(**config_kwargs)
            except Exception:
                return None
        return None


    def decompose_user_demand(
        self,
        user_demand: str,
        game_type: GameType,
        capability: AssistCapability,
        image: Optional[Image.Image] = None,
        thinking_effort: str = "medium"
    ) -> str:
        """
        由 Gemini 大腦處理玩家需求，支援思考深度分級 (medium 快速思考 / max 深度思考)
        :param user_demand: 玩家透過語音 (STT) 或文字輸入之需求
        :param game_type: 遊戲類型
        :param capability: 輔助能力
        :param image: 可選畫面截圖
        :param thinking_effort: 'medium' (相似問題快速思考) 或 'max' (新問題深度思考)
        :return: 結構化戰術指導文字
        """
        if not user_demand or not user_demand.strip():
            return ""

        demand_lower = user_demand.lower()

        # 1. 優先使用 Antigravity CLI 大腦推論 (免金鑰通道)
        if self.active_provider == BrainProviderType.ANTIGRAVITY_CLI and not image:
            res = self.antigravity_cli.decompose_user_demand(
                user_demand=user_demand,
                game_type=game_type,
                capability=capability,
                thinking_effort=thinking_effort
            )
            if res:
                return res

        # 2. 備援：Google Gemini SDK 或本地啟發降級
        if not self.client or self._key_invalid:
            return self._fallback_decompose(user_demand, game_type, capability, is_offline=self._key_invalid, thinking_effort=thinking_effort)


        game_name = game_type.value if hasattr(game_type, "value") else str(game_type)
        cap_name = capability.value if hasattr(capability, "value") else str(capability)
        effort_desc = "深度深思 (Deep Thinking)" if thinking_effort == "max" else "敏捷快速思考"
        prompt = (
            f"你是一位頂級遊戲戰術決策專家 (Gemini 3.8 Flash - 大腦認知核心)。\n"
            f"當前遊戲：{game_name}\n"
            f"輔助模式：{cap_name}\n"
            f"思考模式：【{effort_desc}】\n"
            f"玩家提出了具體需求：【{user_demand.strip()}】。\n"
            "【系統實體操作與自律生長能力認知】：\n"
            "你所在的助理系統已具備完整的『自律器官生長器 (OrganSynthesizer)』與『鍵鼠實體致動器 (ScreenActuator)』，能夠即時自律生長出專屬的 Python 操作 Script 宏手並接管操作！\n"
            "嚴禁宣稱『物理終端（手）缺失』或『只有玩家有手』。\n"
            "當玩家要求操作接管、自動戰鬥、執行連招或提問『長出手』時，請提供清晰明確的即時戰術指示 (Directive)，格式規範如下：\n"
            "1. 核心目標 (例如：接管執行連招、核爆終結、極限閃避、大世界自動採集)\n"
            "2. 推薦輸入序列 (明確列出鍵盤與滑鼠序列，如：切 3 號位 -> E -> 普攻 2 次 -> 切 4 號位 -> E -> Q -> 切 1 號位 -> Q)\n"
            "3. 警戒條件 (例如：遇紅光閃避無敵幀頂傷害、技能CD與能量警報)\n"
            "請以繁體中文回答，條點清晰，適合後續手部器官 (DynamicActionScriptHand) 與 Jev 反射神經直接解析執行。"
        )

        try:
            contents = [image, prompt] if image else [prompt]

            # 依據思考深度動態配置 Gemini 3.8 Flash ThinkingConfig (medium vs high)
            gen_config = self._build_generate_config(thinking_effort=thinking_effort)
            call_kwargs = {"model": self.model_name, "contents": contents}
            if gen_config is not None:
                call_kwargs["config"] = gen_config

            response = self.client.models.generate_content(**call_kwargs)
            if response and response.text:
                return response.text.strip()
            return f"戰術目標：因應需求【{user_demand}】執行最佳輸出與防守。"
        except Exception as e:
            err_str = str(e)
            if "API_KEY_INVALID" in err_str or "API key not valid" in err_str or "INVALID_ARGUMENT" in err_str:
                self._key_invalid = True
                print("[GeminiAuxiliaryEngine] 提示：GEMINI_API_KEY 無效或未授權，已自動切換為本地離線啟發式戰術規則庫。請於 .env 配置有效金鑰。")
            else:
                print(f"[GeminiAuxiliaryEngine] decompose_user_demand 異常: {e}")
            return self._fallback_decompose(user_demand, game_type, capability, is_offline=True, thinking_effort=thinking_effort)

    def _fallback_decompose(
        self,
        user_demand: str,
        game_type: GameType,
        capability: AssistCapability,
        is_offline: bool = False,
        thinking_effort: str = "medium"
    ) -> str:
        demand_lower = user_demand.lower()
        game_str = game_type.value if hasattr(game_type, "value") else str(game_type)
        effort_tag = "深度慢思考" if thinking_effort == "max" else "敏捷快速思考"

        # 1. 優先匹配：長出手 / 操作接管 / 連招 / 幫我打
        if any(kw in user_demand for kw in ["長手", "長出手", "生長手", "接管", "幫我打", "連招", "代打", "操作", "核爆"]):
            res = (
                f"【大腦戰術指示 ({effort_tag}) - {game_str}】：\n"
                f"1. 核心目標：自律生長操作手腳本，接管戰術輸出\n"
                f"2. 推薦輸入序列：\n"
                f"切 3 號位 ➔ E 施放戰技 ➔ 普攻 2 次\n"
                f"切 4 號位 ➔ E 施放戰技 ➔ Q 施放大招\n"
                f"切 2 號位 ➔ E 輔助增益\n"
                f"切 1 號位 ➔ Q 元素爆發融化核爆 ➔ 長按 E 進入輸出 ➔ 連續普攻\n"
                f"3. 警戒條件：鎖定敵方攻擊前搖紅光，危險時以大招無敵幀頂掉傷害，夜魂與能量耗盡立即換人循環"
            )
        elif "閃避" in user_demand or "dodge" in demand_lower or "紅光" in user_demand or "危險" in user_demand:
            res = (
                f"【大腦戰術指示 ({effort_tag}) - {game_str}】：\n"
                f"1. 核心目標：極限閃避防禦\n"
                f"2. 推薦操作：抓準攻擊前搖無敵幀，立即按下 Shift / 右鍵\n"
                f"3. 警戒條件：鎖定敵方紅光或紅圈警示"
            )
        elif "招架" in user_demand or "parry" in demand_lower or "黃光" in user_demand:
            res = (
                f"【大腦戰術指示 ({effort_tag}) - {game_str}】：\n"
                f"1. 核心目標：極限招架反擊\n"
                f"2. 推薦操作：敵方閃黃光瞬間按下 Space / C 觸發支援突擊\n"
                f"3. 警戒條件：失衡積蓄最大化"
            )
        elif "大招" in user_demand or "終結技" in user_demand or "burst" in demand_lower or "ult" in demand_lower:
            res = (
                f"【大腦戰術指示 ({effort_tag}) - {game_str}】：\n"
                f"1. 核心目標：終結技/大招爆發破韌\n"
                f"2. 推薦操作：按下 1-4 號位大招或 Q 鍵進行立即插隊輸出\n"
                f"3. 警戒條件：確認敵方處於弱點或失衡易傷狀態"
            )
        elif "反應" in user_demand or "元素" in user_demand or "蒸發" in user_demand or "融化" in user_demand:
            res = (
                f"【大腦戰術指示 ({effort_tag}) - {game_str}】：\n"
                f"1. 核心目標：元素反應增傷鏈\n"
                f"2. 推薦操作：切換 2 號位掛水/火/雷 ➔ 切回 1 號位主 C 施放戰技 E 與平 A\n"
                f"3. 警戒條件：維持元素附著覆蓋"
            )
        elif any(kw in user_demand for kw in ["探索", "採集", "寶箱", "撲滿", "神瞳", "卡格車", "解謎", "撿"]):
            res = (
                f"【大腦探索與採集指示 ({effort_tag}) - {game_str}】：\n"
                f"1. 核心目標：大世界珍貴物資全收集與地圖解謎\n"
                f"2. 推薦操作：靠近目標標記按 【F】 互動拾取；若遇撲滿立即施放秘技先手開怪\n"
                f"3. 警戒條件：關注迷你地圖特產標記與高低差神瞳"
            )
        elif any(kw in user_demand for kw in ["裝備", "強化", "聖遺物", "遺器", "光碟", "詞條", "雙暴", "調律", "洗練"]):
            res = (
                f"【大腦裝備與強化分析指示 ({effort_tag}) - {game_str}】：\n"
                f"1. 核心目標：主副詞條精準評分與強化及時停損\n"
                f"2. 推薦操作：極品雙暴胚子立即【上鎖】；詞條歪斜立即【停損做狗糧/拆解】；稀缺部位考慮自塑塵脂定向\n"
                f"3. 警戒條件：關注 134 速度閾值與雙暴 1:2 配比"
            )
        elif "分析" in user_demand or "資料" in user_demand:
            res = (
                f"【大腦戰術指示 ({effort_tag}) - {game_str}】：\n"
                f"1. 核心目標：戰鬥遙測與資源分析\n"
                f"2. 推薦操作：統計威脅度與 SP/能量循環\n"
                f"3. 警戒條件：監控血量低於 30% 與戰技點耗盡"
            )
        else:
            res = (
                f"【大腦戰術指示 ({effort_tag}) - {game_str}】：\n"
                f"1. 核心目標：因應需求「{user_demand}」維持最佳攻防\n"
                f"2. 推薦操作：技能 E/Q 冷卻好即施放，穿插普攻壓制\n"
                f"3. 警戒條件：保持拉扯走位，遇危險立即閃避"
            )

        if is_offline or not self.client or self._key_invalid:
            res += "\n\n*(💡 當前為本地離線啟發式戰術；若需啟用 Gemini 3.8 Flash 深度意圖解析，請於 .env 配置有效 GEMINI_API_KEY)*"
        return res

    def evaluate_equipment_screen(
        self,
        image: Image.Image,
        game_type: GameType = GameType.GENSHIN
    ) -> str:
        """
        深度多模態裝備調整與強化分析 (聖遺物 / 遺器 / 驅動光碟 / 泛用裝備)
        """
        if not self.client or self._key_invalid:
            return self._fallback_equipment_analysis(game_type)

        prompt = PROMPTS.get(game_type, {}).get(
            AnalysisMode.EQUIPMENT_ENHANCE,
            PROMPTS[GameType.GENERAL][AnalysisMode.EQUIPMENT_ENHANCE]
        )
        return self.analyze_screen(image, game_type, AnalysisMode.EQUIPMENT_ENHANCE, custom_prompt=prompt)

    def guide_exploration_screen(
        self,
        image: Image.Image,
        game_type: GameType = GameType.GENSHIN
    ) -> str:
        """
        深度多模態大地圖探索蒐集與解謎指引 (特產 / 寶箱 / 撲滿 / 神瞳 / 卡格車)
        """
        if not self.client or self._key_invalid:
            return self._fallback_exploration_guide(game_type)

        prompt = PROMPTS.get(game_type, {}).get(
            AnalysisMode.EXPLORATION_MAP,
            PROMPTS[GameType.GENERAL][AnalysisMode.EXPLORATION_MAP]
        )
        return self.analyze_screen(image, game_type, AnalysisMode.EXPLORATION_MAP, custom_prompt=prompt)

    def _fallback_equipment_analysis(self, game_type: GameType) -> str:
        game_str = game_type.value if hasattr(game_type, "value") else str(game_type)
        if game_type == GameType.GENSHIN:
            return (
                f"### 🛡️ 《原神》聖遺物數值與強化分析 (本地離線啟發式)\n\n"
                f"- **裝備部位**：理之冠 / 空之杯 / 時之沙\n"
                f"- **詞條評估**：暴擊率 + 暴擊傷害 (CV 雙暴分評級)\n"
                f"- **強化策略**：\n"
                f"  1. 初始 3 詞條胚子建議先升至 **+4** 查看第四條詞條。\n"
                f"  2. 若 +8 連續歪入生命/防禦，建議立即**停損**並作為下一胚子之狗糧經驗。\n"
                f"  3. 雙暴分達 35 分以上之胚子，強烈建議點擊右上角**上鎖**保存！\n\n"
                f"*(💡 配置有效 GEMINI_API_KEY 可啟用多模態全自動文字識別與精確數值換算)*"
            )
        elif game_type == GameType.STAR_RAIL:
            return (
                f"### 🛡️ 《崩壞：星穹鐵道》遺器調整與強化分析 (本地離線啟發式)\n\n"
                f"- **遺器六件套**：四件隧洞 + 兩件位面飾品\n"
                f"- **配速閾值**：建議主力角色追求 **133.4 速度** (首輪 2 動) 或 **160 速度**。\n"
                f"- **強化策略**：\n"
                f"  1. 每 3 級 (+3/+6/+9/+12/+15) 提升一次副詞條。\n"
                f"  2. 「自塑塵脂」極其珍貴，強烈建議優先定向合成**「能量恢復效率連結繩」**或**「屬性傷害位面球」**。\n"
                f"  3. 淘汰之金色遺器建議保留作為 10 合 1 遺器合成殘骸。\n\n"
                f"*(💡 配置有效 GEMINI_API_KEY 可啟用遺器面板視覺直讀)*"
            )
        elif game_type == GameType.ZZZ:
            return (
                f"### 🛡️ 《絕區零》驅動光碟評級與調律分析 (本地離線啟發式)\n\n"
                f"- **光碟槽位**：1-3 號位固定基礎數值，4-6 號位為核心隨機主屬性。\n"
                f"- **調律建議**：\n"
                f"  1. 達到高級調律等級後，使用「調律校音器」鎖定 4 號位雙暴、5 號位穿透率/屬性傷或 6 號位衝擊力/能量回復。\n"
                f"  2. 強化每 3 級副詞條升級，若副詞條嚴重歪斜，建議在唱片店**拆解**換取經驗鍍劑與母盤。\n\n"
                f"*(💡 配置有效 GEMINI_API_KEY 可啟用驅動盤多模態圖像精算)*"
            )
        else:
            return (
                f"### 🛡️ 《{game_str}》裝備數值與強化分析 (本地離線啟發式)\n\n"
                f"- **品質與裝等**：檢視主屬性加成與額外詞條收益。\n"
                f"- **強化策略**：評估強化成本與成功率，性價比低時及時停損或分解回收。\n\n"
                f"*(💡 配置有效 GEMINI_API_KEY 可啟用深度多模態視覺剖析)*"
            )

    def _fallback_exploration_guide(self, game_type: GameType) -> str:
        game_str = game_type.value if hasattr(game_type, "value") else str(game_type)
        if game_type == GameType.GENSHIN:
            return (
                f"### 🧭 《原神》提瓦特大世界探索與採集指引 (本地離線啟發式)\n\n"
                f"- **特產採集**：靠近特產植物或礦石按 【F】 拾取。\n"
                f"- **神瞳與寶箱**：留意小地圖十字星神瞳標記與周遭仙靈座，建議標記已拿點位避免漏網。\n"
                f"- **解謎機關**：元素方碑需切換對應屬性角色進行點亮。\n\n"
                f"*(💡 配置有效 GEMINI_API_KEY 可啟用畫面即時特產標記與跟跑路線)*"
            )
        elif game_type == GameType.STAR_RAIL:
            return (
                f"### 🧭 《崩壞：星穹鐵道》銀河探索指引 (本地離線啟發式)\n\n"
                f"- **次元撲滿**：發現撲滿時請勿直接靠近，應提前切換遠程角色施放【秘技】開戰防止逃跑！\n"
                f"- **戰利品全收集**：地圖上的普通/豐厚/貴重戰利品可獲得豐富星瓊與遺器經驗。\n"
                f"- **大世界資源**：擊破紫瓶補滿全隊秘技點。\n\n"
                f"*(💡 配置有效 GEMINI_API_KEY 可啟用戰利品自動方位識別)*"
            )
        elif game_type == GameType.ZZZ:
            return (
                f"### 🧭 《絕區零》新艾利都街區與空洞探索指引 (本地離線啟發式)\n\n"
                f"- **街區收集**：尋訪六分街角落的「遺失的小卡格車」與「調查協會紀念幣」，靠近按 【F】 拾取。\n"
                f"- **喵吉長官**：完成街區收集後與喵吉長官對話領取頁面印章與菲林。\n"
                f"- **零號空洞**：電視網格優先規劃低侵蝕安全路線，並收集流派專屬鳴徽。\n\n"
                f"*(💡 配置有效 GEMINI_API_KEY 可啟用電視網格最佳路徑規劃)*"
            )
        else:
            return (
                f"### 🧭 《{game_str}》地圖物資探索指引 (本地離線啟發式)\n\n"
                f"- **物資收集**：跟隨迷你地圖路標前進，靠近掉落物與寶箱按 【F】 進行互動拾取。\n\n"
                f"*(💡 配置有效 GEMINI_API_KEY 可啟用畫面即時標記與導航路徑)*"
            )

    def analyze_screen(
        self,
        image: Image.Image,
        game_type: GameType,
        mode: AnalysisMode,
        custom_prompt: Optional[str] = None,
        thinking_effort: str = "medium"
    ) -> str:
        """
        深度多模態視覺畫面剖析 (快照分析 F10 / 裝備遺器評估 / 地圖解謎)，支援思考深度分級
        :param image: PIL Image 物件
        :param game_type: 遊戲類型
        :param mode: 分析模式
        :param custom_prompt: 玩家自訂提示詞
        :param thinking_effort: 'medium' (快速思考) 或 'max' (深度思考)
        :return: 深度 Markdown 分析文字
        """
        if not self.client or self._key_invalid:
            if mode == AnalysisMode.EQUIPMENT_ENHANCE:
                return self._fallback_equipment_analysis(game_type)
            elif mode == AnalysisMode.EXPLORATION_MAP:
                return self._fallback_exploration_guide(game_type)
            return "⚠️ **提示**：GEMINI_API_KEY 未設定或無效。Gemini 輔助認知處於離線狀態，Jev 決策核心正依據本地啟發式決策正常運作。"

        if custom_prompt and custom_prompt.strip():
            game_name = game_type.value if hasattr(game_type, "value") else str(game_type)
            effort_text = "深度深思" if thinking_effort == "max" else "快速分析"
            final_prompt = (
                f"玩家提出了關於畫面的具體問題：【{custom_prompt.strip()}】。\n"
                f"思考模式：【{effort_text}】\n"
                f"請結合當前遊戲畫面與遊戲類型 ({game_name})，給出精準且直接的解答與戰術指引。請以繁體中文回答。"
            )
        else:
            final_prompt = PROMPTS.get(game_type, {}).get(
                mode,
                PROMPTS[GameType.GENERAL][AnalysisMode.COMBAT]
            )

        try:
            # 依據思考深度動態配置 Gemini 3.8 Flash ThinkingConfig (medium vs high)
            gen_config = self._build_generate_config(thinking_effort=thinking_effort)
            call_kwargs = {"model": self.model_name, "contents": [image, final_prompt]}
            if gen_config is not None:
                call_kwargs["config"] = gen_config

            response = self.client.models.generate_content(**call_kwargs)
            if response and response.text:
                return response.text
            return "⚠️ Gemini 輔助認知未返回文字結果。"
        except Exception as e:
            err_str = str(e)
            if "API_KEY_INVALID" in err_str or "API key not valid" in err_str or "INVALID_ARGUMENT" in err_str:
                self._key_invalid = True
                print("[GeminiAuxiliaryEngine] 提示：GEMINI_API_KEY 無效或未授權，已自動切換為離線狀態。")
                if mode == AnalysisMode.EQUIPMENT_ENHANCE:
                    return self._fallback_equipment_analysis(game_type)
                elif mode == AnalysisMode.EXPLORATION_MAP:
                    return self._fallback_exploration_guide(game_type)
                return "⚠️ **提示**：GEMINI_API_KEY 無效或未授權。請檢查 .env 設定。"
            if mode == AnalysisMode.EQUIPMENT_ENHANCE:
                return self._fallback_equipment_analysis(game_type)
            elif mode == AnalysisMode.EXPLORATION_MAP:
                return self._fallback_exploration_guide(game_type)
            return f"❌ **Gemini 輔助認知分析異常**：\n```\n{str(e)}\n```"

    def translate_screen(
        self,
        image: Image.Image,
        game_type: GameType = GameType.GENERAL,
        target_lang: str = "繁體中文"
    ) -> str:
        """
        外文遊戲畫面多模態視覺翻譯
        擷取遊戲畫面，識別畫面外文 UI、按鈕、劇情對話與任務並翻譯為目標語言 (預設繁中)
        :param image: PIL 截圖
        :param game_type: 遊戲類型
        :param target_lang: 目標語言
        :return: 結構化 Markdown 翻譯對照報告
        """
        if not self.client or self._key_invalid:
            return self._fallback_screen_translation(game_type, target_lang)

        prompt = (
            f"你是一位頂尖的多國語言遊戲在地化與介面視覺翻譯大師。\n"
            f"請深度解析這張外文遊戲畫面，將畫面中的所有外語（英文、日文、韓文、俄文等）徹底翻譯為【{target_lang}（台灣）】。\n\n"
            "請嚴格依據以下結構化格式清晰輸出：\n\n"
            "### 🌐 遊戲畫面外文翻譯報告\n\n"
            "#### 1. 🖥️ 介面與選單對照 (UI & Navigation)\n"
            "| 原始外文 | 繁體中文翻譯 | 功能說明/對應位置 |\n"
            "| :--- | :--- | :--- |\n"
            "| [原文] | [繁中翻譯] | [位置說明] |\n\n"
            "#### 2. 📜 任務與劇情字幕 (Quest & Dialogue)\n"
            "- **說話者/標題**：`[原文]` ➔ **[繁中翻譯]**\n\n"
            "#### 3. 💬 聊天與玩家互動 (Chat & Subtitles)\n"
            "- **[發言者]**：`[原文]` ➔ **[繁中翻譯]**\n\n"
            "#### 4. 💡 即時操作指引\n"
            "- [下一步建議或快捷鍵提醒]\n\n"
            "若畫面中存在對話字幕、NPC台詞或玩家聊天發言，請務必在文末附帶標準 JSON 區塊供系統即時浮動輸出：\n"
            "```json\n"
            "[\n"
            '  {"sender": "說話者", "original": "外文原文", "translated": "繁中翻譯"}\n'
            "]\n"
            "```\n\n"
            "請使用流暢易讀的繁體中文，格式條點美觀，適合玩家即時查閱。"
        )

        try:
            gen_config = self._build_generate_config(thinking_effort="low")
            call_kwargs = {"model": self.model_name, "contents": [image, prompt]}
            if gen_config is not None:
                call_kwargs["config"] = gen_config

            response = self.client.models.generate_content(**call_kwargs)
            if response and response.text:
                return response.text.strip()
            return "⚠️ Gemini 畫面翻譯未返回內容。"
        except Exception as e:
            err_str = str(e)
            if "API_KEY_INVALID" in err_str or "API key not valid" in err_str or "INVALID_ARGUMENT" in err_str:
                self._key_invalid = True
                print("[GeminiAuxiliaryEngine] 提示：GEMINI_API_KEY 無效或未授權，已自動切換為本地離線翻譯對照庫。")
            else:
                print(f"[GeminiAuxiliaryEngine] translate_screen 異常: {e}")
            return self._fallback_screen_translation(game_type, target_lang)

    def translate_chat_subtitles(
        self,
        image: Image.Image,
        game_type: GameType = GameType.GENERAL,
        target_lang: str = "繁體中文"
    ) -> tuple[str, list[dict]]:
        """
        專注於遊戲對話字幕與聊天訊息之多模態識別與即時翻譯
        :param image: PIL 截圖
        :param game_type: 遊戲類型
        :param target_lang: 目標語言
        :return: (markdown_report, list_of_subtitle_items)
        """
        if not self.client or self._key_invalid:
            return self._fallback_chat_subtitles(target_lang)

        prompt = (
            f"你是一位遊戲語音字幕與聊天框即時翻譯助手。\n"
            f"請聚焦辨識畫面中的「對話字幕 (Subtitles)」或「玩家文字聊天框 (Chat Box)」的外文內容，並翻譯為【{target_lang}】。\n"
            "請在輸出末尾附帶標準 JSON 格式區塊，供系統在遊戲上方浮動輸出翻譯字幕：\n"
            "```json\n"
            "[\n"
            '  {"sender": "玩家或NPC名稱", "original": "外文原文", "translated": "繁中翻譯"}\n'
            "]\n"
            "```\n"
            "前文請用清晰的 Markdown 對照輸出。"
        )

        try:
            gen_config = self._build_generate_config(thinking_effort="minimal")
            call_kwargs = {"model": self.model_name, "contents": [image, prompt]}
            if gen_config is not None:
                call_kwargs["config"] = gen_config

            response = self.client.models.generate_content(**call_kwargs)
            text = response.text.strip() if response and response.text else ""
            if not text:
                return self._fallback_chat_subtitles(target_lang)

            subtitles = self._extract_subtitles_from_json(text)
            return text, subtitles
        except Exception as e:
            err_str = str(e)
            if "API_KEY_INVALID" in err_str or "API key not valid" in err_str or "INVALID_ARGUMENT" in err_str:
                self._key_invalid = True
                print("[GeminiAuxiliaryEngine] 提示：GEMINI_API_KEY 無效或未授權，已自動切換為離線狀態。")
            else:
                print(f"[GeminiAuxiliaryEngine] translate_chat_subtitles 異常: {e}")
            return self._fallback_chat_subtitles(target_lang)

    def translate_voice_text(
        self,
        chinese_text: str,
        target_lang: str = "英文"
    ) -> str:
        """
        將玩家的中文語音文字（STT 辨識結果）翻譯為目標外語，供自動輸入至遊戲文字聊天框
        :param chinese_text: 繁體中文文字
        :param target_lang: 目標語言 (如 '英文', '日文', '韓文', '俄文')
        :return: 翻譯後的目標外語文字 (直接可用於聊天發言)
        """
        if not chinese_text or not chinese_text.strip():
            return ""

        if not self.client or self._key_invalid:
            return self._fallback_voice_translation(chinese_text, target_lang)

        prompt = (
            f"你是一位專業的多人線上遊戲隊伍對話翻譯員。\n"
            f"請將玩家說的繁體中文：【{chinese_text.strip()}】精確翻譯為符合線上遊戲玩家慣用溝通的【{target_lang}】。\n"
            "【嚴格規定】：\n"
            "1. 僅返回翻譯後的純文字字串，絕對不要包含引號、解釋、音標或任何多餘文字。\n"
            "2. 語氣自然、簡短有力，符合遊戲隊伍報點、戰術配合與社交打招呼習慣。"
        )

        try:
            gen_config = self._build_generate_config(
                thinking_effort="minimal",
                temperature=0.1
            )
            call_kwargs = {"model": self.model_name, "contents": [prompt]}
            if gen_config is not None:
                call_kwargs["config"] = gen_config

            response = self.client.models.generate_content(**call_kwargs)
            if response and response.text:
                clean_text = response.text.strip().strip('"\'`')
                return clean_text
            return self._fallback_voice_translation(chinese_text, target_lang)
        except Exception as e:
            err_str = str(e)
            if "API_KEY_INVALID" in err_str or "API key not valid" in err_str or "INVALID_ARGUMENT" in err_str:
                self._key_invalid = True
                print("[GeminiAuxiliaryEngine] 提示：GEMINI_API_KEY 無效或未授權，已自動切換為本地離線詞典對照。")
            else:
                print(f"[GeminiAuxiliaryEngine] translate_voice_text 異常: {e}")
            return self._fallback_voice_translation(chinese_text, target_lang)

    def _extract_subtitles_from_json(self, text: str) -> list[dict]:
        """
        從 AI 產生的輸出中高容錯抽取字幕列表 (支援 JSON 區塊、原始 JSON 與 Markdown 正則降級)
        """
        import json
        import re

        # 1. 優先嘗試由 Markdown 代碼區塊提取 (容許帶或不帶 json 語言標註)
        code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if code_block_match:
            try:
                data = json.loads(code_block_match.group(1).strip())
                if isinstance(data, list):
                    return [x for x in data if isinstance(x, dict)]
                elif isinstance(data, dict):
                    for k in ("subtitles", "dialogues", "chat", "items", "messages"):
                        if isinstance(data.get(k), list):
                            return [x for x in data[k] if isinstance(x, dict)]
                    if "original" in data or "translated" in data:
                        return [data]
            except Exception:
                pass

        # 2. 嘗試直接在文本中匹配原始 JSON 陣列模式 [...]
        raw_array_match = re.search(r'\[\s*\{[\s\S]*?\}\s*\]', text)
        if raw_array_match:
            try:
                data = json.loads(raw_array_match.group(0).strip())
                if isinstance(data, list):
                    return [x for x in data if isinstance(x, dict)]
            except Exception:
                pass

        # 3. 若無可用 JSON，以結構化規則解析 Markdown 對話/字幕行
        subtitles = []
        for line in text.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("|") or line_str.startswith("#"):
                continue

            if "➔" in line_str or "->" in line_str:
                parts = re.split(r'➔|->', line_str, maxsplit=1)
                if len(parts) == 2:
                    left_raw = parts[0].strip(" -*`#")
                    right_raw = parts[1].strip(" -*`#【】")

                    # 解析發言者與原文
                    sender = "對話"
                    orig_text = left_raw
                    # 匹配 - **發言者**：原文 或 [發言者]: 原文
                    prefix_match = re.match(r'^(?:\[([^\]]+)\]|\*\*([^*]+)\*\*|([^：:]+))[：:]\s*(.*)$', left_raw)
                    if prefix_match:
                        s_cand = prefix_match.group(1) or prefix_match.group(2) or prefix_match.group(3)
                        remainder = prefix_match.group(4)
                        if s_cand and remainder:
                            sender = s_cand.strip(" *#`")
                            orig_text = remainder.strip(" `*\'\"[]")

                    orig_clean = orig_text.strip(" `*\'\"[]")
                    trans_clean = right_raw.strip(" `*\'\"【】")
                    if orig_clean and trans_clean:
                        subtitles.append({
                            "sender": sender,
                            "original": orig_clean,
                            "translated": trans_clean
                        })
        return subtitles

    def _fallback_screen_translation(self, game_type: GameType, target_lang: str) -> str:
        game_name = game_type.value if hasattr(game_type, "value") else str(game_type)
        return (
            f"### 🌐 遊戲畫面外文翻譯 (離線對照模式)\n\n"
            f"> ℹ️ *當前處於離線確定性對照模式（未檢測到有效 Gemini API Key）。以下提供通用介面與常見外文對照表。*\n\n"
            f"**當前遊戲**：`{game_name}` | **目標語言**：`{target_lang}`\n\n"
            f"#### 1. 🖥️ 介面與選單對照 (UI & Navigation)\n"
            f"| 原始外文 | 繁體中文翻譯 | 功能說明/對應位置 |\n"
            f"| :--- | :--- | :--- |\n"
            f"| **Settings / Options** | **系統設定** | 畫面/音效/操作鍵位配置 |\n"
            f"| **Inventory / Bag** | **背包 / 道具欄** | 裝備、聖遺物與消耗品清單 |\n"
            f"| **Quest Log / Missions** | **任務日誌** | 主線/支線/每日委託追蹤 |\n"
            f"| **Party / Team Setup** | **隊伍配置** | 角色編隊與切換出戰陣容 |\n"
            f"| **Character / Agent** | **角色面板** | 屬性數值、天賦與技能升級 |\n"
            f"| **Confirm / OK** | **確認 / 確定** | 確定當前操作 |\n"
            f"| **Cancel / Back** | **取消 / 返回** | 關閉或返回上一層介面 |\n\n"
            f"#### 2. 📜 劇情與字幕對話 (Subtitles)\n"
            f"- **System / NPC**：`[Attention! Danger ahead]` ➔ **【警告！前方有危險】**\n\n"
            f"#### 3. 💬 聊天室訊息 (Chat)\n"
            f"- **Teammate**：`[Group up here, let's fight together!]` ➔ **【在這邊集合，一起打！】**\n\n"
            f"```json\n"
            f"[\n"
            f'  {{"sender": "System / NPC", "original": "Attention! Danger ahead", "translated": "警告！前方有危險"}},\n'
            f'  {{"sender": "Teammate", "original": "Group up here, let\'s fight together!", "translated": "在這邊集合，一起打！"}}\n'
            f"]\n"
            f"```\n\n"
            f"💡 **提示**：配置 `GEMINI_API_KEY` 後即可啟動 Gemini 3.8 Flash 實時多模態視覺多國語言完整翻譯。"
        )

    def _fallback_chat_subtitles(self, target_lang: str) -> tuple[str, list[dict]]:
        report = (
            "### 💬 遊戲字幕與對話即時翻譯\n\n"
            "- **NPC / 隊友**：`Watch out! The boss is entering phase 2.` ➔ **【注意！Boss 進入第二階段！】**\n"
            "- **Team**：`Need backup at point A!` ➔ **【A 點需要支援！】**\n"
        )
        subtitles = [
            {
                "sender": "NPC / 隊友",
                "original": "Watch out! The boss is entering phase 2.",
                "translated": "注意！Boss 進入第二階段！"
            },
            {
                "sender": "Team",
                "original": "Need backup at point A!",
                "translated": "A 點需要支援！"
            }
        ]
        return report, subtitles

    def _fallback_voice_translation(self, chinese_text: str, target_lang: str) -> str:
        txt = chinese_text.strip().lower()

        # 針對不同目標外語（英文 / 日文 / 韓文 / 俄文）之遊戲溝通本地字典
        vocab_en = {
            "救我": "Help me!", "救一下": "Help me please!", "救命": "Help!",
            "快跑": "Run! / Retreat!", "快撤": "Fall back!", "撤退": "Retreat!",
            "集合": "Group up here!", "過來": "Come here!", "來這裡": "Gather here!",
            "打boss": "Let's attack the boss!", "打王": "Focus the boss!",
            "開大": "Use your ultimate!", "大招好了": "My ultimate is ready!",
            "漂亮": "Nice play!", "打得好": "Good job!",
            "好的": "OK / Got it!", "收到": "Roger that!",
            "謝謝": "Thanks! / GG!", "多謝": "Thank you!", "感謝": "Thank you so much! GG!",
            "我是台灣人": "I am from Taiwan, nice to meet you!",
            "有人嗎": "Anyone here?", "走這裡": "This way!",
            "注意閃避": "Watch out! Dodge!", "小心": "Be careful!",
            "你好": "Hello everyone!", "哈囉": "Hi there!",
            "加油": "Let's do this!", "稍等": "Wait a moment please.", "等我一下": "Wait for me please."
        }

        vocab_ja = {
            "救我": "助けて！", "救一下": "助けてください！", "救命": "助けて！",
            "快跑": "逃げて！", "快撤": "引いて！", "撤退": "撤退！",
            "集合": "集合！", "過來": "こっちに来て！", "來這裡": "ここに集まって！",
            "打boss": "ボスを集中攻撃！", "打王": "ボスを狙って！",
            "開大": "ウルト使って！", "大招好了": "必殺技準備完了！",
            "漂亮": "ナイス！", "打得好": "ナイスプレイ！",
            "好的": "了解！", "收到": "了解です！",
            "謝謝": "ありがとう！ GG！", "多謝": "どうも！", "感謝": "ありがとうございます！",
            "我是台灣人": "台湾から来ました、よろしくお願いします！",
            "有人嗎": "誰かいますか？", "走這裡": "こっちです！",
            "注意閃避": "気をつけて！回避！", "小心": "注意してください！",
            "你好": "こんにちは！", "哈囉": "やあ！",
            "加油": "頑張りましょう！", "稍等": "ちょっと待って！", "等我一下": "待ってください！"
        }

        vocab_ko = {
            "救我": "살려주세요!", "救一下": "도와주세요!", "救命": "살려줘요!",
            "快跑": "도망쳐요!", "快撤": "후퇴해요!", "撤退": "후퇴!",
            "集合": "모여주세요!", "過來": "이쪽으로 와요!", "來這裡": "여기 모여요!",
            "打boss": "보스 점사해요!", "打王": "보스 집중 공격!",
            "開大": "궁극기 써주세요!", "大招好了": "궁극기 준비 완료!",
            "漂亮": "나이스!", "打得好": "잘했어요!",
            "好的": "확인!", "收到": "알겠습니다!",
            "謝謝": "감사합니다! GG!", "多謝": "고마워요!", "感謝": "정말 감사합니다!",
            "我是台灣人": "대만에서 왔습니다, 잘 부탁드립니다!",
            "有人嗎": "누구 계신가요?", "走這裡": "이쪽이에요!",
            "注意閃避": "조심해요! 회피!", "小心": "조심하세요!",
            "你好": "안녕하세요!", "哈囉": "안녕!",
            "加油": "화이팅!", "稍等": "잠시만요!", "等我一下": "잠시만 기다려주세요!"
        }

        vocab_ru = {
            "救我": "Помогите!", "救一下": "Помогите, пожалуйста!", "救命": "Спасите!",
            "快跑": "Бегите!", "快撤": "Назад!", "撤退": "Отступаем!",
            "集合": "Собираемся здесь!", "過來": "Сюда!", "來這裡": "Идите сюда!",
            "打boss": "Атакуем босса!", "打王": "Фокусите босса!",
            "開大": "Используй ульту!", "大招好了": "Ульта готова!",
            "漂亮": "Отлично!", "打得好": "Хорошая игра!",
            "好的": "Хорошо!", "收到": "Принято!",
            "謝謝": "Спасибо! GG!", "多謝": "Благодарю!", "感謝": "Большое спасибо!",
            "我是台灣人": "Я из Тайваня, приятно познакомиться!",
            "有人嗎": "Есть кто?", "走這裡": "Сюда!",
            "注意閃避": "Осторожно! Уворачивайтесь!", "小心": "Осторожно!",
            "你好": "Всем привет!", "哈囉": "Привет!",
            "加油": "Вперёд!", "稍等": "Минутку.", "等我一下": "Подождите меня."
        }

        if "日" in target_lang:
            target_dict = vocab_ja
            prefix = "[日文]"
        elif "韓" in target_lang:
            target_dict = vocab_ko
            prefix = "[韓文]"
        elif "俄" in target_lang:
            target_dict = vocab_ru
            prefix = "[Русский]"
        else:
            target_dict = vocab_en
            prefix = "[Chat]"

        for k, v in target_dict.items():
            if k in txt:
                return v

        return f"{prefix}: {chinese_text}"

    def extract_reflex_schema_from_directive(
        self,
        directive: str,
        user_demand: str = "",
        game_type: GameType = GameType.GENERAL
    ) -> Dict[str, Any]:
        """
        從 Gemini 大腦產出之戰術指示中，結構化提煉供 Jev 反射固化之要素：
        - primary_action: 萃取核心動作
        - guidance_text: 萃取建議指引文字
        - keywords: 關鍵字觸發詞
        - suggested_questions: 供 Jev Choice/Noul/Score 固化之結構
        """
        text_lower = f"{directive} {user_demand}".lower()

        action = "idle"
        if "閃避" in directive or "dodge" in text_lower or "紅光" in text_lower:
            action = "dash_dodge"
        elif "招架" in directive or "parry" in text_lower or "黃光" in text_lower:
            action = "parry_assist_space"
        elif "大招" in directive or "終結技" in directive or "burst" in text_lower:
            action = "burst_q"
        elif "戰技" in directive or "放e" in text_lower or "skill_e" in text_lower or "技能 e" in text_lower:
            action = "skill_e"
        elif "普攻" in directive or "平a" in text_lower or "normal_attack" in text_lower:
            action = "normal_attack"
        elif "治療" in directive or "補血" in directive or "回血" in directive:
            action = "heal"
        elif "4 號位" in directive or "四號位" in directive:
            action = "switch_4"
        elif "3 號位" in directive or "三號位" in directive:
            action = "switch_3"
        elif "反應" in directive or "元素" in directive or "切換" in directive or "2 號位" in directive or "二號位" in directive:
            action = "switch_2"
        elif "寶箱" in directive or "拾取" in directive or "採集" in directive:
            action = "open_chest"
        elif "神瞳" in directive:
            action = "collect_oculus"
        elif "解謎" in directive or "方碑" in directive or "機關" in directive:
            action = "solve_puzzle"
        elif "上鎖" in directive or "保留" in directive:
            action = "lock_and_keep"
        elif "停損" in directive or "做狗糧" in directive or "拆解" in directive:
            action = "stop_and_salvage"
        elif "自塑塵脂" in directive:
            action = "craft_with_resin"
        elif "校音器" in directive:
            action = "tune_with_calibrator"

        keywords = []
        for kw in [
            "紅光", "黃光", "危險", "前搖", "閃避", "招架", "大招", "終結技", "元素反應",
            "蒸發", "融化", "超導", "感電", "破盾", "戰技", "普攻", "治療", "寶箱", "採集",
            "神瞳", "撲滿", "雙暴", "上鎖", "停損", "自塑塵脂", "校音器", "方碑", "解謎"
        ]:
            if kw in directive or kw in user_demand:
                keywords.append(kw)

        # 尋找推薦操作或主要指示行
        guidance = ""
        for line in directive.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            if "推薦操作" in line_str or "推薦" in line_str:
                guidance = re.sub(r'^\d+[\.、]\s*', '', line_str).strip()
                break
            elif "核心目標" in line_str and not guidance:
                guidance = re.sub(r'^\d+[\.、]\s*', '', line_str).strip()

        if not guidance:
            non_headers = [l.strip() for l in directive.splitlines() if l.strip() and not l.strip().startswith("【") and not l.strip().startswith("#")]
            if non_headers:
                guidance = non_headers[0]
            else:
                first_line = directive.splitlines()[0] if directive.splitlines() else directive
                guidance = first_line.strip("【】*-# ")

        return {
            "primary_action": action,
            "guidance_text": guidance,
            "keywords": keywords,
            "suggested_questions": {
                "tactical_action": {
                    "type": "choice",
                    "instructions": f"評估針對場景的最佳動作",
                    "options": [action, "idle"]
                },
                "should_act": {
                    "type": "noul",
                    "instructions": f"是否立即執行 {action}？"
                },
                "urgency": {
                    "type": "score",
                    "instructions": f"此動作之緊迫程度",
                    "criteria": ["低", "中", "高"]
                }
            }
        }

    def synthesize_tool_code(
        self,
        tool_spec: str,
        game_type: Optional[GameType] = None,
        context_info: str = ""
    ) -> Optional[str]:
        """
        透過大腦 (Antigravity CLI / Gemini) 自主編寫 Python 工具代碼
        """
        if self.active_provider == BrainProviderType.ANTIGRAVITY_CLI:
            return self.antigravity_cli.synthesize_tool_code(tool_spec, game_type, context_info)
        elif self.client and not self._key_invalid:
            try:
                game_str = game_type.value if game_type and hasattr(game_type, "value") else str(game_type or "泛用遊戲")
                prompt = (
                    "你是一位頂尖的 Python 遊戲周邊工具架構師。\n"
                    f"目標遊戲：{game_str}\n"
                    f"工具規格需求：\n{tool_spec}\n"
                    f"周邊上下文：\n{context_info}\n\n"
                    "請為遊戲助理自主生長一個合規的 Python 工具模組代碼。\n"
                    "只輸出純 Python 代碼區塊 (使用 ```python ... ``` 包裹)。"
                )
                gen_config = self._build_generate_config(
                    thinking_effort="high",
                    temperature=0.2
                )
                call_kwargs = {"model": self.model_name, "contents": [prompt]}
                if gen_config is not None:
                    call_kwargs["config"] = gen_config
                resp = self.client.models.generate_content(**call_kwargs)
                if resp and resp.text:
                    return resp.text.strip()
            except Exception:
                pass
        return None



# 向下相容別名
GeminiAIEngine = GeminiAuxiliaryEngine


if __name__ == "__main__":
    engine = GeminiAuxiliaryEngine()
    print("Gemini 3.8 Flash Auxiliary Engine Initialized. Key present:", bool(engine.api_key))
    print("離線語音翻譯測試 ('救我'):", engine.translate_voice_text("救我", target_lang="英文"))

