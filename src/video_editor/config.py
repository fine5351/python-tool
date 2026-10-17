"""配置與參數管理模組。"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Union


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def clean_path(val: Union[str, Path]) -> Path:
    """清理路徑（自動去除兩側多餘空白與 Windows 命令列轉義殘留之引號）。"""
    cleaned = str(val).strip().strip('"\'').strip()
    return Path(cleaned)


@dataclass
class ModelConfig:
    """AI 工作職責三級分流模型配置。

    避免所有工作皆消耗高單價模型，依任務性質切分為三個獨立模型槽位：
    - fast_vision: 高頻率基礎視覺快篩（暫離判定、過場判定、切點穩定度與初始段落基礎摘要）
    - deep_vision: 深度多模態視覺探勘（指定時間區間密集截圖拼圖細掃、跨段落細節比對）
    - planner: 自然語言對話意圖推理與非線性時間軸重組規劃
    """

    fast_vision: str = "flash_lite"
    deep_vision: str = "flash"
    planner: str = "pro"

    @staticmethod
    def normalize_role(role: str) -> str:
        """正規化模型職責名稱（支援 CLI 與互動指令常見別名）。"""
        key = role.strip().lower().replace("-", "_")
        aliases = {
            "fast": "fast_vision",
            "fast_vision": "fast_vision",
            "vision_fast": "fast_vision",
            "deep": "deep_vision",
            "deep_vision": "deep_vision",
            "vision_deep": "deep_vision",
            "plan": "planner",
            "planner": "planner",
            "chat": "planner",
        }
        if key not in aliases:
            raise ValueError(
                f"未知的模型職責 '{role}'（可用職責: fast_vision, deep_vision, planner）"
            )
        return aliases[key]

    def get_model(self, role: str) -> str:
        """依工作職責取得對應的模型名稱。"""
        norm_role = self.normalize_role(role)
        return getattr(self, norm_role)

    def set_model(self, role: str, model_name: str) -> str:
        """動態更新指定工作職責所使用的模型名稱，並回傳正規化後的職責名。"""
        norm_role = self.normalize_role(role)
        cleaned_model = model_name.strip()
        if not cleaned_model:
            raise ValueError("模型名稱不可為空字串")
        setattr(self, norm_role, cleaned_model)
        return norm_role

    def to_dict(self) -> Dict[str, str]:
        """轉為字典結構供序列化儲存。"""
        return {
            "fast_vision": self.fast_vision,
            "deep_vision": self.deep_vision,
            "planner": self.planner,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "ModelConfig":
        """從字典結構還原模型配置。"""
        return cls(
            fast_vision=data.get("fast_vision", "flash_lite"),
            deep_vision=data.get("deep_vision", "flash"),
            planner=data.get("planner", "pro"),
        )


@dataclass
class EditorConfig:
    """AI 剪輯與特徵偵測設定模型。"""

    video_path: Path
    output_dir: Path = field(default_factory=lambda: Path("output_parts"))
    temp_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "temp_frames")
    plan_file: Optional[Path] = None

    # AI 工作職責三級模型配置
    models: ModelConfig = field(default_factory=ModelConfig)

    # 匯出與互動剪輯設定
    # export_mode: "episodes" (無縫拼接後依目標時長分集) | "single" (無縫合併為單一完整檔) | "clips" (各保留段落獨立輸出)
    export_mode: str = "episodes"
    initial_prompt: str = ""
    auto_confirm: bool = False

    # 靜止畫面門檻 (秒)
    min_freeze_duration: float = 30.0

    # 黑畫面偵測門檻 (秒) 與像素門檻
    min_black_duration: float = 0.5
    black_ratio_threshold: float = 0.98
    black_pixel_threshold: float = 0.10

    # 白畫面偵測門檻 (秒) 與像素門檻
    min_white_duration: float = 0.5
    white_ratio_threshold: float = 0.98
    white_pixel_threshold: float = 0.10

    # 強制僅在黑白轉場畫面進行分割 (防止台詞未結束遭腰斬與音訊重疊)
    require_transition: bool = True

    # 切片目標時長 (秒) - 預設 20 ~ 30 分鐘
    target_min_part_len: float = 20.0 * 60.0
    target_max_part_len: float = 30.0 * 60.0
    # 允許為了等待轉場畫面出現，最多延後尋找切點的秒數 (預設: 180 秒)
    max_search_overtime: float = 180.0

    # 語音停頓 / 靜音偵測門檻 (防止台詞或動作被腰斬)
    silence_noise_threshold: str = "-30dB"
    min_silence_duration: float = 0.4

    # 執行程式路徑
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    agy_bin: str = "agy"

    # 行為開關
    dry_run: bool = False
    keep_temp: bool = False

    def __post_init__(self) -> None:
        """正規化所有檔案與目錄路徑並驗證匯出模式。"""
        self.video_path = clean_path(self.video_path)
        self.output_dir = clean_path(self.output_dir)
        self.temp_dir = clean_path(self.temp_dir)
        if not self.temp_dir.is_absolute():
            self.temp_dir = (PROJECT_ROOT / self.temp_dir).resolve()

        if self.plan_file is not None:
            self.plan_file = clean_path(self.plan_file)

        valid_modes = ("episodes", "single", "clips")
        if self.export_mode not in valid_modes:
            raise ValueError(
                f"不支援的 export_mode '{self.export_mode}'，僅支援 {valid_modes}"
            )

    @property
    def resolved_plan_file(self) -> Path:
        """取得剪輯計畫 JSON 檔案的儲存路徑。"""
        if self.plan_file is not None:
            return self.plan_file
        stem = self.video_path.stem or "video"
        return self.output_dir / f"{stem}_edit_plan.json"
