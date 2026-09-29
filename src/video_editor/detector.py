"""影片特徵偵測模組（透過 FFmpeg 快速篩選靜止與過場）。"""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from video_editor.config import EditorConfig


def find_executable(name: str, preferred: Optional[str] = None) -> str:
    """智慧尋找執行檔路徑，支援環境變數自動探測與常見路徑補全。"""
    # 1. 若使用者指定了特定路徑，且該路徑存在
    if preferred and preferred != name:
        p = Path(preferred)
        if p.is_file():
            return str(p.resolve())

    # 2. 系統 PATH 尋找
    system_path = shutil.which(name)
    if system_path:
        return system_path

    # 3. 針對 ffmpeg / ffprobe 檢查 FFMPEG_HOME 與常見 typo (FFMPEG_HOE)
    if name in ("ffmpeg", "ffprobe"):
        env_home = os.environ.get("FFMPEG_HOME") or os.environ.get("FFMPEG_HOE")
        if env_home:
            candidate = Path(env_home) / "bin" / f"{name}.exe"
            if candidate.is_file():
                return str(candidate.resolve())

        # 常見 Windows 安裝候選目錄
        common_candidates = [
            Path(r"D:/work/tool/ffmpeg-7.0.2-full_build/bin") / f"{name}.exe",
            Path(r"D:/ffmpeg-7.0.2-full_build/bin") / f"{name}.exe",
            Path(r"C:/ffmpeg/bin") / f"{name}.exe",
            Path(r"C:/Program Files/ffmpeg/bin") / f"{name}.exe",
        ]
        for candidate in common_candidates:
            if candidate.is_file():
                return str(candidate.resolve())

    # 4. 針對 agy 檢查使用者 AppData 與 local bin
    if name == "agy":
        agy_candidates = [
            Path(os.path.expandvars(r"%LOCALAPPDATA%\agy\bin\agy.exe")),
            Path(os.path.expanduser(r"~/.local/bin/agy.exe")),
        ]
        for candidate in agy_candidates:
            if candidate.is_file():
                return str(candidate.resolve())

    # 若皆找不到，回傳原本名稱
    return name


class VideoDetector:
    """處理影片快速特徵掃描的偵測器。"""

    def __init__(self, config: EditorConfig):
        self.config = config
        # 自動探測並修正執行檔路徑
        self.config.ffmpeg_bin = find_executable("ffmpeg", self.config.ffmpeg_bin)
        self.config.ffprobe_bin = find_executable("ffprobe", self.config.ffprobe_bin)
        self.config.agy_bin = find_executable("agy", self.config.agy_bin)

    def check_tools(self) -> None:
        """檢查 FFmpeg 與 FFprobe 是否可用。"""
        if not self.config.video_path.is_file():
            raise FileNotFoundError(f"找不到指定的影片檔案: '{self.config.video_path}'")

        for tool_name, bin_path in [
            ("FFmpeg", self.config.ffmpeg_bin),
            ("FFprobe", self.config.ffprobe_bin),
        ]:
            try:
                result = subprocess.run(
                    [bin_path, "-version"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                if result.returncode != 0:
                    raise RuntimeError(f"{tool_name} 回傳非零狀態碼: {result.returncode}")
            except Exception as err:
                raise RuntimeError(
                    f"無法執行 {tool_name} ('{bin_path}')。\n"
                    f"原因: {err}\n"
                    "建議排查：\n"
                    "1. 請檢查 Windows 環境變數中的 FFMPEG_HOME 是否正確，\n"
                    "   且確認 PATH 內使用的是 %FFMPEG_HOME%\\bin（避免打成 %FFMPEG_HOE%）。\n"
                    "2. 或在執行指令時直接加上參數：\n"
                    "   --ffmpeg-path \"D:/work/tool/ffmpeg-7.0.2-full_build/bin/ffmpeg.exe\" "
                    "--ffprobe-path \"D:/work/tool/ffmpeg-7.0.2-full_build/bin/ffprobe.exe\""
                ) from err

    def get_duration(self) -> float:
        """取得影片總時長（秒）。"""
        self.check_tools()
        cmd = [
            self.config.ffprobe_bin,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(self.config.video_path),
        ]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            val_str = result.stdout.strip()
            if not val_str or val_str == "N/A":
                raise ValueError(f"ffprobe 無法解析影片時長（輸出為: '{val_str}'）")
            return float(val_str)
        except Exception as err:
            raise RuntimeError(
                f"無法取得影片 '{self.config.video_path}' 的總長度。\n"
                f"指令: {' '.join(cmd)}\n"
                f"原因: {err}"
            ) from err

    def detect_freeze_and_black(self) -> Tuple[List[Tuple[float, float]], List[float]]:
        """高速掃描整部影片，取得疑似暫離的靜止區間與黑畫面切點。"""
        self.check_tools()

        filter_spec = (
            f"freezedetect=n=-50dB:d={self.config.min_freeze_duration},"
            f"blackdetect=d={self.config.min_black_duration}:"
            f"pic_th={self.config.black_ratio_threshold}:"
            f"pix_th={self.config.black_pixel_threshold}"
        )

        cmd = [
            self.config.ffmpeg_bin,
            "-hide_banner",
            "-i", str(self.config.video_path),
            "-vf", filter_spec,
            "-an",
            "-f", "null",
            "-",
        ]

        print("▶ 正在執行 FFmpeg 快速掃描（分析靜止畫面與黑畫面過場）...")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        _, stderr_output = process.communicate()

        freeze_ranges: List[Tuple[float, float]] = []
        black_cuts: List[float] = []

        current_freeze_start = None
        for line in stderr_output.splitlines():
            # 解析 freezedetect 輸出
            if "freeze_start:" in line:
                match = re.search(r"freeze_start:\s*([\d\.]+)", line)
                if match:
                    current_freeze_start = float(match.group(1))
            elif "freeze_end:" in line and current_freeze_start is not None:
                match = re.search(r"freeze_end:\s*([\d\.]+)", line)
                if match:
                    freeze_end = float(match.group(1))
                    freeze_ranges.append((current_freeze_start, freeze_end))
                    current_freeze_start = None

            # 解析 blackdetect 輸出
            if "black_start:" in line and "black_end:" in line:
                m_start = re.search(r"black_start:\s*([\d\.]+)", line)
                m_end = re.search(r"black_end:\s*([\d\.]+)", line)
                if m_start and m_end:
                    b_start = float(m_start.group(1))
                    b_end = float(m_end.group(1))
                    black_cuts.append((b_start + b_end) / 2.0)

        print(
            f"✔ 掃描完成：找到 {len(freeze_ranges)} 個疑似暫離靜止區間，"
            f"{len(black_cuts)} 個黑畫面轉場候選點。"
        )
        return freeze_ranges, black_cuts

    def detect_silences(self) -> List[Tuple[float, float]]:
        """高速掃描音訊中的語音停頓與靜音區間（確保切點不中斷說話台詞）。"""
        self.check_tools()
        filter_spec = (
            f"silencedetect=noise={self.config.silence_noise_threshold}:"
            f"d={self.config.min_silence_duration}"
        )
        cmd = [
            self.config.ffmpeg_bin,
            "-hide_banner",
            "-i", str(self.config.video_path),
            "-vn",
            "-af", filter_spec,
            "-f", "null",
            "-",
        ]

        print("▶ 正在掃描音訊語音停頓（確保切點不截斷角色台詞）...")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        _, stderr_output = process.communicate()

        silence_intervals: List[Tuple[float, float]] = []
        current_start = None
        for line in stderr_output.splitlines():
            if "silence_start:" in line:
                match = re.search(r"silence_start:\s*([\d\.]+)", line)
                if match:
                    current_start = float(match.group(1))
            elif "silence_end:" in line and current_start is not None:
                match = re.search(r"silence_end:\s*([\d\.]+)", line)
                if match:
                    end = float(match.group(1))
                    silence_intervals.append((current_start, end))
                    current_start = None

        print(f"✔ 語音停頓掃描完成：找到 {len(silence_intervals)} 處對話/音訊停頓點。")
        return silence_intervals

    def extract_keyframe(self, timestamp: float, output_path: Path) -> Path:
        """於指定時間戳記截取一張關鍵影格圖片。"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.config.ffmpeg_bin,
            "-y",
            "-ss", str(max(0.0, timestamp)),
            "-i", str(self.config.video_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(output_path),
        ]
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return output_path
