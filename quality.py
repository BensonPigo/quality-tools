#!/usr/bin/env python3
"""三道檢查的進入點：測試、CRAP、抓錯檢查。只用 Python 標準函式庫，Python 3.8 以上。

用法（在專案根目錄執行）：

    python tools/quality/quality.py test
    python tools/quality/quality.py crap --base origin/main
    python tools/quality/quality.py mutation --base origin/main
    python tools/quality/quality.py baseline

指令、設定檔和結束碼的說明見 qtools/cli.py 與 qtools/config.py。
"""

import os
import sys

# 工具掛在專案的 tools/quality 底下時，專案根目錄才是執行目錄，所以要自己把工具目錄加進搜尋路徑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qtools.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
