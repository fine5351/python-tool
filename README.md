# Video Editor (通用型 AI 對話式影片剪輯與重組工具)

以 **Python Best Practice** 架構打造的通用型 AI 影音智慧剪輯專案。結合 **FFmpeg 硬體級特徵快篩**、**工作職責三級 AI 模型分流 (Fast Vision / Deep Vision / Planner)** 與 **終端機自然語言互動對話**，支援對任意長影片進行場景摘要索引、局部畫面放大細掃、刪除多餘過程（如失敗重試、無聊跑圖、選單停滯）、自由重組段落順序，並以 **FFmpeg Stream Copy (`-c copy` + `concat demuxer`)** 毫秒級無損匯出。

---

## 🚀 如何啟動與操作指南 (Quick Start)

### Step 1：環境準備

1. **Python 3.9+**（建議安裝 `Pillow` 以啟用視覺相似度分群與縮圖拼圖合成）：
   ```bash
   pip install Pillow
   ```
2. **FFmpeg & FFprobe**：確認已安裝並加入系統 `PATH`（或於啟動時以 `--ffmpeg-path` / `--ffprobe-path` 指定路徑）。
3. **AGY CLI (`agy`)**：確認本機已安裝並登入 `agy`。

---

### Step 2：啟動程式（4 種常用啟動方式）

本專案提供免安裝入口腳本 `main.py`，直接在專案根目錄開啟終端機（PowerShell / CMD / Bash）即可執行：

#### 方式 A：標準互動模式啟動（最常用）
直接指定輸入影片，程式會先自動完成「FFmpeg 快篩 + AI 通用場景索引」，接著進入**終端機互動對話模式**：
```bash
python main.py -i "path/to/your_video.mp4"
```

#### 方式 B：啟動時直接帶入第一句剪輯指令 (`-p` / `--prompt`) + 指定匯出模式 (`--export-mode`)
可在啟動時直接告訴 AI 你的剪輯目標，AI 會先自動調整好一版計畫，再讓你於終端機確認或繼續微調：
```bash
# 範例：刪除重複失敗過程、只留最後成功段落，並設定合併為單一完整 MP4
python main.py -i "path/to/your_video.mp4" --export-mode single -p "把中間重複挑戰失敗的段落刪掉，只保留最後一次成功通關的段落"
```
> 💡 若希望套用 `-p` 指令後**不需人工確認、直接自動匯出影片**，可加上 `-y`（或 `--yes`）：
> ```bash
> python main.py -i "path/to/your_video.mp4" --export-mode single -p "刪掉所有選單與重打過程" -y
> ```

#### 方式 C：自訂三個工作職責使用的 AI 模型啟動
可依預算與精準度需求，分別指定「基礎快篩 (`fast_vision`)」、「區間細掃 (`deep_vision`)」與「對話規劃 (`planner`)」使用的模型：
```bash
python main.py -i "path/to/your_video.mp4" \
  --model-vision-fast flash_lite \
  --model-vision-deep flash \
  --model-planner pro
```

#### 方式 D：載入既有剪輯計畫檔繼續對話微調 (`--plan-file`)
每次分析與對話修改都會自動存成 `output_parts/{原檔名}_edit_plan.json`。若想針對同一部影片重新調整剪輯順序或切點，可直接載入計畫檔，**免重跑 FFmpeg 與初始 AI 掃描**：
```bash
python main.py -i "path/to/your_video.mp4" --plan-file "output_parts/your_video_edit_plan.json"
```

---

### Step 3：終端機互動對話操作範例

啟動後，終端機會顯示目前的**時間軸場景索引表**並出現 `剪輯指令 >` 提示符：

```text
==============================================================================
🎬 影片剪輯計畫總覽: gameplay.mp4 (總長: 45:00.0)
------------------------------------------------------------------------------
🔧 當前 AI 模型配置: fast_vision=flash_lite | deep_vision=flash | planner=pro
📦 匯出模式: episodes (單集目標: 20~30 分鐘)
------------------------------------------------------------------------------
段落清單 (Segments):
  #1  | ✅ [保留] | 00:00.0 ~ 12:30.0 (750.0s) (劇情, 探索) -> 進入遺跡探索與過場動畫
  #2  | ✅ [保留] | 12:30.0 ~ 18:10.0 (340.0s) [相似群組#1] (戰鬥) -> 首領戰第 1 次嘗試，結尾戰敗
  #3  | ✅ [保留] | 18:10.0 ~ 23:40.0 (330.0s) [相似群組#1] (戰鬥) -> 首領戰第 2 次嘗試，中途重來
  #4  | ✅ [保留] | 23:40.0 ~ 31:00.0 (440.0s) [相似群組#1] (戰鬥, 通關) -> 首領戰最終擊破與結算動畫
  #5  | ❌ [刪除] | 31:00.0 ~ 34:20.0 (200.0s) (靜止, 暫離) -> 暫離/靜止畫面
  #6  | ✅ [保留] | 34:20.0 ~ 45:00.0 (640.0s) (劇情) -> 尾聲對話與章節結算
------------------------------------------------------------------------------
📋 最終匯出順序 (Sequence): [1, 2, 3, 4, 6]
⏱️  預計匯出總有效時長: 41:40.0 (41.67 分鐘)
==============================================================================
💡 請輸入自然語言調整剪輯計畫（或輸入 `export`/`y` 開始匯出、`/models` 切換模型、`/help` 說明、`quit` 離開）：
剪輯指令 >
```

在 `剪輯指令 >` 後方，你可以直接輸入**任何自然語言**或**內建斜線指令**：

| 你想做的事 | 在 `剪輯指令 >` 輸入的內容範例 |
| :--- | :--- |
| **刪除不要的段落** | `把第 2 段和第 3 段刪掉，只保留第 4 段` |
| **重組/調換段落順序** | `把第 4 段移到最前面當開場精華，後面再依序接 1, 4, 6` |
| **切分或修剪特定秒數** | `把第 4 段從 29:30 切開，後半段當成獨立段落` 或 `把第 1 段開頭修剪成從 01:15 開始` |
| **局部區間放大細掃（無轉場處找切點）** | `幫我細看 12:30 到 23:40 之間每次重來的時間點並切開` |
| **切換匯出模式** | `改成合併匯出成單一完整檔案`（或 `改成每集 15 到 20 分鐘分集匯出`） |
| **檢視目前 AI 模型配置** | `/models` |
| **即時切換某項工作的模型** | `/model planner flash` 或 `/model deep_vision pro` |
| **確認無誤，開始無損匯出** | `export`（或輸入 `y`、`開始匯出`） |
| **僅儲存計畫檔並離開（不匯出）** | `quit`（或輸入 `q`） |

---

## 🛠️ CLI 完整參數速查表

| 參數 | 預設值 | 說明 |
| :--- | :--- | :--- |
| `-i`, `--input` | *(必填)* | 輸入的影片檔案路徑 |
| `-o`, `--output` | `output_parts` | 影片輸出目錄 |
| `--export-mode` | `episodes` | `episodes`（無縫拼接後依目標時長分集）、`single`（合併為單一檔 `{原檔名}-edited.mp4`）、`clips`（各保留段獨立輸出） |
| `-p`, `--prompt` | `""` | 啟動時自動套用的第一句自然語言剪輯指令 |
| `--plan-file` | 自動命名 | 指定載入或儲存剪輯計畫 JSON 的路徑 |
| `-y`, `--yes` | `False` | 完成初始規劃後直接自動匯出，跳過終端機互動等待 |
| `--model-vision-fast` | `flash_lite` | 基礎視覺快篩與初始場景摘要模型 |
| `--model-vision-deep` | `flash` | 互動對話中觸發區間密集截圖細掃 (`inspect_range`) 的模型 |
| `--model-planner` | `pro` | 自然語言對話推理與時間軸重組規劃模型 |
| `--min-part` / `--max-part` | `20.0` / `30.0` | `episodes` 模式下每集目標最短與最長分鐘數 |
| `--freeze-threshold` | `30.0` | 判定為疑似暫離的連續靜止秒數 |
| `--dry-run` | `False` | 僅執行分析與互動規劃模擬，不實際呼叫 FFmpeg 寫入輸出影片檔 |

---

## 📁 目錄結構

```text
video-editor/
├── main.py                  # 免安裝快速啟動入口 (python main.py -i ...)
├── pyproject.toml           # Python 專案打包與依賴規範
├── requirements.txt         # 開發與測試依賴清單
├── README.md                # 專案完整繁體中文啟動與使用說明
├── src/
│   └── video_editor/        # 核心套件原始碼
│       ├── config.py        # 參數與三級職責模型設定 (EditorConfig / ModelConfig)
│       ├── models.py        # 通用場景段落 (TimelineSegment) 與非線性剪輯計畫 (EditPlan)
│       ├── detector.py      # FFmpeg 快速特徵掃描 (freezedetect / blackdetect / silencedetect)
│       ├── verifier.py      # AGY CLI 多模態場景索引、視覺相似度分群、區間細掃與意圖規劃
│       ├── interactive.py   # 終端機互動對話迴圈與即時模型切換介面
│       ├── cutter.py        # 非線性拼接編譯與無損流複製匯出 (Stream Copy + Concat Demuxer)
│       ├── pipeline.py      # 端到端主流程協同管線
│       └── cli.py           # 命令列參數解析 (CLI Entrypoint)
└── tests/
    ├── test_cli.py          # 命令列參數與路徑處理單元測試
    └── test_timeline.py     # 時間軸計算、三級模型配置與非線性剪輯重組單元測試
```

---

## 🧪 執行單元測試

```bash
python -m unittest discover tests
```
