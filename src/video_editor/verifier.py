"""AI 多模態驗證模組（結合 AGY CLI 進行關鍵影格審核）。"""

import subprocess
from pathlib import Path
from typing import List, Tuple

from video_editor.config import EditorConfig
from video_editor.detector import VideoDetector


class AIVerifier:
    """利用 AI 進行候選點的多模態視覺複審。"""

    def __init__(self, config: EditorConfig, detector: VideoDetector):
        self.config = config
        self.detector = detector

    def _query_agy_cli(self, image_path: Path, prompt: str) -> bool:
        """透過 AGY CLI 發送多模態查詢並判定回應。"""
        cmd = [
            self.config.agy_bin,
            "ask",
            f"--image={str(image_path)}",
            prompt,
        ]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                timeout=45,
            )
            reply = result.stdout.strip().upper()
            return "YES" in reply
        except (subprocess.SubprocessError, FileNotFoundError) as err:
            print(f"  [AI 呼叫警告] 無法透過 '{self.config.agy_bin}' 驗證 ({err})，採用保守策略。")
            return False

    def verify_freezes(
        self, freeze_ranges: List[Tuple[float, float]]
    ) -> List[Tuple[float, float]]:
        """利用 AI 複審靜止畫面，確認是否為真正的玩家暫離。"""
        if not self.config.enable_ai:
            print("▶ AI 驗證已停用，直接採用全部靜止特徵。")
            return freeze_ranges

        print(f"\n▶ 正在進行 AI 複審：檢查 {len(freeze_ranges)} 個疑似暫離靜止區間...")
        confirmed_freezes: List[Tuple[float, float]] = []

        idle_prompt = (
            "這是一張遊戲錄影片段的截圖。"
            "請判斷畫面是否處於『玩家暫離狀態』"
            "（例如：主選單、暫停 Pause 選單、死亡等待畫面、長時間無操作掛機畫面）。\n"
            "注意：若畫面有角色對話框、字幕、劇情動畫或玩家正在正常瀏覽地圖/介面，請回答 NO。\n"
            "如果是確定暫離或暫停選單，請回答 YES。\n"
            "請在回答的第一行明確輸出 YES 或 NO。"
        )

        for idx, (start, end) in enumerate(freeze_ranges, start=1):
            mid_point = (start + end) / 2.0
            frame_path = self.config.temp_dir / f"freeze_candidate_{idx}.jpg"

            try:
                self.detector.extract_keyframe(mid_point, frame_path)
                is_idle = self._query_agy_cli(frame_path, idle_prompt)
            except Exception as err:
                print(f"  - 影格截取或判定失敗 [{start:.1f}s ~ {end:.1f}s]: {err}")
                is_idle = True  # 預設維持原本靜止偵測

            if is_idle:
                print(f"  - [{start:.1f}s ~ {end:.1f}s] AI 確認：此為暫離/暫停選單（將刪除此段）。")
                confirmed_freezes.append((start, end))
            else:
                print(f"  - [{start:.1f}s ~ {end:.1f}s] AI 判斷：此為劇情對話或遊戲內容（保留此段）。")

        return confirmed_freezes

    def verify_transitions(self, cut_points: List[float]) -> List[float]:
        """利用 AI 複審黑畫面，確認是否為合適的章節過場/讀取畫面。"""
        if not self.config.enable_ai:
            return cut_points

        print(f"\n▶ 正在進行 AI 複審：檢查 {len(cut_points)} 個轉場候選點...")
        confirmed_cuts: List[float] = []

        trans_prompt = (
            "這是一張遊戲錄影截圖。"
            "請判斷畫面是否為『章節切換、過場載入畫面（Loading Screen）或全黑/全白轉場』？\n"
            "若只是遊戲內的黑夜場景、暗部走道或戰鬥畫面，請回答 NO。\n"
            "若是適合用來切分影片的轉場過場，請回答 YES。\n"
            "請在回答的第一行明確輸出 YES 或 NO。"
        )

        for idx, timestamp in enumerate(cut_points, start=1):
            frame_path = self.config.temp_dir / f"cut_candidate_{idx}.jpg"
            try:
                self.detector.extract_keyframe(timestamp, frame_path)
                is_trans = self._query_agy_cli(frame_path, trans_prompt)
            except Exception:
                is_trans = True

            if is_trans:
                confirmed_cuts.append(timestamp)

        print(f"✔ 經 AI 複審後，確認 {len(confirmed_cuts)} 個有效轉場切點。")
        return confirmed_cuts

    def verify_cut_frame_stability(self, cut_time: float) -> bool:
        """利用 AI 複審切點畫面，確保角色動作已做完、畫面處於相對靜止定格狀態。"""
        if not self.config.enable_ai:
            return True

        frame_path = self.config.temp_dir / f"cut_stability_{int(cut_time)}.jpg"
        stability_prompt = (
            "這是一張遊戲影片切片結尾處的畫面截圖。"
            "請判斷畫面是否處於『相對靜止定格或動作已結束』的狀態？\n"
            "（例如：角色已站定對話完畢、過場黑/白畫面、靜態介面或動作收尾）。\n"
            "若角色正在快速揮刀施法、跳躍滯空、鏡頭高速旋轉或動作明顯只做了一半，請回答 NO。\n"
            "若畫面平穩、適合做為該集結尾，請回答 YES。\n"
            "請在回答的第一行明確輸出 YES 或 NO。"
        )
        try:
            self.detector.extract_keyframe(cut_time, frame_path)
            is_stable = self._query_agy_cli(frame_path, stability_prompt)
            return is_stable
        except Exception:
            return True
