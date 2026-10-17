"""終端機互動式 AI 對話剪輯迴圈模組。"""

from typing import Callable, Optional

from video_editor.config import EditorConfig
from video_editor.models import EditPlan, format_timestamp
from video_editor.verifier import AIVerifier


class InteractiveSession:
    """管理終端機時間軸呈現、模型動態切換與自然語言對話編修的互動工作階段。"""

    def __init__(
        self,
        config: EditorConfig,
        verifier: AIVerifier,
        input_fn: Callable[[str], str] = input,
    ):
        self.config = config
        self.verifier = verifier
        self.input_fn = input_fn

    def render_plan_summary(self, plan: EditPlan) -> str:
        """將當前 EditPlan 格式化為清晰易讀的終端機表格字串。"""
        lines = [
            "",
            "=" * 78,
            f"🎬 影片剪輯計畫總覽: {self.config.video_path.name} "
            f"(總長: {format_timestamp(plan.total_duration)})",
            "-" * 78,
            f"🔧 當前 AI 模型配置: "
            f"fast_vision={self.config.models.fast_vision} | "
            f"deep_vision={self.config.models.deep_vision} | "
            f"planner={self.config.models.planner}",
            f"📦 匯出模式: {plan.export_mode} "
            + (
                f"(單集目標: {plan.target_min_part_len / 60:.0f}~{plan.target_max_part_len / 60:.0f} 分鐘)"
                if plan.export_mode == "episodes"
                else ""
            ),
            "-" * 78,
            "段落清單 (Segments):",
        ]

        for seg in plan.segments:
            status = "✅ [保留]" if seg.keep else "❌ [刪除]"
            cluster_str = (
                f" [相似群組#{seg.visual_cluster}]"
                if seg.visual_cluster is not None
                else ""
            )
            tags_str = f" ({', '.join(seg.tags)})" if seg.tags else ""
            lines.append(
                f"  #{seg.id:<2d} | {status} | "
                f"{format_timestamp(seg.start)} ~ {format_timestamp(seg.end)} "
                f"({seg.duration:5.1f}s){cluster_str}{tags_str} -> {seg.summary}"
            )

        kept_segs = plan.get_kept_ordered_segments()
        kept_ids = [seg.id for seg in kept_segs]
        total_kept_sec = sum(seg.duration for seg in kept_segs)
        lines.extend(
            [
                "-" * 78,
                f"📋 最終匯出順序 (Sequence): {kept_ids}",
                f"⏱️  預計匯出總有效時長: {format_timestamp(total_kept_sec)} "
                f"({total_kept_sec / 60.0:.2f} 分鐘)",
                "=" * 78,
            ]
        )
        return "\n".join(lines)

    def apply_user_instruction(self, plan: EditPlan, instruction: str) -> None:
        """透過 AI 規劃器解析單句自然語言指令，必要時觸發區間細掃並更新計畫。"""
        decision = self.verifier.plan_edits_from_dialogue(plan, instruction)
        reply = decision.get("reply")
        if reply:
            print(f"\n💬 AI 助手: {reply}")

        inspect_req = decision.get("inspect_range")
        if isinstance(inspect_req, dict) and "start" in inspect_req and "end" in inspect_req:
            r_start = float(inspect_req["start"])
            r_end = float(inspect_req["end"])
            r_query = str(inspect_req.get("query") or instruction)
            r_samples = int(inspect_req.get("sample_count", 8))

            subsegments = self.verifier.inspect_time_range(
                start=r_start,
                end=r_end,
                query=r_query,
                sample_count=r_samples,
            )
            created = plan.replace_range_with_subsegments(subsegments)
            if created:
                print(
                    f"✔ 深度視覺細掃完成：已將 {format_timestamp(r_start)} ~ {format_timestamp(r_end)} "
                    f"細分為 {len(created)} 個子段落 {[s.id for s in created]}。"
                )

        ops = decision.get("operations")
        if isinstance(ops, list) and ops:
            logs = plan.apply_operations(ops)
            for log_line in logs:
                print(f"  ✔ {log_line}")

        plan.save(self.config.resolved_plan_file)

    def handle_slash_command(self, cmd_line: str) -> bool:
        """處理內建斜線指令（如 /models 與 /model <role> <name>）。"""
        parts = cmd_line.strip().split()
        if not parts:
            return False

        head = parts[0].lower()
        if head == "/models":
            print(
                "\n🔧 目前各工作職責 AI 模型配置：\n"
                f"  - fast_vision (基礎視覺快篩/場景摘要): {self.config.models.fast_vision}\n"
                f"  - deep_vision (區間放大細掃/拼圖探勘): {self.config.models.deep_vision}\n"
                f"  - planner     (對話意圖推理/時間軸重組): {self.config.models.planner}\n"
                "💡 輸入 `/model <fast_vision|deep_vision|planner> <model_name>` 可即時切換模型。"
            )
            return True

        if head == "/model":
            if len(parts) < 3:
                print(
                    "⚠ 用法: `/model <fast_vision|deep_vision|planner> <model_name>` "
                    "(例如: `/model planner flash`)"
                )
                return True
            role_arg, model_arg = parts[1], parts[2]
            try:
                norm_role = self.config.models.set_model(role_arg, model_arg)
                print(f"✔ 已將 `{norm_role}` 職責的模型切換為: {model_arg}")
            except ValueError as err:
                print(f"⚠ {err}")
            return True

        if head == "/help":
            print(
                "\n📖 互動剪輯指令說明：\n"
                "  - 直接輸入自然語言：例如「刪掉段落 2 和 3，把段落 4 移到最前面並匯出成單一檔」\n"
                "  - 局部放大細掃：例如「幫我細掃 10:00 到 20:00 之間每次重打或切換場景的地方」\n"
                "  - `/models`：檢視目前三個工作職責配置的 AI 模型\n"
                "  - `/model <role> <name>`：即時切換指定職責的模型 (role: fast_vision, deep_vision, planner)\n"
                "  - `export` / `y`：確認當前計畫並開始無損匯出影片\n"
                "  - `quit` / `q`：儲存計畫檔並離開（不匯出影片）"
            )
            return True

        return False

    def run_loop(self, plan: EditPlan) -> bool:
        """執行終端機互動對話迴圈。回傳 True 代表使用者確認執行匯出，False 代表僅儲存離開。"""
        # 若啟動時帶有初始 Prompt，先自動執行一輪 AI 規劃
        if self.config.initial_prompt.strip():
            print(f"\n▶ 套用啟動剪輯指令: 『{self.config.initial_prompt}』")
            self.apply_user_instruction(plan, self.config.initial_prompt.strip())

        plan.save(self.config.resolved_plan_file)

        if self.config.auto_confirm:
            print(self.render_plan_summary(plan))
            print("ℹ 已啟用自動確認 (--yes)，直接進入無損匯出階段。")
            return True

        while True:
            print(self.render_plan_summary(plan))
            print(
                "💡 請輸入自然語言調整剪輯計畫（或輸入 `export`/`y` 開始匯出、`/models` 切換模型、`/help` 說明、`quit` 離開）："
            )
            try:
                user_in = self.input_fn("剪輯指令 > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nℹ 收到中斷訊號，已儲存剪輯計畫並離開。")
                plan.save(self.config.resolved_plan_file)
                return False

            if not user_in:
                continue

            low = user_in.lower()
            if low in ("export", "done", "y", "yes", "開始匯出", "匯出", "確認"):
                plan.save(self.config.resolved_plan_file)
                return True

            if low in ("quit", "exit", "q", "離開"):
                plan.save(self.config.resolved_plan_file)
                print(f"✔ 已儲存剪輯計畫至 '{self.config.resolved_plan_file}'，未執行匯出。")
                return False

            if user_in.startswith("/"):
                if self.handle_slash_command(user_in):
                    continue

            self.apply_user_instruction(plan, user_in)
