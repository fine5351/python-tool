"""快速啟動入口腳本（免 pip install 即可直接執行）。"""

import sys
from pathlib import Path

# 將 src 加入模組搜尋路徑
src_path = Path(__file__).resolve().parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from video_editor.cli import main

if __name__ == "__main__":
    main()
