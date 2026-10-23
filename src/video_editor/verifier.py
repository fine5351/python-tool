"""AI 多模態場景索引、視覺探勘與對話規劃模組（支援三級職責 Model 分流）。"""

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from video_editor.config import EditorConfig
from video_editor.detector import VideoDetector
from video_editor.models import EditPlan, TimelineSegment, format_timestamp


class AIVerifier:
    """利用 AGY CLI 與職責分流模型進行多模態場景理解、動態細掃與時間軸規劃。"""

    def __init__(self, config: EditorConfig, detector: VideoDetector):
        self.config = config
        self.detector = detector

    def _build_agy_cmd(
        self,
        prompt: str,
        image_path: Optional[Path] = None,
        role: str = "fast_vision",
    ) -> List[str]:
        """根據工作職責組裝 AGY CLI 指令與對應的合法模型名稱。"""
        cli_model = self.config.models.resolve_cli_model(role)
        final_prompt = prompt
        cmd = [
            self.config.agy_bin,
            "-p",
        ]
        if image_path is not None:
            cmd.extend(["--add-dir", str(image_path.parent.resolve())])
            final_prompt = f"請讀取並分析圖片檔案: {str(image_path.resolve())}\n\n{prompt}"
        cmd.append(final_prompt)
        cmd.append(f"--model={cli_model}")
        return cmd

    def _query_agy_text(
        self,
        prompt: str,
        image_path: Optional[Path] = None,
        role: str = "fast_vision",
        timeout: int = 60,
    ) -> str:
        """透過指定職責的 Model 發送 AGY CLI 查詢並取得文字回應。"""
        cmd = self._build_agy_cmd(prompt=prompt, image_path=image_path, role=role)
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            if result.returncode != 0:
                err_out = (result.stderr or result.stdout or "").strip()
                err_msg = err_out.splitlines()[0] if err_out else f"code {result.returncode}"
                cli_model = self.config.models.resolve_cli_model(role)
                print(f"  [AI 呼叫警告] agy 查詢未成功 (model={cli_model}): {err_msg}")
                return ""
            return result.stdout.strip()
        except (subprocess.SubprocessError, FileNotFoundError) as err:
            cli_model = self.config.models.resolve_cli_model(role)
            print(
                f"  [AI 呼叫警告] 無法透過 '{self.config.agy_bin}' (role={role}, model={cli_model}) 查詢 ({err})。"
            )
            return ""

    def _query_agy_cli(
        self,
        image_path: Path,
        prompt: str,
        role: str = "fast_vision",
    ) -> bool:
        """透過 AGY CLI 發送多模態二元查詢並判定是否為 YES。"""
        reply = self._query_agy_text(prompt=prompt, image_path=image_path, role=role, timeout=45)
        return "YES" in reply.upper()

    @staticmethod
    def _extract_json(text: str) -> Optional[Any]:
        """從 AI 回應文字中安全提取 JSON 物件或陣列。"""
        if not text:
            return None
        cleaned = text.strip()
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, re.IGNORECASE)
        if fence_match:
            cleaned = fence_match.group(1).strip()

        for start_char, end_char in [("{", "}"), ("[", "]")]:
            s_idx = cleaned.find(start_char)
            e_idx = cleaned.rfind(end_char)
            if s_idx != -1 and e_idx != -1 and e_idx > s_idx:
                candidate = cleaned[s_idx : e_idx + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def compute_dhash(image_path: Path, hash_size: int = 8) -> Optional[int]:
        """使用 Pillow 計算影像的 64-bit 差異雜湊值 (dHash)，用於通用場景相似度比對。"""
        try:
            from PIL import Image

            with Image.open(image_path) as img:
                gray = img.convert("L").resize((hash_size + 1, hash_size))
                pixels = list(gray.getdata())
                diff_bits = 0
                for row in range(hash_size):
                    row_offset = row * (hash_size + 1)
                    for col in range(hash_size):
                        diff_bits <<= 1
                        if pixels[row_offset + col] > pixels[row_offset + col + 1]:
                            diff_bits |= 1
                return diff_bits
        except Exception:
            return None

    @staticmethod
    def hamming_distance(hash1: int, hash2: int) -> int:
        """計算兩個 dHash 整數間的漢明距離（相異位元數）。"""
        return bin(hash1 ^ hash2).count("1")

    @classmethod
    def cluster_similar_frames(
        cls,
        frame_paths: List[Optional[Path]],
        max_distance: int = 12,
    ) -> List[Optional[int]]:
        """對各段落代表影格進行視覺相似度分群，僅對出現 >= 2 次的相似場景賦予群組編號。"""
        hashes: List[Optional[int]] = [
            cls.compute_dhash(p) if p is not None and p.is_file() else None
            for p in frame_paths
        ]

        raw_labels: List[Optional[int]] = [None] * len(hashes)
        cluster_counts: Dict[int, int] = {}
        next_cluster_id = 1

        for i, h_i in enumerate(hashes):
            if h_i is None:
                continue
            assigned = None
            for j in range(i):
                h_j = hashes[j]
                if h_j is not None and cls.hamming_distance(h_i, h_j) <= max_distance:
                    assigned = raw_labels[j]
                    break
            if assigned is None:
                assigned = next_cluster_id
                next_cluster_id += 1
            raw_labels[i] = assigned
            cluster_counts[assigned] = cluster_counts.get(assigned, 0) + 1

        # 只保留至少有 2 個段落共享的視覺群組，並重新編號為 1, 2, ...
        remap: Dict[int, int] = {}
        final_labels: List[Optional[int]] = []
        for lbl in raw_labels:
            if lbl is None or cluster_counts.get(lbl, 0) < 2:
                final_labels.append(None)
            else:
                if lbl not in remap:
                    remap[lbl] = len(remap) + 1
                final_labels.append(remap[lbl])
        return final_labels

    @staticmethod
    def build_contact_sheet(
        frames_with_labels: List[Tuple[Path, str]],
        output_path: Path,
        cols: int = 2,
        tile_size: Tuple[int, int] = (480, 270),
    ) -> Optional[Path]:
        """將多張關鍵影格合並為附帶編號與時間戳記標籤的單張拼圖 (Contact Sheet)。"""
        valid_items = [(p, lbl) for p, lbl in frames_with_labels if p.is_file()]
        if not valid_items:
            return None

        try:
            from PIL import Image, ImageDraw

            rows = (len(valid_items) + cols - 1) // cols
            tile_w, tile_h = tile_size
            sheet = Image.new("RGB", (cols * tile_w, rows * tile_h), color=(20, 20, 20))
            draw = ImageDraw.Draw(sheet)

            for idx, (img_path, label) in enumerate(valid_items):
                r = idx // cols
                c = idx % cols
                x0 = c * tile_w
                y0 = r * tile_h
                with Image.open(img_path) as im:
                    resized = im.convert("RGB").resize(tile_size)
                    sheet.paste(resized, (x0, y0))

                # 繪製左上角文字底框與標籤
                banner_w = min(tile_w, max(140, len(label) * 9 + 16))
                draw.rectangle([x0, y0, x0 + banner_w, y0 + 26], fill=(0, 0, 0))
                draw.text((x0 + 6, y0 + 6), label, fill=(255, 255, 0))

            output_path.parent.mkdir(parents=True, exist_ok=True)
            sheet.save(output_path, quality=85)
            return output_path
        except Exception:
            # 若執行環境未安裝 Pillow，退回使用第一張有效影格
            return valid_items[0][0]

    def verify_freezes(
        self, freeze_ranges: List[Tuple[float, float]]
    ) -> List[Tuple[float, float]]:
        """利用 fast_vision 模型複審靜止畫面，確認是否為真正的暫離或無意義停滯。"""
        if not freeze_ranges:
            return []

        model_name = self.config.models.get_model("fast_vision")
        print(
            f"\n▶ 正在進行 AI 靜止區間快篩 (model={model_name})："
            f"檢查 {len(freeze_ranges)} 個疑似暫離區間..."
        )
        confirmed_freezes: List[Tuple[float, float]] = []

        idle_prompt = (
            "這是一張影片片段的截圖。"
            "請判斷畫面是否處於『暫離、暫停選單、讀取等待或長時間無操作靜止狀態』？\n"
            "注意：若畫面有重要對話字幕、劇情演出或正常內容展示，請回答 NO。\n"
            "若是可剔除的暫離或選單靜止畫面，請回答 YES。\n"
            "請在回答的第一行明確輸出 YES 或 NO。"
        )

        for idx, (start, end) in enumerate(freeze_ranges, start=1):
            mid_point = (start + end) / 2.0
            frame_path = self.config.temp_dir / f"freeze_candidate_{idx}.jpg"

            try:
                self.detector.extract_keyframe(mid_point, frame_path)
                is_idle = self._query_agy_cli(frame_path, idle_prompt, role="fast_vision")
            except Exception as err:
                print(f"  - 影格截取或判定失敗 [{start:.1f}s ~ {end:.1f}s]: {err}")
                is_idle = True

            if is_idle:
                print(
                    f"  - [{format_timestamp(start)} ~ {format_timestamp(end)}] "
                    "AI 確認：暫離/選單靜止（預設標記為刪除）。"
                )
                confirmed_freezes.append((start, end))
            else:
                print(
                    f"  - [{format_timestamp(start)} ~ {format_timestamp(end)}] "
                    "AI 判斷：靜態劇情或有效內容（預設保留）。"
                )

        return confirmed_freezes

    def _is_black_or_white_frame(self, frame_path: Path) -> bool:
        """透過畫面亮度與統計數值精準判定是否為黑色或白色轉場畫面。"""
        try:
            from PIL import Image, ImageStat

            with Image.open(frame_path) as im:
                gray = im.convert("L")
                stat = ImageStat.Stat(gray)
                mean_val = stat.mean[0]
                stddev_val = stat.stddev[0]
                if mean_val < 30.0 and stddev_val < 25.0:
                    return True
                if mean_val > 220.0 and stddev_val < 25.0:
                    return True
        except Exception:
            pass
        return False

    def verify_transitions(self, cut_points: List[float]) -> List[float]:
        """使用影像統計與 fast_vision 模型複審黑/白轉場候選點。"""
        if not cut_points:
            return []

        model_name = self.config.models.get_model("fast_vision")
        print(
            f"\n▶ 正在進行轉場複審 (model={model_name})："
            f"檢查 {len(cut_points)} 個黑/白轉場候選點..."
        )
        confirmed_cuts: List[float] = []

        trans_prompt = (
            "這是一張影片截圖。"
            "請判斷畫面是否為『場景切換、過場載入畫面（Loading Screen）或全黑/全白轉場』？\n"
            "若只是暗部場景或一般動態畫面，請回答 NO。\n"
            "若是適合切分場景段落的轉場過場，請回答 YES。\n"
            "請在回答的第一行明確輸出 YES 或 NO。"
        )

        for idx, timestamp in enumerate(cut_points, start=1):
            frame_path = self.config.temp_dir / f"cut_candidate_{idx}.jpg"
            try:
                self.detector.extract_keyframe(timestamp, frame_path)
            except Exception as err:
                print(f"  - 影格截取失敗 [{timestamp:.1f}s]: {err}")
                confirmed_cuts.append(timestamp)
                continue

            if self._is_black_or_white_frame(frame_path):
                confirmed_cuts.append(timestamp)
                continue

            if self._query_agy_cli(frame_path, trans_prompt, role="fast_vision"):
                confirmed_cuts.append(timestamp)

        print(f"✔ 經複審後，確認 {len(confirmed_cuts)} 個有效場景轉場點。")
        return confirmed_cuts

    def verify_cut_frame_stability(self, cut_time: float) -> bool:
        """利用 fast_vision 模型複審切點畫面穩定度。"""
        frame_path = self.config.temp_dir / f"cut_stability_{int(cut_time)}.jpg"
        stability_prompt = (
            "這是一張影片切片結尾處的畫面截圖。"
            "請判斷畫面是否處於『相對靜止定格或動作已收尾』的狀態？\n"
            "若畫面平穩、適合做為段落結尾，請回答 YES；若動作明顯只做了一半，請回答 NO。\n"
            "請在回答的第一行明確輸出 YES 或 NO。"
        )
        try:
            self.detector.extract_keyframe(cut_time, frame_path)
            return self._query_agy_cli(frame_path, stability_prompt, role="fast_vision")
        except Exception:
            return True

    def build_initial_edit_plan(
        self,
        total_duration: float,
        confirmed_freezes: List[Tuple[float, float]],
        confirmed_cuts: List[float],
    ) -> EditPlan:
        """結合轉場邊界、視覺相似度分群與 fast_vision 模型，建立通用初始場景索引計畫 (EditPlan)。"""
        # 1. 收集所有時間軸切分邊界點
        boundaries = {0.0, round(total_duration, 2)}
        for f_start, f_end in confirmed_freezes:
            if 0.0 < f_start < total_duration:
                boundaries.add(round(f_start, 2))
            if 0.0 < f_end < total_duration:
                boundaries.add(round(f_end, 2))
        for cut_t in confirmed_cuts:
            if 0.0 < cut_t < total_duration:
                boundaries.add(round(cut_t, 2))

        sorted_bounds = sorted(boundaries)

        # 過濾過短碎段 (< 2.0 秒) 並建立初步段落
        raw_intervals: List[Tuple[float, float]] = []
        for i in range(len(sorted_bounds) - 1):
            s_t, e_t = sorted_bounds[i], sorted_bounds[i + 1]
            if raw_intervals and (e_t - s_t) < 2.0:
                raw_intervals[-1] = (raw_intervals[-1][0], e_t)
            else:
                raw_intervals.append((s_t, e_t))

        segments: List[TimelineSegment] = []
        rep_frames: List[Optional[Path]] = []

        for idx, (s_t, e_t) in enumerate(raw_intervals, start=1):
            # 檢查該區間是否落在已確認的靜止暫離區間內
            is_freeze = any(
                abs(s_t - fs) < 1.5 and abs(e_t - fe) < 1.5
                for fs, fe in confirmed_freezes
            )
            seg = TimelineSegment(
                id=idx,
                start=s_t,
                end=e_t,
                summary="暫離/靜止畫面" if is_freeze else f"場景段落 #{idx}",
                tags=["靜止", "暫離"] if is_freeze else ["一般內容"],
                keep=not is_freeze,
            )
            segments.append(seg)

            # 擷取各段落開頭偏後 (避開全黑轉場幀) 的代表影格供視覺分群與 AI 摘要使用
            sample_t = min(e_t - 0.1, s_t + min(3.0, (e_t - s_t) * 0.25))
            frame_path = self.config.temp_dir / f"seg_rep_{idx}.jpg"
            try:
                self.detector.extract_keyframe(max(0.0, sample_t), frame_path)
                rep_frames.append(frame_path)
            except Exception:
                rep_frames.append(None)

        # 2. 計算通用視覺相似度分群 (dHash Clustering)
        clusters = self.cluster_similar_frames(rep_frames)
        for seg, cid in zip(segments, clusters):
            seg.visual_cluster = cid

        # 3. 使用 fast_vision 模型批次對拼圖產生通用中文場景描述與標籤
        active_Pairs = [
            (seg, frame_p)
            for seg, frame_p in zip(segments, rep_frames)
            if frame_p is not None and frame_p.is_file() and seg.keep
        ]
        if active_Pairs:
            model_name = self.config.models.get_model("fast_vision")
            print(
                f"\n▶ 正在建立通用場景索引 (model={model_name})："
                f"分析 {len(active_Pairs)} 個有效段落畫面摘要..."
            )
            batch_size = 6
            for b_start in range(0, len(active_Pairs), batch_size):
                batch = active_Pairs[b_start : b_start + batch_size]
                labels_input = [
                    (
                        fp,
                        f"ID:{seg.id} [{format_timestamp(seg.start)}~{format_timestamp(seg.end)}]",
                    )
                    for seg, fp in batch
                ]
                sheet_path = (
                    self.config.temp_dir / f"scene_index_sheet_{b_start // batch_size + 1}.jpg"
                )
                built_sheet = self.build_contact_sheet(labels_input, sheet_path)
                if built_sheet is None:
                    continue

                seg_list_desc = "\n".join(
                    f"- ID {seg.id}: {format_timestamp(seg.start)} ~ {format_timestamp(seg.end)}"
                    + (
                        f" (視覺相似群組 #{seg.visual_cluster})"
                        if seg.visual_cluster is not None
                        else ""
                    )
                    for seg, _ in batch
                )
                caption_prompt = (
                    "這張拼圖包含多個影片段落的代表畫面（左上角標有段落 ID 與時間範圍）。\n"
                    f"段落清單：\n{seg_list_desc}\n\n"
                    "請為每個段落提供客觀簡短的繁體中文畫面摘要 (summary) 與 1~3 個語義標籤 (tags)。\n"
                    "請僅輸出 JSON 陣列格式，範例如下：\n"
                    '[{"id": 1, "summary": "角色於城鎮對話", "tags": ["對話", "城鎮"]}]'
                )
                reply_text = self._query_agy_text(
                    prompt=caption_prompt,
                    image_path=built_sheet,
                    role="fast_vision",
                )
                parsed = self._extract_json(reply_text)
                if isinstance(parsed, list):
                    for item in parsed:
                        if not isinstance(item, dict) or "id" not in item:
                            continue
                        target_id = int(item["id"])
                        for seg, _ in batch:
                            if seg.id == target_id:
                                if item.get("summary"):
                                    seg.summary = str(item["summary"]).strip()
                                if isinstance(item.get("tags"), list):
                                    seg.tags = [str(t) for t in item["tags"]]

        plan = EditPlan(
            video_path=str(self.config.video_path),
            total_duration=total_duration,
            segments=segments,
            sequence=[seg.id for seg in segments],
            export_mode=self.config.export_mode,
            target_min_part_len=self.config.target_min_part_len,
            target_max_part_len=self.config.target_max_part_len,
        )
        return plan

    def inspect_time_range(
        self,
        start: float,
        end: float,
        query: str,
        sample_count: int = 8,
    ) -> List[Dict[str, Any]]:
        """使用 deep_vision 模型對指定時間區間密集抽樣截圖並細分出子段落。"""
        start = max(0.0, float(start))
        end = max(start + 1.0, float(end))
        sample_count = max(2, min(12, int(sample_count)))
        step = (end - start) / float(sample_count)

        model_name = self.config.models.get_model("deep_vision")
        print(
            f"\n🔍 正在啟動深度視覺細掃 (model={model_name})："
            f"範圍 {format_timestamp(start)} ~ {format_timestamp(end)}，抽樣 {sample_count} 格..."
        )

        frames_with_labels: List[Tuple[Path, str]] = []
        sample_times: List[float] = []
        for idx in range(sample_count):
            t = start + (idx + 0.5) * step
            sample_times.append(t)
            fp = self.config.temp_dir / f"inspect_{int(start)}_{int(end)}_{idx + 1}.jpg"
            try:
                self.detector.extract_keyframe(t, fp)
                frames_with_labels.append((fp, f"#{idx + 1} t={t:.1f}s ({format_timestamp(t)})"))
            except Exception:
                pass

        sheet_path = self.config.temp_dir / f"inspect_sheet_{int(start)}_{int(end)}.jpg"
        built_sheet = self.build_contact_sheet(frames_with_labels, sheet_path, cols=2)

        inspect_prompt = (
            f"這張時間軸拼圖展示了影片在 {start:.1f}s ({format_timestamp(start)}) 到 "
            f"{end:.1f}s ({format_timestamp(end)}) 之間的連續抽樣畫面。\n"
            f"使用者的剪輯/探勘需求為：『{query}』\n\n"
            "請根據畫面變化與使用者需求，將這段時間範圍切分為 1 到多個連續的子段落（覆蓋從 "
            f"{start:.1f} 到 {end:.1f} 的完整範圍），並標註每段是否應該保留 (keep: true/false)。\n"
            "請僅輸出 JSON 陣列，格式如下：\n"
            "[\n"
            f'  {{"start": {start:.1f}, "end": ..., "summary": "子段落中文描述", "tags": ["標籤"], "keep": true}},\n'
            f'  {{"start": ..., "end": {end:.1f}, "summary": "子段落中文描述", "tags": ["標籤"], "keep": false}}\n'
            "]"
        )
        reply = self._query_agy_text(
            prompt=inspect_prompt,
            image_path=built_sheet,
            role="deep_vision",
            timeout=90,
        )
        parsed = self._extract_json(reply)
        if isinstance(parsed, list) and parsed:
            valid_subs: List[Dict[str, Any]] = []
            for item in parsed:
                if isinstance(item, dict) and "start" in item and "end" in item:
                    valid_subs.append(item)
            if valid_subs:
                return valid_subs

        # 若 AI 回傳無法解析，保底依中點切為兩段供使用者調整
        mid = round((start + end) / 2.0, 1)
        return [
            {
                "start": start,
                "end": mid,
                "summary": f"細掃區間前半 ({query})",
                "tags": ["細掃"],
                "keep": True,
            },
            {
                "start": mid,
                "end": end,
                "summary": f"細掃區間後半 ({query})",
                "tags": ["細掃"],
                "keep": True,
            },
        ]

    def plan_edits_from_dialogue(
        self,
        plan: EditPlan,
        user_instruction: str,
    ) -> Dict[str, Any]:
        """使用 planner 模型將使用者自然語言指令與當前 EditPlan 轉為結構化剪輯操作。"""
        model_name = self.config.models.get_model("planner")
        print(f"🤖 正在由規劃模型解析指令 (model={model_name})...")

        plan_context = json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)
        planner_prompt = (
            "你是一個專業的通用型 AI 影片剪輯助手。以下為目前影片的時間軸剪輯計畫 (EditPlan JSON)：\n"
            f"{plan_context}\n\n"
            f"使用者的最新指令為：『{user_instruction}』\n\n"
            "你可以透過兩種方式回應使用者需求：\n"
            "1. 若現有段落資訊已足夠，請在 `operations` 陣列中輸出對應的時間軸操作指令，支援的操作格式包含：\n"
            '   - 合併相鄰段落: `{"op": "merge", "segment_ids": [4, 5], "summary": "整合後的段落摘要"}`\n'
            '   - 僅保留指定段落: `{"op": "keep_only", "segment_ids": [4]}`\n'
            '   - 保留段落: `{"op": "keep", "segment_ids": [1, 2]}`\n'
            '   - 刪除段落: `{"op": "drop", "segment_ids": [3, 4]}`\n'
            '   - 切分段落: `{"op": "split", "segment_id": 2, "cut_time": 150.0, "left_summary": "...", "right_summary": "...", "left_keep": false, "right_keep": true}`\n'
            '   - 修剪段落: `{"op": "trim", "segment_id": 1, "new_start": 10.0, "new_end": 120.0, "summary": "..."}`\n'
            '   - 重排匯出順序: `{"op": "reorder", "sequence": [5, 1, 2], "only_keep_listed": false}`\n'
            '   - 切換匯出模式: `{"op": "set_export", "mode": "single" | "episodes" | "clips", "min_minutes": 20, "max_minutes": 30}`\n'
            '   - 設定輸出目標: `{"op": "set_output", "output_path": "路徑/目標檔名.mp4"}`\n'
            '   - 更新段落摘要: `{"op": "update_summary", "segment_id": 1, "summary": "...", "tags": ["..."]}`\n'
            "2. 若使用者要求針對某段時間範圍細看畫面（或現有段落太粗、需要先看圖找出切點），請在 `inspect_range` 填入：\n"
            '   `{"start": 起始秒數, "end": 結束秒數, "query": "要尋找或區分的畫面重點", "sample_count": 8}`\n\n'
            "請僅輸出一個 JSON 物件，格式如下：\n"
            "{\n"
            '  "reply": "給使用者的繁體中文回應說明",\n'
            '  "inspect_range": null,\n'
            '  "operations": []\n'
            "}"
        )

        reply_text = self._query_agy_text(
            prompt=planner_prompt,
            image_path=None,
            role="planner",
            timeout=90,
        )
        parsed = self._extract_json(reply_text)
        if isinstance(parsed, dict) and (parsed.get("operations") or parsed.get("inspect_range")):
            return {
                "reply": str(parsed.get("reply", "已根據您的指令更新剪輯計畫。")),
                "inspect_range": parsed.get("inspect_range"),
                "operations": (
                    parsed.get("operations")
                    if isinstance(parsed.get("operations"), list)
                    else []
                ),
            }

        # 本地端規則保底解析
        fallback = self._fallback_parse_dialogue(plan, user_instruction)
        if fallback is not None:
            return fallback

        return {
            "reply": "無法自動解析 AI 規劃回應，請嘗試明確指定段落編號或秒數（例如：刪除段落 2、或細掃 10:00~20:00）。",
            "inspect_range": None,
            "operations": [],
        }

    def _fallback_parse_dialogue(
        self, plan: EditPlan, user_instruction: str
    ) -> Optional[Dict[str, Any]]:
        """本地端啟發式自然語言規則保底解析（當外部 AI CLI 呼叫失敗時使用）。"""
        text = user_instruction.strip()
        operations: List[Dict[str, Any]] = []
        replies: List[str] = []

        # 1. 輸出路徑指令判定 (例如: 輸出檔案設為 "path/to/video.mp4")
        out_match = re.search(
            r"(?:輸出檔案|輸出路徑|輸出至|輸出目標)(?:設為|為|到|[:：])\s*([\"']?([^\"'\r\n]+)[\"']?)",
            text,
        )
        if out_match:
            raw_out_path = out_match.group(2).strip()
            operations.append({"op": "set_output", "output_path": raw_out_path})
            replies.append(f"設定輸出路徑為 '{raw_out_path}'")

        # 2. 匯出模式判定 (例如: 匯出成單一檔、切換為單檔、single)
        if any(kw in text for kw in ("單一檔", "單檔", "合併為單一", "single")):
            operations.append({"op": "set_export", "mode": "single"})
            replies.append("切換匯出模式為單一完整檔 (single)")
        elif any(kw in text for kw in ("分集", "episodes")):
            operations.append({"op": "set_export", "mode": "episodes"})
            replies.append("切換匯出模式為分集 (episodes)")
        elif any(kw in text for kw in ("各段獨立", "片段", "clips")):
            operations.append({"op": "set_export", "mode": "clips"})
            replies.append("切換匯出模式為各段獨立輸出 (clips)")

        # 3. 提取所有段落編號 (例如: #4, #5, 段落 4, 段落5, ID 4)
        found_ids: List[int] = []
        for match in re.finditer(r"(?:#|段落\s*|段\s*|id\s*)?(\d+)", text, re.IGNORECASE):
            val = int(match.group(1))
            if any(seg.id == val for seg in plan.segments) or val <= len(plan.segments) + 5:
                if val not in found_ids:
                    found_ids.append(val)

        is_merge = any(kw in text for kw in ("整合", "合併", "接合", "連起來", "merge"))
        is_only_keep = any(
            kw in text
            for kw in ("只輸出", "只保留", "僅保留", "只留", "只要", "僅輸出", "only")
        )
        is_drop = any(kw in text for kw in ("刪除", "刪掉", "移除", "不要", "drop", "delete"))
        is_keep = (
            any(kw in text for kw in ("保留", "留下", "keep"))
            and not is_only_keep
            and not is_drop
        )

        if is_merge and len(found_ids) >= 2:
            merge_targets = found_ids[:2] if len(found_ids) == 2 else found_ids
            operations.append({"op": "merge", "segment_ids": merge_targets})
            replies.append(f"將段落 {merge_targets} 合併為單一段落")

            if is_only_keep:
                first_id = sorted(merge_targets)[0]
                operations.append({"op": "keep_only", "segment_ids": [first_id]})
                replies.append(f"並設定為僅輸出該整合後的段落 #{first_id}")

        elif is_only_keep and found_ids:
            operations.append({"op": "keep_only", "segment_ids": found_ids})
            replies.append(f"設定為僅保留段落 {found_ids}")

        elif is_drop and found_ids:
            operations.append({"op": "drop", "segment_ids": found_ids})
            replies.append(f"將段落 {found_ids} 設為刪除")

        elif is_keep and found_ids:
            operations.append({"op": "keep", "segment_ids": found_ids})
            replies.append(f"將段落 {found_ids} 設為保留")

        if operations:
            reply_msg = "已依指令完成規劃：" + "，".join(replies) + "。"
            return {
                "reply": reply_msg,
                "inspect_range": None,
                "operations": operations,
            }

        return None
