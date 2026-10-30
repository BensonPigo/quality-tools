"""四種語言共用的資料格式、狀態和白話名稱。

    Function  {file, name, start, end, complexity, coverage}   coverage 是 0～1
    Mutant    {file, line, column, status, mutator, original, replacement, line_text}
    file 一律是相對於專案根目錄、用 / 分隔的路徑。
"""

from dataclasses import dataclass
from typing import Optional

# 改壞版本的狀態。測試偵測到 = KILLED + TIMED_OUT（改壞之後測試卡住，也算抓到）。
# EQUIVALENT（改了也沒差）和 EXCLUDED_MUTATOR（設定排除的改法）由核心在量測之後標記，語言轉接不會產生。
KILLED = "KILLED"
TIMED_OUT = "TIMED_OUT"
LIVED = "LIVED"
NOT_COVERED = "NOT_COVERED"
EQUIVALENT = "EQUIVALENT"
EXCLUDED_MUTATOR = "EXCLUDED_MUTATOR"
NOT_VIABLE = "NOT_VIABLE"
SKIPPED = "SKIPPED"

STATUSES = [KILLED, TIMED_OUT, LIVED, NOT_COVERED, EQUIVALENT, EXCLUDED_MUTATOR, NOT_VIABLE, SKIPPED]

# 畫面上的白話名稱，用詞跟 docs/導入步驟_三道檢查.md 的用詞對照表一致
STATUS_NAMES = {
    KILLED: "抓到",
    TIMED_OUT: "逾時（算抓到）",
    LIVED: "沒抓到",
    NOT_COVERED: "測試沒跑到",
    EQUIVALENT: "已排除：改了也沒差",
    EXCLUDED_MUTATOR: "已排除：設定排除的改法",
    NOT_VIABLE: "無效",
    SKIPPED: "略過",
}


@dataclass
class Function:
    file: str
    name: str
    start: int
    end: int
    complexity: int
    coverage: float
    crap: float = 0.0  # 由 crap.score_functions 填入


@dataclass
class Mutant:
    file: str
    line: int
    status: str
    mutator: str
    column: Optional[int] = None  # 從 1 起算，工具沒回報就是 None
    original: Optional[str] = None  # S2 填入：被改掉的原文，例如 >=
    replacement: Optional[str] = None  # S2 填入：改成什麼，例如 >
    line_text: str = ""  # 該行原文去頭尾空白，由核心依檔案內容填入
