# Video Editor (遊戲劇情長片智慧剪輯工具)

以 **Python Best Practice** 架構打造的智慧影音自動化剪輯專案。專門為 4～5 小時的長篇遊戲主線劇情影片設計，結合 **FFmpeg 硬體級快篩** 與 **AGY CLI 多模態 AI 審核**，自動剔除掛機暫離段落，並在 20～30 分鐘區間智慧尋找過場黑/白畫面進行無損分割。

---

##  目錄結構 (Python Best Practice)

本專案遵循現代標準 Python `src-layout` 結構，有效避免 import 命名污染與安裝路徑混淆：

```text
video-editor/
├── .gitignore               # Git 忽略配置（包含輸出影片與暫存檔）
├── pyproject.toml           # 現代 Python 專案打包與依賴規範 (PEP 517/518/621)
├── requirements.txt         # 依賴清單 (主要為開發與測試工具)
├── README.md                # 專案完整繁體中文使用說明
├── src/
│   └── video_editor/        # 核心套件原始碼
│       ├── __init__.py      # 套件入口與版本資訊
│       ├── __main__.py      # 模組執行支援 (python -m video_editor)
│       ├── config.py        # 參數與設定模型 (Dataclass)
│       ├── detector.py      # FFmpeg 快速特徵掃描 (freezedetect / blackdetect)
│       ├── verifier.py      # AGY CLI AI 多模態畫面複審模組
│       ├── cutter.py        # 時間軸演算法與無損切片匯出
│       ├── pipeline.py      # 端到端主流程協同管線
│       └── cli.py           # 命令列參數解析 (CLI Entrypoint)
└── tests/
    ├── __init__.py
    └── test_timeline.py     # 時間軸排除與分割演算法單元測試
```

---

## ⚙️ 核心運作原理 (Coarse-to-Fine Pipeline)

1. **第一階段：FFmpeg 快速特徵掃描（分析不耗時）**
   - 不重新解碼或壓縮，以數十倍速利用 `freezedetect` 抓出連續靜止超過指定門檻（預設 30 秒）的疑似暫離片段。
   - 利用 `blackdetect` 抓出過場讀取造成的黑畫面轉場點。
2. **第二階段：AI 多模態精確複審（防誤判）**
   - 針對掃描出的候選時間點各截取一張關鍵影格。
   - 呼叫 **AGY CLI**（利用 Gemini 多模態能力）判定：
     - **暫離審查**：區分「暫停選單/掛機」vs「角色靜態劇情對話/字幕」，確保珍貴劇情不被誤刪。
     - **切點審查**：確認是否為章節讀取畫面（Loading Screen）或過場轉場。
3. **第三階段：無損智慧切片（秒速匯出）**
   - 排除暫離時間後，計算有效播放長度。
   - 當單集長度達到 20～30 分鐘區間，鎖定由 AI 認證的轉場點作為切割標記。
   - 透過 FFmpeg `-c copy`（Stream Copy）流複製技術，免二次編碼快速秒切出多個 MP4，100% 保留原始音質與畫質。

---

## 🛠️ 環境需求與準備

### 1. 外部工具依賴
- **Python 3.9+**
- **FFmpeg & FFprobe**：
  - 請確認已安裝並加入系統 `PATH` 環境變數。
  - *(若未加入 PATH，亦可在執行時透過 `--ffmpeg-path` 與 `--ffprobe-path` 指定執行檔路徑)*
- **AGY CLI**：
  - 需已登入並具有多模態查詢能力。
  - *(若暫時不想調用 AI，可加上 `--no-ai` 參數純依特徵閾值處理)*

### 2. 安裝與虛擬環境建置

在專案根目錄下建議使用虛擬環境：

```bash
# 建立虛擬環境
python -m venv .venv

# 啟動虛擬環境 (Windows PowerShell)
.venv\Scripts\Activate.ps1

# 安裝專案為可編輯模式 (Editable Mode)
pip install -e .

# 若要執行單元測試，安裝測試套件
pip install -e .[dev]
```

---

##  使用說明與範例

### 1. 快速開始 (預設執行)
```bash
video-editor -i path/to/your_gameplay.mp4
```
或直接透過 Python 模組執行：
```bash
python -m video_editor -i path/to/your_gameplay.mp4
```

### 2. 常用參數範例

- **預先模擬規劃 (Dry-run，只排程不實際剪片)**：
  ```bash
  video-editor -i input.mp4 --dry-run
  ```
- **語音停頓與平滑剪輯參數 (防止講話被截斷或動作做一半)**：
  ```bash
  # 允許最多延後 90 秒等待一句話講完或動作定格 (預設已啟用)
  python main.py -i input.mp4 --max-overtime 90 --silence-noise -30dB --min-silence 0.4
  ```
- **自訂每集時長 (例如：每集 15 ～ 25 分鐘)**：
  ```bash
  python main.py -i input.mp4 --min-part 15 --max-part 25
  ```
- **調整暫離判定門檻 (例如：靜止超過 45 秒才算暫離)**：
  ```bash
  python main.py -i input.mp4 --freeze-threshold 45
  ```
- **純特徵切割 (跳過 AI 多模態複審)**：
  ```bash
  python main.py -i input.mp4 --no-ai
  ```
- **指定自訂的輸出資料夾與 FFmpeg 路徑**：
  ```bash
  python main.py -i input.mp4 -o my_episodes --ffmpeg-path "D:/tools/ffmpeg/bin/ffmpeg.exe"
  ```

---

## 🧪 執行單元測試

專案內附核心時間軸與切片演算法的測試案例：

```bash
pytest
```
