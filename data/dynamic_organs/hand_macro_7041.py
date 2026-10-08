"""
自律生長專屬操作手腳本 - 建立腳本操作手
需求: 建立腳本 -> 【Guidance HUD 戰術指令載入完成】   【系統狀態】：大腦認知核心 (Gemini 3.8 Flash) 已
"""

import time
from typing import Dict, Any, Optional, List
from game_assistant.organs.base import BaseOrganTool, OrganType


class DynamicHand_61424(BaseOrganTool):
    def __init__(self, actuator=None):
        super().__init__(
            organ_id="hand_macro_7041",
            organ_type=OrganType.ACTUATOR_HAND,
            name="建立腳本操作手",
            description="針對需求【建立腳本 -> 【Guidance HUD 戰術指令載入完成】   【系統狀態】：大腦認知核心 (Gemini 3.8 Flash) 已】自律生長建置之真實操作接管手",
            is_built_in=False
        )
        self.actuator = actuator
        self.steps = [{'action_type': 'key', 'target': '3', 'duration': 0.05, 'post_delay': 0.25, 'description': '切 3 號位輔助'}, {'action_type': 'key', 'target': 'e', 'duration': 0.08, 'post_delay': 0.3, 'description': '施放戰技 E 掛屬'}, {'action_type': 'click', 'target': 'left', 'duration': 0.04, 'post_delay': 0.15, 'description': '普攻補能量'}, {'action_type': 'key', 'target': '4', 'duration': 0.05, 'post_delay': 0.25, 'description': '切 4 號位副C'}, {'action_type': 'key', 'target': 'e', 'duration': 0.08, 'post_delay': 0.3, 'description': '副C戰技 E'}, {'action_type': 'key', 'target': 'q', 'duration': 0.1, 'post_delay': 0.45, 'description': '副C大招 Q 增傷'}, {'action_type': 'key', 'target': '1', 'duration': 0.05, 'post_delay': 0.25, 'description': '切 1 號位主 C'}, {'action_type': 'key', 'target': 'q', 'duration': 0.1, 'post_delay': 0.5, 'description': '主 C 大招 Q 核爆'}, {'action_type': 'key', 'target': 'e', 'duration': 0.08, 'post_delay': 0.25, 'description': '主 C 戰技 E 連招'}, {'action_type': 'click', 'target': 'left', 'duration': 0.04, 'post_delay': 0.15, 'description': '連續平 A 壓制'}]

    def execute(self, **kwargs) -> Dict[str, Any]:
        self.execution_count += 1
        act = kwargs.get("actuator", self.actuator)
        init_enabled = bool(act and getattr(act, "is_enabled", False))
        performed = False
        details = []

        for step in self.steps:
            a_type = step.get("action_type", "key")
            tgt = step.get("target", "e")
            dur = step.get("duration", 0.05)
            p_delay = step.get("post_delay", 0.15)
            desc = step.get("description", "")

            if act and getattr(act, "is_enabled", False):
                performed = True
                try:
                    if a_type in ("key", "hold_key"):
                        act.press_key(tgt, hold_sec=dur)
                    elif a_type in ("click", "hold_click"):
                        act.click_mouse(button_name=tgt, count=1)
                except Exception:
                    pass

            details.append(desc)
            if p_delay > 0:
                time.sleep(p_delay)

            if init_enabled and act and not getattr(act, "is_enabled", False):
                details.append("⚠️ 偵測到 F8 緊急急停，終止後續動作")
                break

        res = {
            "action": "script_takeover_executed",
            "organ_id": self.organ_id,
            "performed_real": performed,
            "steps": details,
            "status": "completed"
        }
        self.last_result = res
        return res

    def extract_predicates(self, **kwargs) -> Dict[str, Any]:
        return {
            "hand_macro_7041_executed": True,
            "has_hand_takeover": True
        }
