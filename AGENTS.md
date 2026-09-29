# 專案代理規則 (Workspace Agent Rules)

本文件定義針對本影音編輯工具專案（Video Editor）之開發規範、架構原則與品質防護守則。所有在此專案目錄下運作之代理皆須嚴格遵守。

---

## 1. 專案架構與代碼品質規範 (Architecture & Code Quality)

1. **標準 `src-layout` 結構**：
   - 核心模組位於 `src/video_editor/`，測試套件位於 `tests/`。
   - 禁止在 `src/` 外或專案根目錄散落業務邏輯腳本（`main.py` 僅保留作為簡化啟動進入點）。
2. **型別提示與現代 Python 風格**：
   - 目標 Python 版本為 3.9+，所有公開函式與方法必須具備型別標註（Type Hints）。
   - 配置模型統一以 `dataclasses`（如 `src/video_editor/config.py`）維護，落實不可變性與明確欄位。
3. **跨平台路徑處理**：
   - 專案內部所有檔案路徑一律使用 `pathlib.Path` 物件進行操作。
   - 配置、規則、註解與文字輸出中之檔案引用，**一律使用跨平台相對路徑**（以 POSIX 正斜線 `/` 表示），嚴格禁止寫入特定本機或作業系統絕對路徑。

---

## 2. 影音處理與 FFmpeg 執行守則 (Media Processing & Safety)

1. **無損與極速優先原則 (Stream Copy First)**：
   - 視訊切割時一律優先使用 FFmpeg `-c copy`（流複製技術），避免不必要的重編碼以維持 100% 原始畫質與毫秒級匯出速度。
2. **特徵掃描效能維護 (Coarse-to-Fine Pipeline)**：
   - 第一階段特徵掃描（`freezedetect`、`blackdetect`、`silencedetect`）應保持高效快篩，不進行全片解碼。
3. **暫存資源生命週期管理**：
   - 暫存影格（如截取至 `temp_frames/`）在分析完成或程序異常中斷時，必須確保具備清理機制，防止暫存檔佔滿磁碟。
4. **特殊檔名與空格容錯**：
   - 處理多媒體輸入與輸出路徑時，必須完整支援含有空白、中文、逗號與特殊符號之檔名。

---

## 3. 測試與驗證守則 (Testing & Verification)

1. **演算法可驗證性**：
   - 任何涉及時間軸計算（`calculate_valid_segments`）、切片規劃（`plan_slices`）或檔名命名規則（`export_slices`）之異動，必須在 `tests/test_timeline.py` 中補充對應的單元測試。
2. **測試套件執行**：
   - 驗證修改時，可直接透過沙箱執行 `pytest` 或 `python -m unittest discover tests`。
   - 修改完成前必須確認所有現有單元測試均無迴歸並 100% 通過。

---

## 4. Karpathy 核心工程原則 (Karpathy Guidelines)

1. **動手前先思考 (Think Before Coding)**：實作前明確定義假設與邊界條件，指令不明確時先向使用者確認。
2. **簡潔至上 (Simplicity First)**：嚴格依循 YAGNI，只編寫解決當前問題的最簡代碼，不進行多餘包裝與推測性擴充。
3. **精準修改 (Surgical Changes)**：修改範圍僅限於本次任務，不隨意格式化或重構無關代碼。
4. **目標導向執行 (Goal-Driven Execution)**：以客觀可量化的測試與執行輸出作為完成驗收標準。
