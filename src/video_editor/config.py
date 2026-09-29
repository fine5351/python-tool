"""配置與參數管理模組。"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EditorConfig:
    """剪輯與偵測設定模型。"""

    video_path: Path
    output_dir: Path = field(default_factory=lambda: Path("output_parts"))
    temp_dir: Path = field(default_factory=lambda: Path("temp_frames"))

    # 靜止畫面門檻 (秒)
    min_freeze_duration: float = 30.0

    # 黑畫面偵測門檻 (秒) 與像素門檻
    min_black_duration: float = 0.5
    black_ratio_threshold: float = 0.98
    black_pixel_threshold: float = 0.10

    # 切片目標時長 (秒) - 預設 20 ~ 30 分鐘
    target_min_part_len: float = 20.0 * 60.0
    target_max_part_len: float = 30.0 * 60.0
    # 允許為了等待句子講完或動作做完，最多延後尋找切點的秒數 (預設: 90 秒)
    max_search_overtime: float = 90.0

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
