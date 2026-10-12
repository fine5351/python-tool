"""Video RPA 人機協同介入控制台 (HITL Intervention Controller).

提供執行過程中的非阻塞式監聽介面與懸浮控制視窗，讓使用者在腳本卡住或等待時，
能隨時透過輸入窗告知程式啟用 Agent 進行畫面探索並決定下一步操作。
"""

import logging
import os
import queue
import threading
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class HitlInterventionController:
    """人機協同介入與 Agent 探索控制器 (單例模式)."""

    _instance: Optional["HitlInterventionController"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._intervention_event = threading.Event()
        self._skip_event = threading.Event()
        self._pending_instruction: Optional[str] = None
        self._current_step_name: str = "初始化中"
        self._gui_thread: Optional[threading.Thread] = None
        self._root: Any = None
        self._status_label: Any = None
        self._is_running: bool = False
        self._enable_gui: bool = os.environ.get("RPA_DISABLE_HITL_HUD", "0") != "1"
        self._command_queue: queue.Queue = queue.Queue()

    @classmethod
    def get_instance(cls) -> "HitlInterventionController":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_instance(cls):
        """用於測試重置."""
        with cls._lock:
            if cls._instance:
                cls._instance.close()
            cls._instance = None

    def start_controller_window(self, initial_step: str = "運行中"):
        """在背景執行緒中啟動輕量置頂控制視窗 (HUD)."""
        if not self._enable_gui or self._is_running:
            return

        self._current_step_name = initial_step
        self._is_running = True

        def _run_gui():
            try:
                import tkinter as tk
                from tkinter import messagebox, simpledialog

                root = tk.Tk()
                self._root = root
                root.title("Video RPA 控制台")
                root.geometry("340x120+1450+60")
                root.attributes("-topmost", True)
                root.resizable(False, False)

                # 美化小視窗背景與風格
                root.configure(bg="#212121")

                # 狀態標籤
                status_var = tk.StringVar(value=f"⏳ 當前狀態: {self._current_step_name}")
                self._status_var = status_var

                lbl = tk.Label(
                    root,
                    textvariable=status_var,
                    bg="#212121",
                    fg="#e0e0e0",
                    font=("Segoe UI", 9, "bold"),
                    wraplength=320,
                    justify="left"
                )
                lbl.pack(padx=10, pady=(8, 4), anchor="w")

                # 按鈕容器
                btn_frame = tk.Frame(root, bg="#212121")
                btn_frame.pack(fill="x", padx=10, pady=4)

                def on_call_agent():
                    """點擊召喚 Agent 畫面探索."""
                    prompt = simpledialog.askstring(
                        "啟用 Agent 畫面探索",
                        "請輸入給 Agent 的指示 (或直接按確定以自動分析畫面決定下一步):",
                        initialvalue="畫面疑似卡住，請分析當前畫面並決定下一步操作，例如點擊關閉或確認",
                        parent=root
                    )
                    if prompt is not None:
                        logger.info(f"使用者透過控制視窗啟用 Agent 畫面探索: '{prompt}'")
                        self.trigger_agent_exploration(prompt)

                def on_skip():
                    """手動強制略過或標記完成."""
                    if messagebox.askyesno("強制推進", "是否強制將當前等待步驟標記為完成？", parent=root):
                        logger.info("使用者透過控制視窗手動標記當前步驟為完成。")
                        self.trigger_skip()

                btn_agent = tk.Button(
                    btn_frame,
                    text="🤖 啟用 Agent 畫面探索",
                    bg="#1976d2",
                    fg="#ffffff",
                    activebackground="#1565c0",
                    activeforeground="#ffffff",
                    font=("Segoe UI", 9, "bold"),
                    relief="flat",
                    cursor="hand2",
                    command=on_call_agent
                )
                btn_agent.pack(side="left", expand=True, fill="x", padx=(0, 4))

                btn_skip = tk.Button(
                    btn_frame,
                    text="⏭️ 略過/完成",
                    bg="#424242",
                    fg="#e0e0e0",
                    activebackground="#616161",
                    activeforeground="#ffffff",
                    font=("Segoe UI", 9),
                    relief="flat",
                    cursor="hand2",
                    command=on_skip
                )
                btn_skip.pack(side="right", padx=(4, 0))

                # 處理來自其他線程的更新通知
                def check_queue():
                    try:
                        while True:
                            cmd, args = self._command_queue.get_nowait()
                            if cmd == "update_status":
                                status_var.set(f"⏳ 當前狀態: {args}")
                            elif cmd == "close":
                                root.destroy()
                                return
                    except queue.Empty:
                        pass
                    if self._is_running:
                        root.after(100, check_queue)

                root.after(100, check_queue)
                root.mainloop()

            except Exception as e:
                logger.warning(f"無法啟動 HITL 控制視窗 (可能無桌面環境或 Tkinter 異常): {e}")
            finally:
                self._is_running = False
                self._root = None

        self._gui_thread = threading.Thread(target=_run_gui, daemon=True, name="HitlControllerGuiThread")
        self._gui_thread.start()
        logger.info("已啟動 Video RPA 人機介入控制視窗 (HUD)。")

    def update_status(self, step_name: str):
        """更新控制視窗上顯示的當前步驟狀態."""
        self._current_step_name = step_name
        self._command_queue.put(("update_status", step_name))

    def trigger_agent_exploration(self, instruction: str = ""):
        """設定使用者介入旗標，觸發 Agent 畫面探索."""
        self._pending_instruction = instruction
        self._intervention_event.set()

    def trigger_skip(self):
        """觸發強制跳過或標記完成."""
        self._skip_event.set()

    def is_intervention_requested(self) -> bool:
        """檢查是否有使用者介入請求."""
        return self._intervention_event.is_set()

    def is_skip_requested(self) -> bool:
        """檢查是否有強制跳過請求."""
        return self._skip_event.is_set()

    def consume_intervention(self) -> Optional[str]:
        """取出並清除介入指示."""
        instruction = self._pending_instruction
        self._pending_instruction = None
        self._intervention_event.clear()
        return instruction

    def consume_skip(self) -> bool:
        """取出並清除跳過旗標."""
        if self._skip_event.is_set():
            self._skip_event.clear()
            return True
        return False

    def prompt_user_input_dialog(self, title: str = "人機協同介入", prompt_text: str = "請輸入操作指示:") -> Optional[str]:
        """主動彈出輸入視窗詢問使用者指示 (若環境支援 GUI 則使用 Tkinter 對話框，否則回退到控制台)."""
        result = None
        event = threading.Event()

        def _ask_in_gui():
            nonlocal result
            try:
                import tkinter as tk
                from tkinter import simpledialog

                temp_root = tk.Tk()
                temp_root.withdraw()
                temp_root.attributes("-topmost", True)
                result = simpledialog.askstring(title, prompt_text, parent=temp_root)
                temp_root.destroy()
            except Exception as e:
                logger.warning(f"GUI 輸入視窗彈出失敗: {e}")
                result = None
            finally:
                event.set()

        t = threading.Thread(target=_ask_in_gui, daemon=True)
        t.start()
        event.wait(timeout=30)
        return result

    def close(self):
        """關閉控制視窗並清理資源."""
        self._is_running = False
        self._command_queue.put(("close", None))
        self._intervention_event.clear()
        self._skip_event.clear()
        self._pending_instruction = None
