"""通用時間軸段落與非線性剪輯計畫資料模型。"""

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def format_timestamp(seconds: float) -> str:
    """將秒數格式化為 MM:SS.s 或 HH:MM:SS 字串。"""
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60.0
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:04.1f}"
    return f"{minutes:02d}:{secs:04.1f}"


@dataclass
class TimelineSegment:
    """通用場景時間軸段落模型（不綁定特定情境分類）。"""

    id: int
    start: float
    end: float
    summary: str = "未命名場景段落"
    tags: List[str] = field(default_factory=list)
    visual_cluster: Optional[int] = None
    keep: bool = True

    @property
    def duration(self) -> float:
        """取得段落時長（秒）。"""
        return max(0.0, self.end - self.start)

    def to_dict(self) -> Dict[str, Any]:
        """轉為可序列化字典。"""
        return {
            "id": self.id,
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "summary": self.summary,
            "tags": list(self.tags),
            "visual_cluster": self.visual_cluster,
            "keep": self.keep,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimelineSegment":
        """由字典建立段落實例。"""
        return cls(
            id=int(data["id"]),
            start=float(data["start"]),
            end=float(data["end"]),
            summary=str(data.get("summary", "未命名場景段落")),
            tags=list(data.get("tags", [])),
            visual_cluster=(
                int(data["visual_cluster"])
                if data.get("visual_cluster") is not None
                else None
            ),
            keep=bool(data.get("keep", True)),
        )


@dataclass
class EditPlan:
    """通用非線性影片剪輯計畫模型（支援刪除、修剪、切分、重排順序與多模式匯出）。"""

    video_path: str
    total_duration: float
    segments: List[TimelineSegment] = field(default_factory=list)
    sequence: List[int] = field(default_factory=list)
    export_mode: str = "episodes"
    target_min_part_len: float = 20.0 * 60.0
    target_max_part_len: float = 30.0 * 60.0
    _id_mappings: Dict[int, int] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        """若未指定輸出序列，預設依段落初始順序排列。"""
        if not self.sequence and self.segments:
            self.sequence = [seg.id for seg in self.segments]

    def resolve_id(self, seg_id: int) -> int:
        """解析經合併後的最終段落 ID（處理鏈式映射）。"""
        curr = int(seg_id)
        visited = set()
        while curr in self._id_mappings and curr not in visited:
            visited.add(curr)
            curr = self._id_mappings[curr]
        return curr

    def merge_segments(
        self, segment_ids: List[int], summary: Optional[str] = None
    ) -> TimelineSegment:
        """將多個相鄰的有效段落整合為單一段落，沿用首段 ID 並記錄 ID 映射。"""
        if not segment_ids or len(segment_ids) < 2:
            raise ValueError("合併操作至少需要指定 2 個段落 ID")

        resolved_ids = list(dict.fromkeys(self.resolve_id(int(sid)) for sid in segment_ids))
        if len(resolved_ids) < 2:
            raise ValueError("經 ID 映射後，欲合併的有效段落少於 2 個")

        target_segs = [self.get_segment(sid) for sid in resolved_ids]
        if any(s is None for s in target_segs):
            missing = [sid for sid, s in zip(resolved_ids, target_segs) if s is None]
            raise ValueError(f"找不到要合併的段落 ID: {missing}")

        sorted_segs = sorted(target_segs, key=lambda s: s.start)

        for i in range(len(sorted_segs) - 1):
            gap = sorted_segs[i + 1].start - sorted_segs[i].end
            if gap > 1.0 or gap < -1.0:
                raise ValueError(
                    f"段落 #{sorted_segs[i].id} ({sorted_segs[i].end:.1f}s) 與 "
                    f"#{sorted_segs[i + 1].id} ({sorted_segs[i + 1].start:.1f}s) 不相鄰（間隙 {gap:.1f}s > 1.0s），無法合併"
                )

        first_seg = sorted_segs[0]
        first_id = first_seg.id
        first_seg.end = sorted_segs[-1].end
        first_seg.keep = True

        merged_tags: List[str] = []
        for s in sorted_segs:
            for t in s.tags:
                if t not in merged_tags:
                    merged_tags.append(t)
        first_seg.tags = merged_tags

        if summary is not None and summary.strip():
            first_seg.summary = summary.strip()
        else:
            summaries = [s.summary for s in sorted_segs if s.summary and s.summary.strip()]
            first_seg.summary = " + ".join(summaries) if summaries else first_seg.summary

        for other_seg in sorted_segs[1:]:
            self._id_mappings[other_seg.id] = first_id
            if other_seg in self.segments:
                self.segments.remove(other_seg)

        new_seq: List[int] = []
        for sid in self.sequence:
            res_id = self.resolve_id(sid)
            if self.get_segment(res_id) is not None and res_id not in new_seq:
                new_seq.append(res_id)
        self.sequence = new_seq

        return first_seg

    def keep_only(self, segment_ids: List[int]) -> List[int]:
        """僅保留指定的段落（其餘段落設為 keep=False），並同步更新 sequence。"""
        resolved_targets = {self.resolve_id(int(sid)) for sid in segment_ids}
        valid_targets = {sid for sid in resolved_targets if self.get_segment(sid) is not None}

        for seg in self.segments:
            seg.keep = (seg.id in valid_targets)

        new_seq = [sid for sid in self.sequence if self.resolve_id(sid) in valid_targets]
        dedup_seq = list(dict.fromkeys(new_seq))
        for tid in valid_targets:
            if tid not in dedup_seq:
                dedup_seq.append(tid)
        self.sequence = dedup_seq

        return [seg.id for seg in self.segments if seg.keep]

    def _next_id(self) -> int:
        """產生下一個唯一段落編號。"""
        if not self.segments:
            return 1
        return max(seg.id for seg in self.segments) + 1

    def get_segment(self, seg_id: int) -> Optional[TimelineSegment]:
        """依段落 ID 取得段落物件。"""
        for seg in self.segments:
            if seg.id == seg_id:
                return seg
        return None

    def get_kept_ordered_segments(self) -> List[TimelineSegment]:
        """依 sequence 順序回傳所有標記為 keep=True 的有效段落（支援重組與重複引用）。"""
        ordered: List[TimelineSegment] = []
        for seg_id in self.sequence:
            seg = self.get_segment(seg_id)
            if seg is not None and seg.keep and seg.duration > 0.1:
                ordered.append(seg)
        return ordered

    def get_kept_ordered_ranges(self) -> List[Tuple[float, float]]:
        """依 sequence 順序回傳所有保留段落的 (start, end) 時間區間清單。"""
        return [(seg.start, seg.end) for seg in self.get_kept_ordered_segments()]

    def set_keep(self, seg_ids: List[int], keep: bool) -> List[int]:
        """批次設定指定段落的保留或刪除狀態。"""
        updated: List[int] = []
        for sid in seg_ids:
            seg = self.get_segment(sid)
            if seg is not None:
                seg.keep = bool(keep)
                if keep and sid not in self.sequence:
                    self.sequence.append(sid)
                updated.append(sid)
        return updated

    def trim_segment(
        self,
        seg_id: int,
        new_start: Optional[float] = None,
        new_end: Optional[float] = None,
        summary: Optional[str] = None,
    ) -> TimelineSegment:
        """修剪指定段落的起訖時間與摘要。"""
        seg = self.get_segment(seg_id)
        if seg is None:
            raise ValueError(f"找不到段落 ID: {seg_id}")

        start_val = seg.start if new_start is None else max(0.0, float(new_start))
        end_val = (
            seg.end
            if new_end is None
            else min(self.total_duration, float(new_end))
        )
        if end_val <= start_val:
            raise ValueError(
                f"修剪後的結束時間 ({end_val:.1f}s) 必須大於開始時間 ({start_val:.1f}s)"
            )

        seg.start = start_val
        seg.end = end_val
        if summary is not None and summary.strip():
            seg.summary = summary.strip()
        return seg

    def split_segment(
        self,
        seg_id: int,
        cut_time: float,
        left_summary: Optional[str] = None,
        right_summary: Optional[str] = None,
        left_keep: Optional[bool] = None,
        right_keep: Optional[bool] = None,
    ) -> Tuple[TimelineSegment, TimelineSegment]:
        """在指定秒數將單一段落一分為二，並自動同步更新 sequence 順序。"""
        seg = self.get_segment(seg_id)
        if seg is None:
            raise ValueError(f"找不到段落 ID: {seg_id}")

        if not (seg.start < cut_time < seg.end):
            raise ValueError(
                f"切點 {cut_time:.1f}s 必須落在段落 #{seg_id} 的時間範圍 ({seg.start:.1f}s ~ {seg.end:.1f}s) 內"
            )

        orig_end = seg.end
        orig_summary = seg.summary
        orig_tags = list(seg.tags)
        orig_cluster = seg.visual_cluster
        orig_keep = seg.keep

        seg.end = cut_time
        if left_summary:
            seg.summary = left_summary
        else:
            seg.summary = f"{orig_summary} (前半)"
        if left_keep is not None:
            seg.keep = bool(left_keep)

        new_id = self._next_id()
        right_seg = TimelineSegment(
            id=new_id,
            start=cut_time,
            end=orig_end,
            summary=right_summary if right_summary else f"{orig_summary} (後半)",
            tags=orig_tags,
            visual_cluster=orig_cluster,
            keep=orig_keep if right_keep is None else bool(right_keep),
        )

        # 將新段落插入在原段落正後方
        idx = self.segments.index(seg)
        self.segments.insert(idx + 1, right_seg)

        # 更新輸出序列中的對應位置
        new_seq: List[int] = []
        for sid in self.sequence:
            new_seq.append(sid)
            if sid == seg_id:
                new_seq.append(new_id)
        self.sequence = new_seq

        return seg, right_seg

    def replace_range_with_subsegments(
        self,
        subsegments_data: List[Dict[str, Any]],
    ) -> List[TimelineSegment]:
        """將細掃（inspect_range）產出的多個子段落嵌入時間軸，自動切開或替換重疊的原段落。"""
        if not subsegments_data:
            return []

        sorted_subs = sorted(subsegments_data, key=lambda x: float(x["start"]))
        range_start = float(sorted_subs[0]["start"])
        range_end = float(sorted_subs[-1]["end"])

        created_segments: List[TimelineSegment] = []
        new_segments_list: List[TimelineSegment] = []
        replacement_map: Dict[int, List[int]] = {}

        for seg in self.segments:
            # 完全不重疊的段落直接保留
            if seg.end <= range_start + 0.5 or seg.start >= range_end - 0.5:
                new_segments_list.append(seg)
                continue

            replacement_ids: List[int] = []
            # 若原段落開頭在細掃範圍之前，保留前置殘段
            if seg.start < range_start - 1.0:
                prefix_id = self._next_id() + len(created_segments) + len(new_segments_list)
                prefix_seg = TimelineSegment(
                    id=prefix_id,
                    start=seg.start,
                    end=range_start,
                    summary=f"{seg.summary} (前段)",
                    tags=list(seg.tags),
                    visual_cluster=seg.visual_cluster,
                    keep=seg.keep,
                )
                new_segments_list.append(prefix_seg)
                replacement_ids.append(prefix_id)

            # 在第一個重疊段落處插入細掃出的所有子段落
            if not created_segments:
                base_id = self._next_id() + len(new_segments_list) + 10
                for offset, item in enumerate(sorted_subs):
                    s_start = max(0.0, float(item["start"]))
                    s_end = min(self.total_duration, float(item["end"]))
                    if s_end <= s_start:
                        continue
                    sub_seg = TimelineSegment(
                        id=base_id + offset,
                        start=s_start,
                        end=s_end,
                        summary=str(item.get("summary", "細掃子段落")),
                        tags=list(item.get("tags", [])),
                        visual_cluster=item.get("visual_cluster"),
                        keep=bool(item.get("keep", True)),
                    )
                    created_segments.append(sub_seg)
                    new_segments_list.append(sub_seg)
                    replacement_ids.append(sub_seg.id)

            # 若原段落結尾在細掃範圍之後，保留後置殘段
            if seg.end > range_end + 1.0:
                suffix_id = (
                    self._next_id()
                    + len(created_segments)
                    + len(new_segments_list)
                    + 100
                )
                suffix_seg = TimelineSegment(
                    id=suffix_id,
                    start=range_end,
                    end=seg.end,
                    summary=f"{seg.summary} (後段)",
                    tags=list(seg.tags),
                    visual_cluster=seg.visual_cluster,
                    keep=seg.keep,
                )
                new_segments_list.append(suffix_seg)
                replacement_ids.append(suffix_id)

            replacement_map[seg.id] = replacement_ids

        self.segments = new_segments_list

        # 同步更新 sequence
        updated_seq: List[int] = []
        inserted_created = False
        for sid in self.sequence:
            if sid in replacement_map:
                for rid in replacement_map[sid]:
                    if rid not in updated_seq:
                        updated_seq.append(rid)
                inserted_created = True
            elif self.get_segment(sid) is not None:
                updated_seq.append(sid)

        if not inserted_created and created_segments:
            updated_seq.extend(s.id for s in created_segments)

        self.sequence = updated_seq
        return created_segments

    def reorder(
        self, new_sequence: List[int], only_keep_listed: bool = False
    ) -> List[int]:
        """重新排列段落輸出順序（支援調換順序或重複引用同段落）。"""
        valid_seq = [
            int(sid)
            for sid in new_sequence
            if self.get_segment(int(sid)) is not None
        ]
        if not valid_seq:
            raise ValueError("重排後的 sequence 未包含任何有效的段落 ID")

        self.sequence = valid_seq
        for sid in valid_seq:
            seg = self.get_segment(sid)
            if seg is not None:
                seg.keep = True

        if only_keep_listed:
            listed_set = set(valid_seq)
            for seg in self.segments:
                if seg.id not in listed_set:
                    seg.keep = False

        return self.sequence

    def set_export_mode(
        self,
        mode: str,
        min_minutes: Optional[float] = None,
        max_minutes: Optional[float] = None,
    ) -> None:
        """設定匯出模式與目標分集時長。"""
        clean_mode = mode.strip().lower()
        if clean_mode not in ("episodes", "single", "clips"):
            raise ValueError(
                f"不支援的匯出模式 '{mode}'（可用: episodes, single, clips）"
            )
        self.export_mode = clean_mode
        if min_minutes is not None and float(min_minutes) > 0:
            self.target_min_part_len = float(min_minutes) * 60.0
        if max_minutes is not None and float(max_minutes) > 0:
            self.target_max_part_len = float(max_minutes) * 60.0

    def apply_operations(self, operations: List[Dict[str, Any]]) -> List[str]:
        """批次執行由 Planner AI 產生的非線性時間軸編輯指令，並回傳變更紀錄。"""
        logs: List[str] = []
        for op_data in operations:
            op_type = str(op_data.get("op", "")).strip().lower()
            try:
                if op_type == "merge":
                    raw_ids = [int(x) for x in op_data.get("segment_ids", [])]
                    merged_seg = self.merge_segments(raw_ids, summary=op_data.get("summary"))
                    logs.append(
                        f"已將段落 {raw_ids} 合併為段落 #{merged_seg.id} "
                        f"({format_timestamp(merged_seg.start)} ~ {format_timestamp(merged_seg.end)})"
                    )

                elif op_type in ("keep_only", "only_keep"):
                    raw_ids = [int(x) for x in op_data.get("segment_ids", [])]
                    if "segment_id" in op_data and op_data["segment_id"] is not None:
                        raw_ids.append(int(op_data["segment_id"]))
                    kept = self.keep_only(raw_ids)
                    logs.append(f"已將剪輯計畫設為僅保留段落 {kept}")

                elif op_type in ("keep", "drop", "set_keep"):
                    ids = [self.resolve_id(int(x)) for x in op_data.get("segment_ids", [])]
                    if "segment_id" in op_data and op_data["segment_id"] is not None:
                        ids.append(self.resolve_id(int(op_data["segment_id"])))
                    keep_val = (
                        True
                        if op_type == "keep"
                        else (
                            False
                            if op_type == "drop"
                            else bool(op_data.get("keep", True))
                        )
                    )
                    updated = self.set_keep(ids, keep_val)
                    action_str = "保留" if keep_val else "刪除"
                    logs.append(f"已將段落 {updated} 設為【{action_str}】")

                elif op_type == "split":
                    sid = self.resolve_id(int(op_data["segment_id"]))
                    cut_t = float(op_data["cut_time"])
                    left_s, right_s = self.split_segment(
                        seg_id=sid,
                        cut_time=cut_t,
                        left_summary=op_data.get("left_summary"),
                        right_summary=op_data.get("right_summary"),
                        left_keep=op_data.get("left_keep"),
                        right_keep=op_data.get("right_keep"),
                    )
                    logs.append(
                        f"已於 {format_timestamp(cut_t)} ({cut_t:.1f}s) 將段落 #{sid} 切分為 #{left_s.id} 與 #{right_s.id}"
                    )

                elif op_type == "trim":
                    sid = self.resolve_id(int(op_data["segment_id"]))
                    seg = self.trim_segment(
                        seg_id=sid,
                        new_start=op_data.get("new_start"),
                        new_end=op_data.get("new_end"),
                        summary=op_data.get("summary"),
                    )
                    logs.append(
                        f"已修剪段落 #{sid} 時間範圍為 {format_timestamp(seg.start)} ~ {format_timestamp(seg.end)}"
                    )

                elif op_type == "reorder":
                    seq = [self.resolve_id(int(x)) for x in op_data.get("sequence", [])]
                    only_listed = bool(op_data.get("only_keep_listed", False))
                    new_seq = self.reorder(seq, only_keep_listed=only_listed)
                    logs.append(f"已更新段落匯出順序為: {new_seq}")

                elif op_type in ("set_export", "export_mode"):
                    mode = str(op_data.get("mode", self.export_mode))
                    min_m = op_data.get("min_minutes")
                    max_m = op_data.get("max_minutes")
                    self.set_export_mode(mode, min_minutes=min_m, max_minutes=max_m)
                    logs.append(f"已切換匯出模式為: {self.export_mode}")

                elif op_type in ("set_output", "output"):
                    out_path = op_data.get("output_path", "")
                    logs.append(f"設定輸出目標為: {out_path}")

                elif op_type == "update_summary":
                    sid = self.resolve_id(int(op_data["segment_id"]))
                    seg = self.get_segment(sid)
                    if seg is not None:
                        if "summary" in op_data:
                            seg.summary = str(op_data["summary"])
                        if "tags" in op_data and isinstance(op_data["tags"], list):
                            seg.tags = [str(t) for t in op_data["tags"]]
                        logs.append(f"已更新段落 #{sid} 的摘要與標籤")
            except Exception as err:
                logs.append(f"執行操作 '{op_type}' 時發生警告: {err}")

        return logs

    def to_dict(self) -> Dict[str, Any]:
        """序列化為字典結構。"""
        return {
            "video_path": self.video_path,
            "total_duration": round(self.total_duration, 2),
            "export_mode": self.export_mode,
            "target_min_part_len": self.target_min_part_len,
            "target_max_part_len": self.target_max_part_len,
            "sequence": list(self.sequence),
            "segments": [seg.to_dict() for seg in self.segments],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EditPlan":
        """由字典結構反序列化還原 EditPlan。"""
        segments = [
            TimelineSegment.from_dict(item) for item in data.get("segments", [])
        ]
        sequence = [int(x) for x in data.get("sequence", [])]
        return cls(
            video_path=str(data.get("video_path", "")),
            total_duration=float(data.get("total_duration", 0.0)),
            segments=segments,
            sequence=sequence,
            export_mode=str(data.get("export_mode", "episodes")),
            target_min_part_len=float(data.get("target_min_part_len", 1200.0)),
            target_max_part_len=float(data.get("target_max_part_len", 1800.0)),
        )

    def save(self, path: Path) -> Path:
        """將剪輯計畫儲存為 JSON 檔案。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        return path

    @classmethod
    def load(cls, path: Path) -> "EditPlan":
        """從 JSON 檔案載入剪輯計畫。"""
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)
