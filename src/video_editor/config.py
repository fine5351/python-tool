"""配置與參數管理模組。"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Union


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def clean_path(val: Union[str, Path]) -> Path:
    """清理路徑（自動去除兩側多餘空白與 Windows 命令列轉義殘留之引號）。"""
    cleaned = str(val).strip().strip('"\'').strip()
    return Path(cleaned)


@dataclass
class EditorConfig:
    """剪輯與偵測設定模型。"""

    video_path: Path
    output_dir: Path = field(default_factory=lambda: Path("output_parts"))
    temp_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "temp_frames")

    def __post_init__(self) -> None:
        """正規化所有檔案與目錄路徑。"""
        self.video_path = clean_path(self.video_path)
        self.output_dir = clean_path(self.output_dir)
        self.temp_dir = clean_path(self.temp_dir)
        if not self.temp_dir.is_absolute():
            self.temp_dir = (PROJECT_ROOT / self.temp_dir).resolve()

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
    enable_ai: bool = True
    dry_run: bool = False
    keep_temp: bool = False
