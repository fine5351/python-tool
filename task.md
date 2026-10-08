# Jev 通用遊戲 Agent 升級實作任務列表 (task.md)

## 第一階段：核心模型與設定重構
- [x] 任務 1: 研究 TypeSafe AI 新發布之 Jev (System 1) 基礎決策模型特性與即時遊戲輔助實現路徑 (Dual-System 架構)
- [x] 任務 2: 升級 `config.py`，配置 Jev 相關參數 (`TYPESAFE_API_KEY`, `JEV_MODEL_NAME`, `JEV_API_URL`)、將 Gemini 升級至 `gemini-3.8-flash`、固定每 0.25 秒畫面決策輪詢 (`DEFAULT_POLL_INTERVAL = 0.25`)、配置 `AssistCapability` 與 `F8` 急停熱鍵
- [x] 任務 3: 實作 `jev_engine.py`，提供 Jev System 1 決策引擎 (支援 Choice, Noul, Score 結構化決策、官方 SDK、REST API 與本地啟發式決策器三重降級)
- [x] 任務 4: 實作 `input_actuator.py`，封裝 `ScreenActuator` 支援實體鍵盤與滑鼠模擬、F8 安全熔斷急停與操作冷卻防洪

## 第二階段：策略模式重構 (Strategy Pattern)
- [x] 任務 5: 建立 `strategies/base.py`，定義 `BaseGameStrategy` 抽象類別、`TelemetryData`、`StrategyDecision` 與 `ActionResult`
- [x] 任務 6: 實作 `strategies/genshin.py`，建立《原神》策略 (元素反應鏈、四人循環切人 E/Q/A、無敵幀閃避)
- [x] 任務 7: 實作 `strategies/star_rail.py`，建立《崩壞：星穹鐵道》策略 (戰技點 SP 配額、1-4 終結技插隊破韌)
- [x] 任務 8: 實作 `strategies/zzz.py`，建立《絕區零》策略 (黃光招架 Space/C、紅光閃避 Shift、失衡連攜技 QTE)
- [x] 任務 9: 實作 `strategies/general.py`，建立《泛用遊戲》策略 (通用 WASD、滑鼠操作與技能)
- [x] 任務 10: 實作 `strategies/registry.py`，建立 `StrategyRegistry` 支援動態註冊與未來任意新遊戲的無縫擴充
- [x] 任務 11: 建立 `strategies/__init__.py` 統一匯出

## 第三階段：通用遊戲 Agent 與雙系統認知整合
- [x] 任務 12: 重構 `ai_engine.py` 為 `GeminiAuxiliaryEngine`，擔當 System 2 輔助認知層，優先處理玩家需求意圖拆解 (`decompose_user_demand`) 與深度視覺分析
- [x] 任務 13: 實作 `agent.py`，建立 `UniversalGameAgent` 整合感知 (ScreenCapturer)、認知 (Gemini 3.8 Flash)、決策 (Jev System 1)、策略 (Strategy Pattern) 與致動 (ScreenActuator)
- [x] 任務 14: 升級 `gui.py`，呈現 Jev System 1 實時決策 HUD 卡片、0.25 秒高頻決策控制、輔助能力切換 (操作指導/代替操作/資料分析) 與 F8 急停按鈕
- [x] 任務 15: 重構 `main.py`，建立 0.25s `JevLoopWorker`、非同步 `GeminiIntentWorker`、`DeepVisionWorker`，實現 4 Hz 高頻決策與無阻塞 UI
- [x] 任務 16: 強化 `screen_capture.py`，增加 BitBlt 異常防禦與安全降級畫面，杜絕無授權會話下崩潰

## 第四階段：驗證、審查修正與說明文件
- [x] 任務 17: 實作 `test_universal_agent.py`，撰寫 32 個覆蓋 Jev、Gemini、各遊戲策略、動態擴充、代替操作、急停鍵位釋放、冷卻防洪、資料分析與邊界情境的自動化單元測試，全部驗證通過
- [x] 任務 18: 審查修正與防禦強化：
  - 修正 F8 急停開關 (Killswitch) 真實按鍵與滑鼠釋放邏輯，杜絕按鍵卡死在 Windows 系統
  - 修正致動器冷卻時間多執行緒競態條件 (Race Condition)
  - 修正 GUI 面板在 0.25 秒高頻下 setMarkdown 重繪閃爍與滾動條頻繁重設問題，支援深度分析與語音解析鎖定展示
  - 完整串接 `DATA_ANALYSIS` 輔助能力至 0.25 秒實時迴圈與所有策略遙測問題
  - 強化 Gemini 意圖拆解 Worker，於呼叫前擷取即時螢幕畫面注入視覺上下文
  - 強化語音需求處理流程，於 Gemini 完成意圖拆解後立即自動接入 Jev 觸發決策
  - 修正 `TTSEngine.stop()` 支援即時中止語音播報
  - 強化 `Choice`、`Noul`、`Score` 同時完整相容 TypeSafe 官方 SDK 與 REST API Schema
- [x] 任務 19: 執行全專案 17 個 Python 模組 `python -m py_compile` 語法編譯檢查零錯誤
- [x] 任務 20: 更新 `requirements.txt` 加入 `typesafe-sdk>=0.1.0`
- [x] 任務 21: 更新 `README.md`，提供完整架構說明、0.25s 實時操作指南與全域熱鍵說明

## 第五階段：專案目錄結構 Package 化重構 (Package Modularization)
- [x] 任務 22: 建立 `core/`、`engines/`、`ui/`、`audio/`、`utils/`、`tests/` 套件目錄與 `__init__.py`
- [x] 任務 23: 透過 `git mv` 遷移根目錄平鋪之模組至各職責套件：
  - `agent.py`, `config.py` -> `core/`
  - `jev_engine.py`, `ai_engine.py` -> `engines/`
  - `gui.py` -> `ui/`
  - `tts_engine.py`, `stt_engine.py` -> `audio/`
  - `screen_capture.py`, `input_actuator.py` -> `utils/`
  - `test_universal_agent.py` -> `tests/`
- [x] 任務 24: 更新全專案跨模組 import 引用（包含 `main.py`、`tests/`、`strategies/`、各子套件），並加入模組獨立執行路徑備援
- [x] 任務 25: 執行完整 32 項單元測試、模組語法檢查與各子模組獨立執行驗證，確認 100% 通過
- [x] 任務 26: 同步更新 `README.md` 與 `AGENTS.md` 之架構說明與驗證指令清單

## 第六階段：現代 Python 最佳實踐結構重構 (Modern Python Best Practice & `src/` Layout)
- [x] 任務 27: 建立標準 `src/` layout 結構 (`src/game_assistant/`) 並透過 `git mv` 將子套件遷移至主要套件命名空間：
  - `src/game_assistant/core/`
  - `src/game_assistant/engines/`
  - `src/game_assistant/ui/`
  - `src/game_assistant/audio/`
  - `src/game_assistant/utils/`
  - `src/game_assistant/strategies/`
- [x] 任務 28: 建立 `src/game_assistant/__init__.py`，定義套件版本號 (`0.2.0`) 並統一匯出核心 API 與子模組
- [x] 任務 29: 實作 `src/game_assistant/app.py`，完整封裝 `GameAssistantController` 與 5 組非同步 `QThread` Worker 執行緒群
- [x] 任務 30: 建立 `src/game_assistant/cli.py` 提供 `main()` 進入點，並建立 `src/game_assistant/__main__.py` 支援 `python -m game_assistant` 啟動
- [x] 任務 31: 配置現代化 `pyproject.toml`，遵循 PEP 517/518/621 標準，配置相依套件、`setuptools` `src` layout 套件發現與 `game-assistant` console_scripts 進入點
- [x] 任務 32: 重構根目錄 `main.py` 為輕量相容性啟動器，注入 `src/` 至 `sys.path` 並轉發調用 `game_assistant.cli:main`，確保直接執行 `python main.py` 100% 相容
- [x] 任務 33: 全面更新全專案所有模組 import 引用為 `game_assistant.*` 標準絕對路徑引用，並保留各子模組獨立執行路徑備援防護
- [x] 任務 34: 更新 `tests/` 單元測試套件路徑與匯出介面測試，擴充至 42 個測試案例（新增套件元資料、CLI 進入點、Controller 匯出等），全部 100% 通過
- [x] 任務 35: 驗證 `pip install -e .` 可編輯安裝成功，產生 `game-assistant.exe` console_scripts 執行檔並測試各子模組獨立執行皆正常
- [x] 任務 36: 同步更新 `README.md` 與 `AGENTS.md` 架構圖、安裝模式與指令說明

## 第七階段：審查修正、強健性強化與最佳實踐深度驗證 (Review Fixes & Deep Robustness)
- [x] 任務 37: 修正 `StrategyRegistry.get()` 比對自訂字串 key 時的 `AttributeError`，並在測試中增加 `finally` 恢復註冊中心預設狀態，徹底修復 `pytest` 下測試失敗問題
- [x] 任務 38: 修正 `pyproject.toml` 與 `requirements.txt` 中 `pywin32` 依賴缺少 PEP 508 環境標記問題（加入 `; sys_platform == 'win32'`），確保跨平台打包與安裝相容性
- [x] 任務 39: 為 `src/game_assistant/cli.py` 整合標準 `argparse`，支援 `-v/--version` 與 `-h/--help` 命令行標準輸出與優雅退出，避免命令行參數錯誤啟動 GUI
- [x] 任務 40: 消除 7 個內部套件模組中全域侵入性 `sys.path.insert(0, ...)`，加入 `if __name__ == "__main__" and not __package__:` 防護，維護標準函式庫隔離性
- [x] 任務 41: 全面強化策略模式與 Gemini 引擎中對 `capability` 為字串或枚舉時的相容處理 (`getattr(capability, "value", str(capability))`)
- [x] 任務 42: 擴充單元測試至 44 項，涵蓋 CLI argparse、`pyproject.toml` PEP 621 設定與未知遊戲降級機制，`pytest` 與 `unittest` 雙測試套件 100% 通過

## 第八階段：遊戲輔助功能「語文翻譯能力」擴充與驗證 (Translation & Live Subtitles)
- [x] 任務 43: 配置翻譯功能核心常數、列舉與 Prompt 範本 (`config.py`)：新增 `HOTKEY_VOICE_TRANSLATE` (F6)、`HOTKEY_TRANSLATE_SCREEN` (F7)、`DEFAULT_TARGET_LANGUAGE`、`AssistCapability.TRANSLATION`、`AnalysisMode.TRANSLATION` 與各遊戲專屬外文翻譯提示詞範本
- [x] 任務 44: 擴充致動器文字輸入能力 (`input_actuator.py`)：實作 `copy_to_clipboard` (Pyperclip / Win32 API 雙重降級) 與 `paste_text_to_chat` (模擬開啟聊天框、Ctrl+V 貼上、Enter 發送與 force 強制模式)
- [x] 任務 45: 擴充 Gemini 輔助認知引擎多模態翻譯 (`ai_engine.py`)：實作 `translate_screen` (外文介面/選單/劇情/聊天 Markdown 對照)、`translate_chat_subtitles` (JSON 字幕抽取與對話即時翻譯) 與 `translate_voice_text` (玩家繁中語音即時轉譯外語，含離線常用遊戲字典對照降級)
- [x] 任務 46: 實作 UniversalGameAgent 翻譯協調介面 (`agent.py`)：整合畫面外文視覺翻譯 (`translate_screen`) 與中文語音翻譯並自動發送至遊戲聊天框 (`translate_voice_to_chat`)
- [x] 任務 47: 實作置頂浮動翻譯字幕視窗與主介面翻譯控制列 (`gui.py`)：
  - 建立 `FloatingSubtitleOverlay`：支援無邊框滑鼠拖曳、置頂半透明、高對比發光字幕、自動逾時隱藏
  - 擴充 `GameAssistantOverlay`：新增 F7 畫面翻譯按鈕、F6 語音翻譯輸入按鈕、目標外語切換下拉選單 (英文/日文/韓文/俄文)、翻譯檢視專屬鎖定模式防重繪閃爍
  - 擴充 `HotkeyListener`：全域監聽 F6 與 F7 快捷鍵訊號
- [x] 任務 48: 實作非同步翻譯 Worker 執行緒群與控制器整合 (`app.py`)：
  - 建立 `ScreenTranslationWorker` 與 `VoiceTranslationWorker` 確保 UI 零阻塞
  - 整合 `GameAssistantController` 訊號槽、全域熱鍵、能力切換連動與 TTS 即時朗讀對話字幕
- [x] 任務 49: 統一套件匯出與相容性維護 (`__init__.py`, `main.py`)：匯出翻譯熱鍵常數、Worker 與浮動字幕組件
- [x] 任務 50: 撰寫完整單元測試套件 (`tests/test_translation.py`)：覆蓋常數列舉、Gemini 視覺翻譯/離線降級/JSON 抽取、致動器剪貼簿貼上、Agent 協調、UI 浮動字幕/Overlay、非同步 Worker、Win32 64-bit ctypes 降級、防焦點奪取旗標等 36 項測試，確保現有 44 項原有測試持續 100% 通過（總計 80 項測試全數 PASS）
- [x] 任務 51: 全專案語法編譯檢查 (`py_compile`) 28 個模組 100% 零錯誤

## 第九階段：Gemini 3.8 Flash 模型遷移與思考架構升級 (Gemini 3.8 Flash Migration)
- [x] 任務 52: 檢閱 Gemini 3.8 Flash API 規格與 `google-genai` SDK 遷移規範 (語意化 `thinking_level` 取代 legacy `thinking_budget`、結構化 JSON 輸出、64K output 與 1M context)
- [x] 任務 53: 擴充系統組態與神經系統思考列舉 (`config.py`, `nervous_system.py`)：新增 `ThinkingEffortLevel.MINIMAL`、`LOW`、`HIGH`，精準映射 Gemini 3.8 Flash 的思考深度
- [x] 任務 54: 升級 `GeminiAuxiliaryEngine` (`ai_engine.py`)：實作 `_build_generate_config`，全面接入 Gemini 3.8 Flash 的 `thinking_level`、`response_mime_type="application/json"` 與溫度控制
- [x] 任務 55: 針對全系統 6 大 Gemini API 調用點深度優化：
  - `decompose_user_demand`: 支援 medium / high 深度戰術拆解
  - `analyze_screen`: 支援 medium / high 深度多模態畫面分析
  - `translate_screen`: 配置 low 思考深度，兼顧翻譯品質與響應速度
  - `translate_chat_subtitles`: 配置 minimal 思考深度與原生 JSON 輸出，加速字幕浮動顯示
  - `translate_voice_text`: 配置 minimal 思考深度與 0.1 低溫，實現確定性遊戲短語極速翻譯
  - `synthesize_tool_code`: 配置 high 思考深度，發揮 Gemini 3.8 Flash 頂尖代碼推理與安全審查能力
- [x] 任務 56: 擴充單元測試套件 (`tests/test_universal_agent.py`, `tests/test_translation.py`)：新增 `TestGemini38FlashMigration` 涵蓋常數、思考深度列舉、Config 建置與 Mock 調用檢驗
- [x] 任務 57: 更新專案說明文檔 (`README.md`, `AGENTS.md`)，詳述 Gemini 3.8 Flash 遷移成果與技術優勢


