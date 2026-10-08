import os
import json
import time
import re
import threading
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List, Tuple

from game_assistant.core.config import (
    GameType, AssistCapability,
    REFLEX_CONFIDENCE_THRESHOLD, NOVELTY_SIMILARITY_THRESHOLD,
    MIN_MEMORIES_TO_CONSOLIDATE, MEMORY_STORE_PATH, REFLEX_ARCS_PATH
)
from game_assistant.engines.jev_engine import (
    Choice, Noul, Score, JevDecisionEngine, JevResponse,
    ChoiceResult, NoulResult, ScoreResult
)
from game_assistant.strategies.base import (
    TelemetryData, StrategyDecision, ActionResult
)
from game_assistant.core.memory_index import (
    HierarchicalMemoryIndex, JevMemoryRouter, MemoryDomain
)



class NoveltyLevel(str, Enum):
    """問題新穎程度判定"""
    SIMILAR = "similar"  # 簡單相似問題 (已有相關記憶或反射弧)
    NOVEL = "novel"      # 從未遇過的新問題 (無足夠相似記憶)


class ThinkingEffort(str, Enum):
    """Gemini 3.8 Flash 大腦思考深度 (Thinking Effort / Level)"""
    MINIMAL = "minimal"  # 極速思考 (無思考延遲)
    LOW = "low"          # 快速輕量思考
    MEDIUM = "medium"    # 快速思考 (針對簡單相似問題)
    MAX = "max"          # 深度慢思考 (針對未曾遇過的新問題，Deep Thinking)
    HIGH = "high"        # MAX 相容別名


def normalize_game_type(g: Any) -> str:
    """標準化遊戲類型標籤，支援 Enum、字串與中英文縮寫"""
    if not g:
        return ""
    val = g.value if hasattr(g, "value") else str(g)
    val = val.lower()
    if "genshin" in val or "原神" in val:
        return "genshin"
    if "star_rail" in val or "星穹鐵道" in val or "honkai" in val:
        return "star_rail"
    if "zzz" in val or "絕區零" in val or "zenless" in val:
        return "zzz"
    if "general" in val or "泛用" in val:
        return "general"
    return val.split("(")[0].strip()


@dataclass
class ReflexArc:
    """
    Jev 反射弧 (Reflex Arc / System 1 固化神經路徑)
    將先前 Gemini 大腦的思考成果固化為 Jev 可直接處理的：
    1. Input: 觸發特徵關鍵字 (trigger_keywords) 與遙測條件 (trigger_predicates)
    2. Flow: Jev 專屬 Question Schema (Choice, Noul, Score)
    3. Output: 決策映射 (decision_mapping) 與本地確定性預設 (deterministic_output)
    使往後遇到相同或相似情境時，能直接由 Jev 在毫秒級完成反射決策。
    """
    arc_id: str
    name: str
    game_type: str = "ALL"
    trigger_keywords: List[str] = field(default_factory=list)
    trigger_predicates: Dict[str, Any] = field(default_factory=dict)
    questions: Dict[str, Any] = field(default_factory=dict)
    decision_mapping: Dict[str, Any] = field(default_factory=dict)
    deterministic_output: Optional[Dict[str, Any]] = None
    confidence_threshold: float = REFLEX_CONFIDENCE_THRESHOLD
    source_memory_ids: List[str] = field(default_factory=list)
    hit_count: int = 0
    last_fired_at: float = 0.0
    created_at: float = field(default_factory=time.time)

    def matches(
        self,
        state: str,
        telemetry: Optional[TelemetryData] = None,
        user_demand: str = "",
        game_type: Optional[Any] = None
    ) -> bool:
        """
        評估當前狀態是否匹配此反射弧之輸入條件
        """
        combined_text = f"{state} {user_demand}".lower()

        # 1. 遊戲類型過濾 (嚴格防禦跨遊戲反射弧誤判)
        if self.game_type != "ALL":
            arc_game = normalize_game_type(self.game_type)
            target_game = None
            if game_type is not None:
                target_game = normalize_game_type(game_type)
            elif telemetry is not None:
                target_game = normalize_game_type(telemetry.game_type)

            if target_game:
                if arc_game != target_game:
                    return False
            else:
                # 若無 telemetry 亦無明確指定遊戲，檢查文字中是否含有衝突的它種遊戲特徵
                known_other_games = ["原神", "星穹鐵道", "絕區零"]
                conflict = any(other.lower() in combined_text for other in known_other_games if other.lower() not in self.game_type.lower())
                if conflict:
                    return False

        # 2. 關鍵字觸發匹配 (若有定義關鍵字，需命中至少一個核心特徵)
        if self.trigger_keywords:
            matched_kw = False
            for kw in self.trigger_keywords:
                kw_str = kw.strip().lower()
                if not kw_str:
                    continue
                # 純英數/熱鍵使用單詞邊界比對，避免子字串誤判 (如 'e' 誤中 'danger_detected')
                if re.match(r'^[a-z0-9_]+$', kw_str):
                    if re.search(r'\b' + re.escape(kw_str) + r'\b', combined_text):
                        matched_kw = True
                        break
                else:
                    if kw_str in combined_text:
                        matched_kw = True
                        break
            if not matched_kw:
                return False

        # 3. 遙測條件判定
        if self.trigger_predicates and telemetry:
            for k, expected_val in self.trigger_predicates.items():
                actual_val = getattr(telemetry, k, None)
                if actual_val is None and isinstance(telemetry.features, dict):
                    actual_val = telemetry.features.get(k)
                if actual_val != expected_val:
                    return False

        return True

    def build_jev_questions(self) -> Dict[str, Any]:
        """產出供 Jev 引擎執行的 Question Schema 物件字典"""
        instantiated = {}
        for q_id, q_def in self.questions.items():
            if isinstance(q_def, (Choice, Noul, Score)):
                instantiated[q_id] = q_def
            elif isinstance(q_def, dict):
                q_type = q_def.get("type", "choice")
                instructions = q_def.get("instructions", "")
                if q_type == "choice":
                    instantiated[q_id] = Choice(
                        instructions=instructions,
                        options=q_def.get("options", []),
                        criteria=q_def.get("criteria", {})
                    )
                elif q_type == "noul":
                    instantiated[q_id] = Noul(
                        instructions=instructions,
                        criteria=q_def.get("criteria")
                    )
                elif q_type == "score":
                    instantiated[q_id] = Score(
                        instructions=instructions,
                        criteria=q_def.get("criteria", [])
                    )
            else:
                instantiated[q_id] = Choice(instructions=str(q_def), options=["default"])
        return instantiated

    def interpret_decision(
        self,
        jev_response: JevResponse,
        telemetry: TelemetryData
    ) -> StrategyDecision:
        """依據 Jev 回應與反射弧規則轉譯為 StrategyDecision"""
        primary_action = "idle"
        confidence = 0.85
        urgency = 0.5
        should_evade = False
        guidance_text = f"⚡ Jev 反射弧觸發：【{self.name}】"

        # 從 Jev 決策中獲取 primary_action
        if "tactical_action" in jev_response.choices:
            c = jev_response.choices["tactical_action"]
            primary_action = c.choice
            confidence = c.confidence
        elif "action" in jev_response.choices:
            c = jev_response.choices["action"]
            primary_action = c.choice
            confidence = c.confidence
        elif self.deterministic_output:
            primary_action = self.deterministic_output.get("primary_action", "idle")
            confidence = self.deterministic_output.get("confidence", 0.9)

        # 判定 should_evade
        if "should_evade" in jev_response.nouls:
            should_evade = bool(jev_response.nouls["should_evade"])
        elif "danger" in jev_response.nouls:
            should_evade = bool(jev_response.nouls["danger"])
        elif self.deterministic_output:
            should_evade = self.deterministic_output.get("should_evade", False)

        # 判定 urgency
        if "combat_urgency" in jev_response.scores:
            urgency = jev_response.scores["combat_urgency"].score
        elif "urgency" in jev_response.scores:
            urgency = jev_response.scores["urgency"].score
        elif self.deterministic_output:
            urgency = self.deterministic_output.get("urgency", 0.5)

        # 映射自定義 guidance
        if primary_action in self.decision_mapping:
            mapping_info = self.decision_mapping[primary_action]
            if isinstance(mapping_info, dict):
                guidance_text = mapping_info.get("guidance", guidance_text)
            elif isinstance(mapping_info, str):
                guidance_text = mapping_info
        elif self.deterministic_output and "guidance_text" in self.deterministic_output:
            guidance_text = self.deterministic_output["guidance_text"]

        return StrategyDecision(
            primary_action=primary_action,
            confidence=confidence,
            urgency=urgency,
            should_evade=should_evade,
            guidance_text=guidance_text,
            telemetry=telemetry,
            raw_jev=jev_response
        )

    def to_dict(self) -> Dict[str, Any]:
        """序列化為字典供保存與日後加載"""
        serialized_questions = {}
        for k, v in self.questions.items():
            if hasattr(v, "to_dict"):
                serialized_questions[k] = v.to_dict()
            elif isinstance(v, dict):
                serialized_questions[k] = v
            else:
                serialized_questions[k] = {"instructions": str(v)}

        return {
            "arc_id": self.arc_id,
            "name": self.name,
            "game_type": self.game_type,
            "trigger_keywords": self.trigger_keywords,
            "trigger_predicates": self.trigger_predicates,
            "questions": serialized_questions,
            "decision_mapping": self.decision_mapping,
            "deterministic_output": self.deterministic_output,
            "confidence_threshold": self.confidence_threshold,
            "source_memory_ids": self.source_memory_ids,
            "hit_count": self.hit_count,
            "last_fired_at": self.last_fired_at,
            "created_at": self.created_at
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ReflexArc":
        return cls(
            arc_id=d.get("arc_id", ""),
            name=d.get("name", ""),
            game_type=d.get("game_type", "ALL"),
            trigger_keywords=d.get("trigger_keywords", []),
            trigger_predicates=d.get("trigger_predicates", {}),
            questions=d.get("questions", {}),
            decision_mapping=d.get("decision_mapping", {}),
            deterministic_output=d.get("deterministic_output"),
            confidence_threshold=d.get("confidence_threshold", REFLEX_CONFIDENCE_THRESHOLD),
            source_memory_ids=d.get("source_memory_ids", []),
            hit_count=d.get("hit_count", 0),
            last_fired_at=d.get("last_fired_at", 0.0),
            created_at=d.get("created_at", time.time())
        )


@dataclass
class MemoryTrace:
    """
    神經突觸記憶痕跡 (Memory Trace)
    每次 Gemini 大腦進行思考（無論 medium 快速思考或 max 深度思考）皆完整保留。
    具備 Jev 固化所需之完整上下文：
    - 輸入狀態與特徵 (user_demand, state_text, telemetry_features)
    - 思考深度與新穎度判定 (thinking_effort, novelty_level)
    - Gemini 戰術指導與解析 (gemini_directive)
    - 提煉之動作與建議 Schema (primary_action, guidance_text, suggested_questions)
    """
    memory_id: str
    timestamp: float
    game_type: str
    user_demand: str
    visual_context: str
    state_text: str
    telemetry_features: Dict[str, Any] = field(default_factory=dict)
    novelty_level: str = "novel"
    thinking_effort: str = "max"
    gemini_directive: str = ""
    primary_action: str = "idle"
    guidance_text: str = ""
    suggested_questions: Dict[str, Any] = field(default_factory=dict)
    is_consolidated: bool = False
    consolidation_arc_id: Optional[str] = None


    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MemoryTrace":
        return cls(
            memory_id=d.get("memory_id", ""),
            timestamp=d.get("timestamp", time.time()),
            game_type=d.get("game_type", ""),
            user_demand=d.get("user_demand", ""),
            visual_context=d.get("visual_context", ""),
            state_text=d.get("state_text", ""),
            telemetry_features=d.get("telemetry_features", {}),
            novelty_level=d.get("novelty_level", "novel"),
            thinking_effort=d.get("thinking_effort", "max"),
            gemini_directive=d.get("gemini_directive", ""),
            primary_action=d.get("primary_action", "idle"),
            guidance_text=d.get("guidance_text", ""),
            suggested_questions=d.get("suggested_questions", {}),
            is_consolidated=d.get("is_consolidated", False),
            consolidation_arc_id=d.get("consolidation_arc_id")
        )


class ReflexMemoryStore:
    """
    神經突觸記憶庫 (Reflex Memory Store)
    執行緒安全儲存所有大腦思考留下的記憶痕跡，支援未固化查詢、檢索與持久化。
    """
    def __init__(self, storage_path: str = MEMORY_STORE_PATH, router: Optional[Any] = None):
        self.storage_path = storage_path
        self._lock = threading.RLock()
        self._traces: List[MemoryTrace] = []
        self._router = router
        self._load_from_disk()

    def set_router(self, router: Any):
        """綁定 Jev 階層式路由器並為現有記憶建立多層索引"""
        with self._lock:
            self._router = router
            for t in self._traces:
                try:
                    self._router.register_trace_auto(t)
                except Exception:
                    pass

    def record_trace(self, trace: MemoryTrace, game_type: Optional[Any] = None, capability: Optional[Any] = None) -> str:
        """紀錄一筆記憶痕跡並自動經由 Jev 路由器登錄多層索引"""
        with self._lock:
            self._traces.append(trace)
            self._save_to_disk()
            if self._router:
                try:
                    self._router.register_trace_auto(trace, game_type=game_type, capability=capability)
                except Exception:
                    pass
            return trace.memory_id

    def get_unconsolidated_traces(self, game_type: Optional[str] = None) -> List[MemoryTrace]:
        """取得尚未固化為反射弧之記憶"""
        with self._lock:
            res = [t for t in self._traces if not t.is_consolidated]
            if game_type:
                res = [t for t in res if t.game_type.lower() == game_type.lower()]
            return list(res)

    def get_all_traces(self) -> List[MemoryTrace]:
        with self._lock:
            return list(self._traces)

    def mark_consolidated(self, trace_ids: List[str], arc_id: str):
        """將指定記憶標記為已固化"""
        with self._lock:
            id_set = set(trace_ids)
            for t in self._traces:
                if t.memory_id in id_set:
                    t.is_consolidated = True
                    t.consolidation_arc_id = arc_id
            self._save_to_disk()

    def clear(self):
        """清空記憶 (用於測試或系統重置)"""
        with self._lock:
            self._traces.clear()
            self._save_to_disk()
            if self._router and hasattr(self._router, "index") and hasattr(self._router.index, "clear"):
                try:
                    self._router.index.clear()
                except Exception:
                    pass


    def _save_to_disk(self):
        """持久化保存至相對路徑檔案 (原子寫入防禦)"""
        try:
            target_dir = os.path.dirname(self.storage_path)
            if target_dir and not os.path.exists(target_dir):
                os.makedirs(target_dir, exist_ok=True)
            data = [t.to_dict() for t in self._traces]
            tmp_path = f"{self.storage_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.storage_path)
        except Exception:
            # 檔案寫入異常防禦（如受限環境下不崩潰）
            pass

    def _load_from_disk(self):
        """從相對路徑讀取已保存之記憶"""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._traces = [MemoryTrace.from_dict(item) for item in data]
            except Exception:
                self._traces = []


class NoveltyDetector:
    """
    新穎性與相似度評估器 (Novelty & Similarity Evaluator)
    用於決定 Gemini 大腦之思考深度 (Thinking Effort):
    - 簡單相似問題 (SIMILAR, >= 閾值) -> Gemini effort MEDIUM (快速思考)
    - 從未遇過的新問題 (NOVEL, < 閾值) -> Gemini effort MAX (深度慢思考, Deep Thinking)
    """

    def __init__(self, similarity_threshold: float = NOVELTY_SIMILARITY_THRESHOLD):
        self.similarity_threshold = similarity_threshold

    def tokenize(self, text: str) -> set[str]:
        """
        高容錯中英雙語與遊戲熱鍵特徵分詞：
        - 英文關鍵字 (shift, space, boss, dodge, parry, burst, ult...)
        - 遊戲按鍵與槽位 (q, e, f, r, c, z, 1, 2, 3, 4)
        - 中文字元、單字與二元/三元滑動視窗 (閃避, 招架, 破盾, 元素反應...)
        """
        if not text:
            return set()
        words = set()
        text_lower = text.lower()

        # 1. 抽取英數字詞與重要遊戲熱鍵
        alphanumeric_tokens = re.findall(r'[a-z0-9]+', text_lower)
        valid_single_keys = {'q', 'e', 'f', 'r', 'c', 'z', '1', '2', '3', '4'}
        for term in alphanumeric_tokens:
            if len(term) >= 2 or term in valid_single_keys:
                words.add(term)

        # 2. 抽取中文連續區塊並建立單字 (1-gram) 與二元滑動視窗 (2-gram)
        cjk_chunks = re.findall(r'[\u4e00-\u9fff]+', text)
        for chunk in cjk_chunks:
            c_len = len(chunk)
            for i in range(c_len):
                words.add(chunk[i])
                if i < c_len - 1:
                    words.add(chunk[i:i+2])

        return words

    def compute_similarity(self, tokens1: set[str], tokens2: set[str]) -> float:
        """計算 Jaccard / 重疊相似係數"""
        if not tokens1 or not tokens2:
            return 0.0
        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)
        jaccard = intersection / union if union > 0 else 0.0
        overlap = intersection / min(len(tokens1), len(tokens2)) if min(len(tokens1), len(tokens2)) > 0 else 0.0
        # 綜合加權相似度
        return round(0.4 * jaccard + 0.6 * overlap, 3)

    def evaluate(
        self,
        state: str,
        user_demand: str,
        memory_store: ReflexMemoryStore,
        reflex_registry: "ReflexArcRegistry",
        memory_router: Optional[Any] = None,
        game_type: Optional[Any] = None,
        capability: Optional[Any] = None
    ) -> Tuple[NoveltyLevel, ThinkingEffort, float, Optional[str]]:
        """
        評估新問題之新穎度與相應思考深度 (支援 Jev 多層記憶路由檢索，消除 O(N) 遍歷)
        :return: (NoveltyLevel, ThinkingEffort, similarity_score, matched_reference_id)
        """
        current_text = f"{user_demand} {state}"
        current_tokens = self.tokenize(current_text)

        if not current_tokens:
            return NoveltyLevel.NOVEL, ThinkingEffort.MAX, 0.0, None

        best_score = 0.0
        matched_ref = None

        # 1. 與現有反射弧比對
        for arc in reflex_registry.all_arcs():
            arc_text = f"{arc.name} {' '.join(arc.trigger_keywords)}"
            arc_tokens = self.tokenize(arc_text)
            sim = self.compute_similarity(current_tokens, arc_tokens)
            if sim > best_score:
                best_score = sim
                matched_ref = f"arc:{arc.arc_id}"

        # 2. 與歷史記憶痕跡比對 (優先透過 Jev 多層記憶路由逐層下潛至特定葉節點桶)
        if memory_router is not None:
            domain_id, cluster_id = memory_router.route(
                input_text=current_text,
                game_type=game_type,
                capability=capability,
                tokens=current_tokens
            )
            leaf_results = memory_router.query_leaf_traces(
                input_tokens=current_tokens,
                domain_id=domain_id,
                cluster_id=cluster_id,
                memory_store=memory_store,
                compute_similarity_fn=self.compute_similarity,
                tokenize_fn=self.tokenize,
                top_k=5
            )

            for trace, sim in leaf_results:
                if sim > best_score:
                    best_score = sim
                    matched_ref = f"mem:{trace.memory_id}"
        else:
            # 備援降級：全域遍歷
            for trace in memory_store.get_all_traces():
                trace_text = f"{trace.user_demand} {trace.state_text} {trace.primary_action}"
                trace_tokens = self.tokenize(trace_text)
                sim = self.compute_similarity(current_tokens, trace_tokens)
                if sim > best_score:
                    best_score = sim
                    matched_ref = f"mem:{trace.memory_id}"

        # 3. 判定新穎度與思考深度
        if best_score >= self.similarity_threshold:
            return NoveltyLevel.SIMILAR, ThinkingEffort.MEDIUM, best_score, matched_ref
        else:
            return NoveltyLevel.NOVEL, ThinkingEffort.MAX, best_score, None


class ReflexArcRegistry:
    """
    Jev 反射弧註冊庫 (Reflex Arc Registry)
    管理所有本能反射弧與動態固化反射弧，支援持久化與即時查詢。
    """
    def __init__(self, storage_path: str = REFLEX_ARCS_PATH):
        self.storage_path = storage_path
        self._lock = threading.RLock()
        self._arcs: Dict[str, ReflexArc] = {}
        self._init_instinct_arcs()
        self._load_from_disk()

    def _init_instinct_arcs(self):
        """初始化基礎本能反射弧 (原生反射神經)"""
        # 本能 1: 紅光危險極限閃避
        dodge_arc = ReflexArc(
            arc_id="instinct_dodge_red",
            name="紅光危險極限閃避反射",
            game_type="ALL",
            trigger_keywords=["紅光", "危險", "前搖", "紅圈", "alert", "danger"],
            trigger_predicates={"danger_detected": True},
            questions={
                "tactical_action": Choice(
                    instructions="敵方發動危險前搖攻擊，選擇即時動作",
                    options=["dash_dodge", "parry", "burst_q", "idle"]
                ),
                "should_evade": Noul(instructions="是否必須立即進行迴避閃避？")
            },
            decision_mapping={"dash_dodge": "⚡ 本能反射：偵測到危險前搖，立即按下 Shift / 右鍵閃避！"},
            deterministic_output={"primary_action": "dash_dodge", "should_evade": True, "confidence": 0.98, "urgency": 0.95}
        )
        self._arcs[dodge_arc.arc_id] = dodge_arc

        # 本能 2: 黃光極限招架反擊
        parry_arc = ReflexArc(
            arc_id="instinct_parry_yellow",
            name="黃光極限招架反擊反射",
            game_type="ALL",
            trigger_keywords=["黃光", "招架", "parry", "支援突擊"],
            questions={
                "tactical_action": Choice(
                    instructions="敵方出現黃光警示，選擇最佳應對",
                    options=["parry_assist_space", "dash_dodge", "attack"]
                ),
                "yellow_flash": Noul(instructions="畫面中是否閃爍黃光？")
            },
            decision_mapping={"parry_assist_space": "⚡ 本能反射：黃光閃爍！立即按下 Space / 招架鍵反擊！"},
            deterministic_output={"primary_action": "parry_assist_space", "should_evade": False, "confidence": 0.97, "urgency": 0.98}
        )
        self._arcs[parry_arc.arc_id] = parry_arc

        # 本能 3: 滿能量終結技/大招插隊爆發
        burst_arc = ReflexArc(
            arc_id="instinct_burst_energy_full",
            name="滿能量終結技爆發反射",
            game_type="ALL",
            trigger_keywords=["滿能量", "能量已滿", "ultimateready", "energy_full", "大招就緒"],
            trigger_predicates={"energy_ready": True},
            questions={
                "tactical_action": Choice(
                    instructions="能量已滿，評估是否立即釋放終結技",
                    options=["burst_q", "ultimate_1", "skill_e", "idle"]
                ),
                "energy_ready": Noul(instructions="角色能量是否已滿？")
            },
            decision_mapping={
                "burst_q": "⚡ 本能反射：大招就緒！立即按下 Q 釋放大招！",
                "ultimate_1": "⚡ 本能反射：終結技就緒！立即插隊釋放！"
            },
            deterministic_output={"primary_action": "burst_q", "should_evade": False, "confidence": 0.95, "urgency": 0.88}
        )
        self._arcs[burst_arc.arc_id] = burst_arc

        # 本能 4: 探索互動拾取
        pickup_arc = ReflexArc(
            arc_id="instinct_pickup_interactive",
            name="探索互動寶箱採集反射",
            game_type="ALL",
            trigger_keywords=["寶箱", "拾取", "採集", "神瞳", "卡格車", "撲滿"],
            trigger_predicates={"has_interactive_target": True},
            questions={
                "exploration_action": Choice(
                    instructions="偵測到可互動目標，選擇操作",
                    options=["open_chest", "gather_specialty", "interact_pickup", "catch_trotter"]
                ),
                "has_interactive_target": Noul(instructions="是否有可互動標記？")
            },
            decision_mapping={
                "open_chest": "⚡ 本能反射：靠近寶箱，立即按 【F】 開啟！",
                "gather_specialty": "⚡ 本能反射：靠近特產，立即按 【F】 採集！",
                "interact_pickup": "⚡ 本能反射：靠近物資，立即按 【F】 拾取！",
                "catch_trotter": "⚡ 本能反射：發現次元撲滿，立即施放秘技先手開怪！"
            },
            deterministic_output={"primary_action": "open_chest", "should_evade": False, "confidence": 0.92, "urgency": 0.8}
        )
        self._arcs[pickup_arc.arc_id] = pickup_arc

    def register_arc(self, arc: ReflexArc):
        with self._lock:
            self._arcs[arc.arc_id] = arc
            self._save_to_disk()

    def get_arc(self, arc_id: str) -> Optional[ReflexArc]:
        with self._lock:
            return self._arcs.get(arc_id)

    def find_matching_arc(
        self,
        state: str,
        telemetry: Optional[TelemetryData] = None,
        user_demand: str = "",
        game_type: Optional[Any] = None
    ) -> Optional[ReflexArc]:
        """尋找匹配當前輸入之最佳反射弧"""
        with self._lock:
            # 優先比對動態固化反射弧 (已進化路徑)，再比對基礎本能弧
            learned_arcs = [a for a in self._arcs.values() if not a.arc_id.startswith("instinct_")]
            instinct_arcs = [a for a in self._arcs.values() if a.arc_id.startswith("instinct_")]

            for arc in (learned_arcs + instinct_arcs):
                if arc.matches(state, telemetry, user_demand, game_type=game_type):
                    return arc
            return None

    def all_arcs(self) -> List[ReflexArc]:
        with self._lock:
            return list(self._arcs.values())

    def clear(self):
        """清空所有動態固化反射弧，重置為僅保留基礎本能弧"""
        with self._lock:
            self._arcs.clear()
            self._init_instinct_arcs()
            self._save_to_disk()

    def _save_to_disk(self):
        try:
            target_dir = os.path.dirname(self.storage_path)
            if target_dir and not os.path.exists(target_dir):
                os.makedirs(target_dir, exist_ok=True)
            # 僅保存動態固化反射弧，避免污染基礎本能
            learned_data = [a.to_dict() for a in self._arcs.values() if not a.arc_id.startswith("instinct_")]
            tmp_path = f"{self.storage_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(learned_data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.storage_path)
        except Exception:
            pass

    def _load_from_disk(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            arc = ReflexArc.from_dict(item)
                            self._arcs[arc.arc_id] = arc
            except Exception:
                pass


class ConsolidationPipeline:
    """
    記憶固化管線 (Memory Consolidation Pipeline)
    定期整理記憶，將 Gemini 大腦產出的思考成果提煉、聚類，
    固化為可透過 Jev 處理的：
    - Input: 核心關鍵字特徵與遙測述詞
    - Output: 行動選項、指導說明與機率邊界
    - Flow: Jev 專屬 Question Schema (Choice, Noul, Score) 與本地確定性快取
    使往後遇到相同或相似 input 時，可以直接透過 Jev 反射出答案，完成系統自我進化！
    """

    def __init__(self, min_traces: int = MIN_MEMORIES_TO_CONSOLIDATE):
        self.min_traces = min_traces

    @staticmethod
    def extract_keywords_from_traces(traces: List[MemoryTrace]) -> List[str]:
        """
        從聚類記憶痕跡中提煉出代表性輸入特徵關鍵字 (Jev Trigger Keywords)
        結合跨痕跡高頻中文字詞 (2~4 字元滑動視窗)、英文單字、按鍵與動作概念，過濾無意義停用詞。
        """
        stopwords = {
            "幫我", "現在", "持續", "推薦", "當前", "一個", "我們", "這是", "進行",
            "需要", "可以", "以及", "出現", "因應", "維持", "最佳", "操作", "核心",
            "目標", "條件", "需求", "指示", "狀態", "一下", "請問", "情境", "遇到",
            "敵人", "角色", "施放", "使用", "如果", "這個", "那個", "請", "針對", "評估"
        }

        ngram_counts: Dict[str, int] = {}
        ngram_doc_counts: Dict[str, int] = {}
        en_words: set[str] = set()

        for t in traces:
            text = f"{t.user_demand} {t.state_text}"
            for w in re.findall(r'[a-zA-Z0-9]+', text.lower()):
                if len(w) >= 2 or w in {'q', 'e', 'f', 'r', 'c', 'z', '1', '2', '3', '4'}:
                    if w not in stopwords:
                        en_words.add(w)

            cjk_chunks = re.findall(r'[\u4e00-\u9fff]+', text)
            seen_in_trace = set()
            for chunk in cjk_chunks:
                c_len = len(chunk)
                for n in (2, 3, 4):
                    for i in range(c_len - n + 1):
                        gram = chunk[i:i+n]
                        if gram in stopwords:
                            continue
                        ngram_counts[gram] = ngram_counts.get(gram, 0) + 1
                        seen_in_trace.add(gram)
            for g in seen_in_trace:
                ngram_doc_counts[g] = ngram_doc_counts.get(g, 0) + 1

        if not ngram_counts and not en_words:
            if traces and traces[0].primary_action:
                return [traces[0].primary_action]
            return ["general"]

        # 候選排序：跨痕跡覆蓋數 (doc_count) 優先，次之為總頻率
        candidates = sorted(
            ngram_counts.keys(),
            key=lambda g: (ngram_doc_counts.get(g, 0), ngram_counts.get(g, 0)),
            reverse=True
        )

        selected: List[str] = []
        for g in candidates:
            if len(traces) > 1 and ngram_doc_counts.get(g, 0) < 2 and len(selected) >= 3:
                continue
            if g not in selected:
                selected.append(g)
            if len(selected) >= 8:
                break

        for w in sorted(en_words):
            if len(selected) < 10 and w not in selected:
                selected.append(w)

        return selected if selected else [traces[0].primary_action]

    def consolidate(
        self,
        memory_store: ReflexMemoryStore,
        reflex_registry: ReflexArcRegistry,
        force: bool = False
    ) -> List[ReflexArc]:
        """
        執行記憶整理與固化
        依據 (game_type, primary_action) 與語意特徵進行細分聚類，將 Gemini 大腦成果固化為 Jev 反射弧。
        :param memory_store: 記憶庫
        :param reflex_registry: 反射弧庫
        :param force: 是否強制固化 (即便未滿 min_traces)
        :return: 本次新固化之反射弧列表
        """
        unconsolidated = memory_store.get_unconsolidated_traces()
        if not unconsolidated:
            return []

        detector = NoveltyDetector()
        # 1. 聚類記憶：依據 (game_type, primary_action) 與語意特徵相似度進行細分聚類
        clusters: List[Dict[str, Any]] = []
        for trace in unconsolidated:
            if trace.primary_action == "idle" and not trace.guidance_text.strip():
                continue

            trace_text = f"{trace.user_demand} {trace.state_text} {trace.guidance_text}"
            trace_tokens = detector.tokenize(trace_text)

            matched_cluster = None
            for c in clusters:
                same_game = (normalize_game_type(c["game_type"]) == normalize_game_type(trace.game_type)) or c["game_type"] == "ALL" or trace.game_type == "ALL"
                same_action = (c["primary_action"] == trace.primary_action)
                if same_game and same_action:
                    sim = detector.compute_similarity(trace_tokens, c["tokens"])
                    # 若語意相似度 >= 0.38，判定為同一情境之記憶，歸入同反射弧聚類
                    if sim >= 0.38:
                        matched_cluster = c
                        break

            if matched_cluster:
                matched_cluster["traces"].append(trace)
                matched_cluster["tokens"] |= trace_tokens
            else:
                clusters.append({
                    "game_type": trace.game_type,
                    "primary_action": trace.primary_action,
                    "traces": [trace],
                    "tokens": set(trace_tokens)
                })

        new_arcs: List[ReflexArc] = []

        for cluster in clusters:
            traces = cluster["traces"]
            game_type = cluster["game_type"]
            action = cluster["primary_action"]

            if not force and len(traces) < self.min_traces:
                continue

            # 2. 提煉共通 Input 特徵關鍵字 (Jev Trigger Keywords)
            selected_keywords = self.extract_keywords_from_traces(traces)

            # 3. 提煉共通遙測特徵
            common_predicates = {}
            if traces and traces[0].telemetry_features:
                first_telemetry = traces[0].telemetry_features
                for k, v in first_telemetry.items():
                    if all(t.telemetry_features.get(k) == v for t in traces):
                        if isinstance(v, bool):
                            common_predicates[k] = v

            # 4. 構建 Jev Flow (Question Schema) - 整合 trace 建議與完整 Choice/Noul/Score 三原語
            clean_act = re.sub(r'\W+', '_', action.lower()).strip('_')
            top_kw = selected_keywords[0] if selected_keywords else clean_act
            arc_id = f"arc_learned_{clean_act}_{top_kw}_{int(time.time())}_{len(new_arcs)}"
            arc_name = f"固化反射弧：{game_type} - {action} ({top_kw})"

            options = [action]
            if "idle" not in options:
                options.append("idle")
            if "dash_dodge" not in options and "dodge" in action:
                options.append("dash_dodge")

            # 檢查記憶痕跡中是否有 suggested_questions
            merged_questions = {}
            for t in traces:
                if t.suggested_questions:
                    for qk, qv in t.suggested_questions.items():
                        if qk not in merged_questions:
                            merged_questions[qk] = qv

            questions = {
                "tactical_action": Choice(
                    instructions=f"針對【{game_type}】當前場景，評估最佳決策動作",
                    options=options
                ),
                "should_act": Noul(
                    instructions=f"當前情境是否應當立即執行【{action}】？"
                ),
                "urgency": Score(
                    instructions="此決策之緊迫程度評估",
                    criteria=["低", "中", "高"]
                )
            }
            # 合併 trace 的自定義 question schemas (如果有)
            for qk, qv in merged_questions.items():
                if qk not in questions and isinstance(qv, dict):
                    qtype = qv.get("type", "choice")
                    if qtype == "choice":
                        questions[qk] = Choice(instructions=qv.get("instructions", ""), options=qv.get("options", options))
                    elif qtype == "noul":
                        questions[qk] = Noul(instructions=qv.get("instructions", ""))
                    elif qtype == "score":
                        questions[qk] = Score(instructions=qv.get("instructions", ""), criteria=qv.get("criteria", ["低", "中", "高"]))

            # 5. 構建 Output 與本地確定性規則
            guidance = traces[0].guidance_text or f"⚡ Jev 固化反射：因應【{game_type}】執行【{action}】。"
            decision_mapping = {action: guidance}
            deterministic_output = {
                "primary_action": action,
                "confidence": 0.95,
                "urgency": 0.85,
                "should_evade": ("dodge" in action or "parry" in action),
                "guidance_text": guidance
            }

            source_ids = [t.memory_id for t in traces]

            solidified_arc = ReflexArc(
                arc_id=arc_id,
                name=arc_name,
                game_type=game_type,
                trigger_keywords=selected_keywords,
                trigger_predicates=common_predicates,
                questions=questions,
                decision_mapping=decision_mapping,
                deterministic_output=deterministic_output,
                confidence_threshold=REFLEX_CONFIDENCE_THRESHOLD,
                source_memory_ids=source_ids
            )

            # 6. 註冊反射弧並標記記憶為已固化
            reflex_registry.register_arc(solidified_arc)
            memory_store.mark_consolidated(source_ids, arc_id)
            new_arcs.append(solidified_arc)

        return new_arcs


class NervousSystemCoordinator:
    """
    人類神經系統協調整合核心 (Nervous System Coordinator)
    將 Jev 作為反射神經 (System 1 - Reflex)，將 Gemini 3.8 Flash 作為大腦 (System 2 - Brain)。
    全自動流轉：
    1. Sensation (感知輸入)
    2. Reflex Attempt (優先嘗試 Jev 毫秒級反射)
    3. Escalation Check (若 Jev 無法得出確定結果，自動上升至 Gemini 大腦思考)
    4. Brain Thinking (簡單相似問題 medium effort，新問題 max effort)
    5. Memory Retention (每次皆留下完整記憶痕跡)
    6. Consolidation Pipeline (定期/手動固化為 Jev input、output、flow)
    7. Self-Evolution (下一次相同 input 即可直接由 Jev 反射答案)
    """

    def __init__(
        self,
        jev_engine: JevDecisionEngine,
        gemini_engine: Any,
        memory_store: Optional[ReflexMemoryStore] = None,
        reflex_registry: Optional[ReflexArcRegistry] = None,
        novelty_detector: Optional[NoveltyDetector] = None,
        consolidation_pipeline: Optional[ConsolidationPipeline] = None,
        memory_index: Optional[HierarchicalMemoryIndex] = None,
        memory_router: Optional[JevMemoryRouter] = None
    ):
        self.jev_engine = jev_engine
        self.gemini_engine = gemini_engine
        self.memory_store = memory_store or ReflexMemoryStore()
        self.reflex_registry = reflex_registry or ReflexArcRegistry()
        self.novelty_detector = novelty_detector or NoveltyDetector()
        self.consolidation_pipeline = consolidation_pipeline or ConsolidationPipeline()
        self.memory_index = memory_index or HierarchicalMemoryIndex()
        self.memory_router = memory_router or JevMemoryRouter(index=self.memory_index, jev_engine=self.jev_engine)
        self.memory_store.set_router(self.memory_router)


        # 神經統計指標
        self.reflex_hit_count: int = 0
        self.brain_escalation_count: int = 0
        self.total_requests: int = 0

        # 大腦高頻升級防洪冷卻 (針對 4 Hz 輪詢迴圈)
        self._last_escalation_time: float = 0.0
        self._last_escalated_state: str = ""
        self._last_brain_decision: Optional[Tuple[StrategyDecision, JevResponse, str]] = None
        self.escalation_cooldown: float = 1.5

    def process_step(
        self,
        state: str,
        telemetry: TelemetryData,
        strategy: Any,
        capability: AssistCapability,
        questions: Optional[Dict[str, Any]] = None,
        user_demand: str = "",
        force_escalate: bool = False,
        game_type: Optional[Any] = None
    ) -> Tuple[StrategyDecision, JevResponse, str]:
        """
        神經決策主流程
        :return: (StrategyDecision, JevResponse, decision_source)
                 decision_source: 'reflex' (Jev 反射) | 'brain_medium' (大腦快速思考) | 'brain_max' (大腦深度思考)
        """
        self.total_requests += 1
        effective_game_type = game_type or telemetry.game_type

        # 1. 第一步：Jev 反射神經優先評估 (System 1 Reflex)
        matched_arc = self.reflex_registry.find_matching_arc(
            state=state,
            telemetry=telemetry,
            user_demand=user_demand,
            game_type=effective_game_type
        )

        if not force_escalate:
            # 優先使用 matched_arc 專屬 Question Schema，次之使用 strategy 建構之 questions
            eval_questions = None
            if matched_arc:
                eval_questions = matched_arc.build_jev_questions()
            elif questions:
                eval_questions = questions

            if eval_questions:
                jev_response = self.jev_engine.evaluate(state, eval_questions)

                # 若匹配到固化反射弧且具備確定性決策，執行固化神經突觸權重激發 (Synaptic Excitation)
                if matched_arc and matched_arc.deterministic_output:
                    det_action = matched_arc.deterministic_output.get("primary_action")
                    det_conf = matched_arc.deterministic_output.get("confidence", 0.95)
                    for action_key in ("tactical_action", "action", "exploration_action", "enhancement_action"):
                        if action_key in jev_response.choices and det_action:
                            c = jev_response.choices[action_key]
                            if c.choice == det_action or c.choice == "idle" or c.confidence < matched_arc.confidence_threshold:
                                c.choice = det_action
                                c.confidence = max(c.confidence, det_conf)
                                jev_response.overall_confidence = max(jev_response.overall_confidence, det_conf)
                                jev_response.needs_escalation = False

                # 檢查 Jev 置信度是否達到門檻
                min_choice_conf = 1.0
                if jev_response.choices:
                    min_choice_conf = min(c.confidence for c in jev_response.choices.values())

                conf_threshold = matched_arc.confidence_threshold if matched_arc else self.jev_engine.confidence_threshold

                if min_choice_conf >= conf_threshold and not jev_response.needs_escalation:
                    # 🎯 Jev 反射成功！直接輸出毫秒級答案
                    if matched_arc:
                        matched_arc.hit_count += 1
                        matched_arc.last_fired_at = time.time()
                        jev_response.matched_arc_id = matched_arc.arc_id

                    self.reflex_hit_count += 1
                    jev_response.is_reflex = True

                    # 轉譯決策：若為已命中反射弧，優先使用 matched_arc.interpret_decision 保留專屬決策映射
                    if matched_arc:
                        decision = matched_arc.interpret_decision(jev_response, telemetry)
                        if not decision.guidance_text.startswith("⚡ Jev 反射"):
                            decision.guidance_text = f"⚡ Jev 反射【{matched_arc.name}】：{decision.guidance_text}"
                    else:
                        decision = strategy.interpret_decision(jev_response, telemetry, capability)

                    return decision, jev_response, "reflex"

        # 2. 第二步：無法透過 Jev 得到確定結果，上升至 Gemini 大腦思考 (System 2 Escalation)
        # 高頻輪詢冷卻檢查：若非強制升級且無玩家新需求，且距上次大腦升級時間過短且狀態高度相似，復用近期大腦決策
        if not force_escalate and not user_demand and self._last_brain_decision:
            now_t = time.time()
            if (now_t - self._last_escalation_time) < self.escalation_cooldown:
                detector = self.novelty_detector
                sim = detector.compute_similarity(detector.tokenize(state), detector.tokenize(self._last_escalated_state))
                if sim >= 0.70:
                    last_dec, last_jev, last_src = self._last_brain_decision
                    reused_dec = StrategyDecision(
                        primary_action=last_dec.primary_action,
                        confidence=last_dec.confidence,
                        urgency=0.8 if telemetry.danger_detected else last_dec.urgency,
                        should_evade=last_dec.should_evade,
                        guidance_text=last_dec.guidance_text,
                        telemetry=telemetry,
                        raw_jev=last_jev
                    )
                    return reused_dec, last_jev, last_src

        self.brain_escalation_count += 1

        # 評估問題新穎度與相應思考深度 (經由 Jev 階層式路由下潛)
        novelty, effort, sim_score, matched_ref = self.novelty_detector.evaluate(
            state=state,
            user_demand=user_demand,
            memory_store=self.memory_store,
            reflex_registry=self.reflex_registry,
            memory_router=self.memory_router,
            game_type=telemetry.game_type,
            capability=capability
        )


        # Gemini 大腦思考
        effective_demand = user_demand or f"當前狀態遙測：血量 {telemetry.player_hp_ratio:.2f}，危險={telemetry.danger_detected}"
        gemini_directive = self.gemini_engine.decompose_user_demand(
            user_demand=effective_demand,
            game_type=telemetry.game_type,
            capability=capability,
            thinking_effort=effort.value
        )

        # 解析 Gemini 指令作為決策
        parsed_action = "idle"
        guidance_text = gemini_directive
        g_lower = gemini_directive.lower()
        if "閃避" in gemini_directive or "dodge" in g_lower:
            parsed_action = "dash_dodge"
        elif "招架" in gemini_directive or "parry" in g_lower:
            parsed_action = "parry_assist_space"
        elif "大招" in gemini_directive or "終結技" in gemini_directive or "burst" in g_lower:
            parsed_action = "burst_q"
        elif "戰技" in gemini_directive or "放e" in g_lower or "skill_e" in g_lower or "技能 e" in g_lower:
            parsed_action = "skill_e"
        elif "普攻" in gemini_directive or "平a" in g_lower or "normal_attack" in g_lower:
            parsed_action = "normal_attack"
        elif "治療" in gemini_directive or "補血" in gemini_directive or "回血" in gemini_directive:
            parsed_action = "heal"
        elif "4 號位" in gemini_directive or "四號位" in gemini_directive:
            parsed_action = "switch_4"
        elif "3 號位" in gemini_directive or "三號位" in gemini_directive:
            parsed_action = "switch_3"
        elif "反應" in gemini_directive or "切換" in gemini_directive or "2 號位" in gemini_directive or "二號位" in gemini_directive:
            parsed_action = "switch_2"
        elif "拾取" in gemini_directive or "開啟" in gemini_directive or "寶箱" in gemini_directive:
            parsed_action = "open_chest"
        elif "神瞳" in gemini_directive:
            parsed_action = "collect_oculus"
        elif "解謎" in gemini_directive or "方碑" in gemini_directive or "機關" in gemini_directive:
            parsed_action = "solve_puzzle"
        elif "上鎖" in gemini_directive or "保留" in gemini_directive:
            parsed_action = "lock_and_keep"
        elif "停損" in gemini_directive or "做狗糧" in gemini_directive or "拆解" in gemini_directive:
            parsed_action = "stop_and_salvage"

        # 3. 第三步：每次大腦思考皆留下記憶痕跡 (滿足 Jev 固化需求)
        schema = {}
        if hasattr(self.gemini_engine, "extract_reflex_schema_from_directive"):
            try:
                schema = self.gemini_engine.extract_reflex_schema_from_directive(
                    directive=gemini_directive,
                    user_demand=effective_demand,
                    game_type=telemetry.game_type
                )
                if schema.get("primary_action") and schema.get("primary_action") != "idle":
                    parsed_action = schema.get("primary_action")
            except Exception:
                schema = {}

        trace_guidance = schema.get("guidance_text") if schema.get("guidance_text") else guidance_text[:100]
        suggested_q = schema.get("suggested_questions") if schema.get("suggested_questions") else {
            "tactical_action": {"type": "choice", "options": [parsed_action, "idle"]},
            "should_act": {"type": "noul", "instructions": f"是否執行 {parsed_action}？"},
            "urgency": {"type": "score", "criteria": ["低", "中", "高"]}
        }

        mem_id = f"mem_{int(time.time() * 1000)}_{self.brain_escalation_count}"
        trace = MemoryTrace(
            memory_id=mem_id,
            timestamp=time.time(),
            game_type=telemetry.game_type.value if hasattr(telemetry.game_type, "value") else str(telemetry.game_type),
            user_demand=user_demand,
            visual_context=gemini_directive[:120],
            state_text=state,
            telemetry_features={
                "danger_detected": telemetry.danger_detected,
                "energy_ready": telemetry.energy_ready,
                "in_combat": telemetry.in_combat,
                "has_interactive_target": telemetry.has_interactive_target
            },
            novelty_level=novelty.value,
            thinking_effort=effort.value,
            gemini_directive=gemini_directive,
            primary_action=parsed_action,
            guidance_text=trace_guidance,
            suggested_questions=suggested_q
        )
        self.memory_store.record_trace(
            trace,
            game_type=telemetry.game_type,
            capability=capability
        )

        # 建構 StrategyDecision
        jev_response = JevResponse(
            choices={"tactical_action": ChoiceResult(choice=parsed_action, confidence=0.88)},
            nouls={"should_evade": NoulResult(noul=(parsed_action == "dash_dodge"))},
            scores={"combat_urgency": ScoreResult(score=0.8)}
        )
        jev_response.is_reflex = False
        jev_response.needs_escalation = True

        decision = StrategyDecision(
            primary_action=parsed_action,
            confidence=0.88,
            urgency=0.8 if telemetry.danger_detected else 0.5,
            should_evade=(parsed_action == "dash_dodge"),
            guidance_text=f"🧠 大腦思考 ({'快速思考' if effort == ThinkingEffort.MEDIUM else '深度思考'})：\n{gemini_directive}",
            telemetry=telemetry,
            raw_jev=jev_response
        )

        source_label = f"brain_{effort.value}"
        self._last_escalation_time = time.time()
        self._last_escalated_state = state
        self._last_brain_decision = (decision, jev_response, source_label)

        return decision, jev_response, source_label

    def consolidate(self, force: bool = False) -> List[ReflexArc]:
        """觸發記憶整理與固化管線"""
        return self.consolidation_pipeline.consolidate(
            memory_store=self.memory_store,
            reflex_registry=self.reflex_registry,
            force=force
        )

    def get_stats(self) -> Dict[str, Any]:
        """神經系統狀態與自我進化指標"""
        hit_rate = (self.reflex_hit_count / self.total_requests) if self.total_requests > 0 else 0.0
        all_traces = self.memory_store.get_all_traces()
        unconsolidated = [t for t in all_traces if not t.is_consolidated]
        solidified_arcs = [a for a in self.reflex_registry.all_arcs() if not a.arc_id.startswith("instinct_")]

        # 自我進化階段評定
        if len(solidified_arcs) >= 10 and hit_rate >= 0.8:
            stage = "神經系統完全體 (Autonomous Reflex Mastery)"
        elif len(solidified_arcs) >= 5:
            stage = "高度反射成型階段 (Advanced Reflex Consolidation)"
        elif len(solidified_arcs) >= 1:
            stage = "突觸建立階段 (Synapse Formation)"
        else:
            stage = "初始探索階段 (Initial Exploration)"

        # 多層記憶索引狀態
        total_domains = len(self.memory_index.domains)
        total_clusters = sum(len(d.clusters) for d in self.memory_index.domains.values())

        return {
            "total_requests": self.total_requests,
            "reflex_hit_count": self.reflex_hit_count,
            "brain_escalation_count": self.brain_escalation_count,
            "reflex_hit_rate": round(hit_rate * 100, 1),
            "memory_traces_count": len(all_traces),
            "unconsolidated_memories": len(unconsolidated),
            "solidified_arcs_count": len(solidified_arcs),
            "total_reflex_arcs": len(self.reflex_registry.all_arcs()),
            "total_domains": total_domains,
            "total_clusters": total_clusters,
            "hierarchical_routing_enabled": True,
            "current_evolution_stage": stage
        }

