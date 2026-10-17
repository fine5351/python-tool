"""測試套件初始化（自動掛載 src 目錄以支援免安裝直接執行測試）。"""

import sys
from pathlib import Path

_src_dir = Path(__file__).resolve().parents[1] / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))
