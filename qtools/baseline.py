"""現況報告：在現有程式上量一次，寫成 markdown，當作技術債清單。"""

import datetime
import os

from qtools import crap, mutation
from qtools.model import KILLED, LIVED, NOT_COVERED, TIMED_OUT
from qtools.proc import git
from qtools.report import pct


def write_baseline(funcs, mutants, cfg, lang, out_path):
    threshold = cfg["crap"]["threshold"]

    out = []
    out.append("# 品質現況\n")
    out.append("量測日期：{}，commit：{}\n".format(datetime.date.today(), git("rev-parse", "--short", "HEAD").strip()))

    out.append("## CRAP\n")
    passed = sum(1 for f in funcs if f.crap <= threshold)
    split = sum(1 for f in funcs if f.crap > threshold and f.complexity > threshold)
    out.append("門檻 {}。函式總數 {}，通過 {}，超標 {}（補測試就能過 {}，要拆函式 {}）。\n".format(
        threshold, len(funcs), passed, len(funcs) - passed, len(funcs) - passed - split, split))
    out.append("| CRAP | C | 覆蓋率 | 函式 | 位置 | 改善方向 |")
    out.append("|---|---|---|---|---|---|")
    for f in funcs:
        if f.crap > threshold:
            out.append("| {:.1f} | {} | {:.1f}% | `{}` | `{}:{}` | {} |".format(
                f.crap, f.complexity, f.coverage * 100, f.name, f.file, f.start,
                crap.advice_text(f.complexity, threshold)))
    if passed == len(funcs):
        out.append("| — | — | — | 沒有超標的函式 | — | — |")
    out.append("")

    out.append("## 抓錯檢查\n")
    out.append("抓錯率 =（抓到 + 逾時）÷（抓到 + 逾時 + 沒抓到），看有測到的程式碼測得夠不夠嚴。")
    out.append("測到率 =（抓到 + 逾時 + 沒抓到）÷（再加上測試沒跑到），看有多少程式碼有測試。兩個數字要一起看。\n")
    out.append("| 套件 | 抓到 | 逾時 | 沒抓到 | 測試沒跑到 | 抓錯率 | 測到率 |")
    out.append("|---|---|---|---|---|---|---|")
    by_pkg = mutation.by_package(mutants, lang.report_group)
    # 讓沒有任何改壞版本的套件（例如沒有測試專案）也列出來
    packages = sorted(set(by_pkg) | {lang.report_group(f.file) for f in funcs})
    for pkg in packages:
        c = by_pkg.get(pkg)
        if c is None:
            out.append("| `{}` | — | — | — | — | 沒有量到改壞的版本 | — |".format(pkg))
            continue
        out.append("| `{}` | {} | {} | {} | {} | {} | {} |".format(
            pkg, c[KILLED], c[TIMED_OUT], c[LIVED], c[NOT_COVERED],
            pct(mutation.kill_rate(c)), pct(mutation.reach_rate(c))))
    out.append("")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))

