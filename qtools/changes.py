"""用 git diff 找出改到的行。邏輯沿用 v1。"""

import math
from collections import defaultdict

from qtools.proc import QualityError, git, is_excluded, normalize


def changed_lines(base, lang, cfg):
    """回傳 {檔案: [(起, 訖), ...]}，只包含正式程式碼和測試檔，不含 exclude 底下的檔案。

    比較的起點是 base 和 HEAD 的分岔點，所以 base 之後別人合併進去的改動不會算進來；
    比較的終點是工作目錄，所以還沒 commit 的改動和新增的檔案也會算進來。
    """
    try:
        merge_base = git("merge-base", base, "HEAD").strip()
    except QualityError as e:
        raise QualityError("找不到 {} 和 HEAD 的分岔點（CI 上要把 git 歷史完整抓下來）\n{}".format(base, e))

    diff = git("diff", "-U0", "--no-color", "--relative", "--ignore-cr-at-eol", merge_base, "--", *lang.SOURCE_GLOBS)
    changed = defaultdict(list)
    file = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            file = None if line == "+++ /dev/null" else normalize(line[len("+++ b/"):])  # /dev/null：檔案被刪除
        elif file and line.startswith("@@"):
            # @@ -舊起點,舊行數 +新起點,新行數 @@，只需要新版本的行號
            new = line.split()[2][1:]
            start, _, n = new.partition(",")
            start, n = int(start), int(n or 1)
            if n == 0:  # 只刪除沒新增：刪除位置在 start 和 start+1 之間
                changed[file].append((start, start + 1))
            else:
                changed[file].append((start, start + n - 1))

    for file in git("ls-files", "--others", "--exclude-standard", "--", *lang.SOURCE_GLOBS).splitlines():
        changed[normalize(file)].append((1, math.inf))

    return {f: s for f, s in changed.items() if not is_excluded(f, cfg)}


def overlaps(spans, start, end):
    return any(a <= end and b >= start for a, b in spans or [])
