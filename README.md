# Jev 通用遊戲 Agent (Universal Game Agent - Jev System 1 + Gemini 3.8 Flash)

基於 **TypeSafe AI Jev (System 1 決策核心)** 與 **Google Gemini 3.8 Flash (System 2 輔助認知)** 的 Windows 桌面通用即時遊戲 Agent。專為米哈遊系列遊戲（**《原神》**、**《崩壞：星穹鐵道》**、**《絕區零》**）與**泛用遊戲模式**設計，具備以 Strategy Pattern 建立的無限擴充能力，支援固定每 0.25 秒（4 Hz）畫面流即時分析、實時操作指導、螢幕代替操作、戰況資料分析與雙向語音互動。

---

## 🌟 核心特色與架構革新 (Key Features)

### 1. 雙系統認知與反應架構 (Dual-System Architecture)
- ⚡ **Jev 決策核心 (System 1 - Fast Reflex)**：
  - 由 TypeSafe AI Jev 模型驅動，非自回歸（Non-autoregressive）結構化單 Pass 決策。
  - 固定以 **0.25 秒（4 Hz）** 極速分析當前遊戲畫面與戰況特徵。
  - 支援 `Choice`（動作選擇）、`Noul`（布林判定，如攻擊前搖閃避）、`Score`（緊急度打分），延遲僅 70~500ms，徹底突破傳統 LLM 需耗時 2~5 秒無法即時操作的瓶頸。
- 🧠 **Gemini 3.8 Flash 輔助認知 (System 2 - Slow Thinking & Reasoning)**：
  - 全面遷移至最新世代的 **`gemini-3.8-flash`**（具備 1M Token 上下文與 64K Output，針對 Agentic 自主工作流特化）。
  - 原生語意化思考深度控制 (`thinking_level`: `MINIMAL` / `LOW` / `MEDIUM` / `HIGH`)：語音翻譯採取 `MINIMAL` 極速確定性輸出；戰術拆解與深度畫面剖析採取 `MEDIUM` / `HIGH` 深度慢思考，完美平衡延遲與高維認知。
  - 原生支援結構化 JSON 輸出與多模態即時畫面直讀，將宏觀目標精確拆解為 Jev 可執行的戰術指示（Directive）。

### 2. 策略模式架構 (Strategy Pattern)
將遊戲輔助能力全面解耦為獨立 Strategy 類別，並由 `StrategyRegistry` 統一管理，保有極佳的未來遊戲擴充能力：
- 🗡️ **原神策略 (`GenshinStrategy`)**：
  - 元素反應鏈分析（蒸發、融化、超綻放、超激化、凍結）。
  - 四人隊伍切人循環（1-4 號位）與技能施放時機（E / Q / 普攻連招）。
  - 衝刺無敵幀閃避敵方高威脅前搖。
- 🚂 **崩壞：星穹鐵道策略 (`StarRailStrategy`)**：
  - 戰技點 (SP) 餘額預測與主副 C 資源調配。
  - 終結技（鍵盤 1-4）即時插隊破韌與防禦救急。
  - 弱點屬性打擊與模擬宇宙/差分宇宙事件最佳路徑。
- ⚡ **絕區零策略 (`ZZZStrategy`)**：
  - 毫秒級光芒前搖辨識：**黃光**觸發極限切人支援招架（Space / C），**紅光**觸發極限閃避（Shift / 右鍵）。
  - 敵方失衡值 (Daze) 監控與連攜技 (Chain Attack QTE 左/右代理人) 選擇。
  - EX 強化特殊技 (E) 與終結技 (Q) 爆發。
- 🎮 **泛用遊戲策略 (`GeneralGameStrategy`)**：
  - 提供通用的 WASD、滑鼠主副操作、技能 (Q/E/R/F/1-4)、跳躍與翻滾閃避。
  - **未來擴充能力**：新增任意新遊戲只需繼承 `BaseGameStrategy` 並註冊至 `StrategyRegistry`，無需變動核心迴圈。

### 3. 全方位遊戲輔助需求能力 (All-in-One Capabilities)
- 💡 **操作指導 (Guidance HUD)**：在透明面板上實時呈現最佳按鍵、技能連招與閃避提示，搭配可選離線語音播報 (TTS)。
- 🤖 **代替操作 (Autonomous Screen Play)**：透過 `ScreenActuator` 實體模擬鍵盤與滑鼠按鍵，實現自動格擋、自動放招與閃避。
- 📊 **資料分析 (Data & Stats)**：每 0.25 秒記錄戰鬥遙測（威脅度、反應速度、SP 波動、技能循環），即時匯出統計報告。
- 🎤 **語音指令發問 (Voice Interaction)**：按下 `F11` 口述發問，先由 Gemini 3.8 Flash 解析戰術意圖，再接入 Jev 0.25 秒迴圈執行。

### 4. 安全熔斷機制 (Safety Killswitch)
- 🛑 **`F8` 緊急安全停止**：無論處於何種代替操作狀態，按下 **`F8`** 鍵立即強制解除所有按鍵與滑鼠模擬，並切回安全的操作指導模式。

---

## 📁 專案架構 (Modern Python `src/` Layout)

本專案遵循現代 Python 官方與社群最佳實踐（PEP 517 / 518 / 621 標準與 `src/` layout）：

```
game-assistant/
├── pyproject.toml              # 現代化 PEP 621 專案建置與依賴配置 (含 console_scripts)
├── requirements.txt            # 相容性依賴清單
├── main.py                     # 根目錄相容啟動器 (支援直接 python main.py 執行)
├── README.md                   # 專案說明與操作指南
├── AGENTS.md                   # 代理工程規則與規範
├── task.md                     # 任務清單與進度追蹤
├── src/
│   └── game_assistant/         # 核心套件 (game_assistant)
│       ├── __init__.py         # 套件版本 (v0.2.0) 與核心 API 統一匯出
│       ├── __main__.py         # 支援 python -m game_assistant 啟動
│       ├── cli.py              # console_scripts 進入點 (game-assistant 指令)
│       ├── app.py              # PyQt6 應用排程控制器與非同步 QThread Worker 群
│       ├── core/               # 核心 Agent 協調器與系統組態
│       │   ├── __init__.py
│       │   ├── agent.py        # UniversalGameAgent 通用遊戲 Agent 核心協調器
│       │   └── config.py       # Jev / Gemini 設定、0.25s 輪詢、熱鍵與 Prompt 範本
│       ├── engines/            # 雙系統 AI 決策與輔助認知引擎
│       │   ├── __init__.py
│       │   ├── jev_engine.py   # TypeSafe Jev (System 1) 決策引擎 (SDK / REST / 確定性降級)
│       │   └── ai_engine.py    # Gemini 3.8 Flash (System 2) 輔助認知與使用者意圖拆解
│       ├── ui/                 # 視覺介面與熱鍵監聽
│       │   ├── __init__.py
│       │   └── gui.py          # PyQt6 置頂懸浮 Overlay 視窗 (HUD 決策卡片與 F8 急停按鈕)
│       ├── audio/              # 語音處理模組
│       │   ├── __init__.py
│       │   ├── tts_engine.py   # Windows SAPI5 離線語音朗讀
│       │   └── stt_engine.py   # SpeechRecognition 麥克風擷取與繁中 STT
│       ├── utils/              # 工具與周邊致動服務
│       │   ├── __init__.py
│       │   ├── screen_capture.py # mss 與 Pillow 超低延遲畫面擷取 (BitBlt 防禦降級)
│       │   └── input_actuator.py # 螢幕操作致動器 (鍵盤/滑鼠模擬、F8 急停、冷卻防洪保護)
│       └── strategies/         # 策略模式遊戲套件
│           ├── __init__.py
│           ├── base.py         # BaseGameStrategy 策略抽象基底類別
│           ├── genshin.py      # 原神策略 (元素反應、四人循環、無敵幀閃避)
│           ├── star_rail.py    # 崩壞：星穹鐵道策略 (SP 配額、終結技插隊)
│           ├── zzz.py          # 絕區零策略 (黃光招架、紅光閃避、失衡 QTE)
│           ├── general.py      # 泛用遊戲策略 (WASD、滑鼠攻擊、通用技能)
│           └── registry.py     # StrategyRegistry 策略工廠與動態註冊中心
└── tests/                      # 單元測試與驗證套件 (獨立於 src 外)
    ├── __init__.py
    ├── test_translation.py     # 語文翻譯與即時字幕測試套件 (36 個測試案例)
    └── test_universal_agent.py # 通用 Agent 核心測試套件 (44 個測試案例)
```

---

## 🛠️ 安裝與快速開始 (Installation & Quick Start)

### 1. 環境要求
- 作業系統：Windows 10 / 11
- Python 版本：Python 3.10+
- 音訊設備：可用麥克風與耳機/喇叭

### 2. 安裝套件

可使用以下任一種方式安裝：

**方式 A：標準套件可編輯安裝（推薦最佳實踐）**
```bash
pip install -e .
```

**方式 B：傳統 requirements 安裝**
```bash
pip install -r requirements.txt
```

### 3. 配置 API Key (可選)
於專案根目錄下的 `.env` 設定金鑰：
```env
# TypeSafe Jev (System 1 決策核心)
TYPESAFE_API_KEY=your_typesafe_api_key

# Google Gemini 3.8 Flash (System 2 輔助認知)
GEMINI_API_KEY=your_gemini_api_key
```
*備註：若未填寫金鑰，Jev 決策核心會自動切換為本地確定性啟發決策器 (Local Heuristics)，系統仍可正常運作。*

### 4. 執行測試套件
```bash
# 使用 unittest 自動發現執行完整 80 項測試 (包含 44 項通用核心與 36 項翻譯測試)
python -m unittest discover -s tests

# 或分別執行測試模組
python tests/test_universal_agent.py
python tests/test_translation.py
```

### 5. 啟動通用遊戲 Agent

重構後支援多元標準啟動方式：

**方式 A：Console Script 命令行啟動（套件安裝後）**
```bash
game-assistant
```

**方式 B：Python 模組模式啟動**
```bash
python -m game_assistant
```

**方式 C：根目錄相容啟動器直接執行**
```bash
python main.py
```

---

## ⌨️ 全域熱鍵一覽 (Hotkeys Reference)

| 熱鍵 | 功能說明 |
| :--- | :--- |
| **`F6`** | **💬 中文語音翻譯並自動輸入 (Voice Translation)**：聆聽玩家中文語音，轉譯為外語 (英文/日文/韓文等) 並代替操作貼上至遊戲聊天框。 |
| **`F7`** | **🌐 外文畫面與對話即時翻譯 (Screen Translation)**：擷取遊戲畫面，深度解析外文 UI 選單、任務、劇情字幕與對話框並顯示翻譯與浮動字幕。 |
| **`F8`** | **🛑 緊急安全急停 (Killswitch)**：立即終止代替操作，解除所有鍵盤滑鼠動作，切回指導模式。 |
| **`F9`** | **⚡ 切換 0.25 秒高頻實時決策輪詢**：啟動 / 暫停固定 4 Hz 畫面決策迴圈。 |
| **`F10`** | **📸 手動快照深度分析**：調用 Gemini 3.8 Flash 進行深層畫面視覺解析與裝備評估。 |
| **`F11`** | **🎤 語音指令發問 (STT)**：口述需求（如「幫我閃避攻擊」），由 Gemini 處理後接入 Jev 執行。 |

---

## ⚠️ 免責聲明 (Disclaimer)

本工具為外掛式畫面讀取與操作輔助工具，僅透過 OS 螢幕擷取 API (`mss`) 與標準作業系統輸入模擬 (`pynput`) 運作，**不包含**任何記憶體修改、反編譯、封包改寫或遊戲程式碼注入行為。請遵守各遊戲之使用者協議與規範。
