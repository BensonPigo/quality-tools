#!/usr/bin/env python3
"""三重約束的共用判定。

各語言的量測由 lang_<語言>.py 負責，轉成共用格式；這支腳本負責找出改到的部分、
算 CRAP、判斷門檻、產生現況報告。只用 Python 標準函式庫，Python 3.8 以上。

用法（在專案根目錄執行）：

    python tools/quality/quality.py test                          # 第一重：單元測試
    python tools/quality/quality.py crap --base origin/main       # 第二重：只檢查改到的函式
    python tools/quality/quality.py mutation --base origin/main   # 第三重：只計算改到的行
    python tools/quality/quality.py baseline                      # 量現況，寫成 docs/品質現況.md

crap 和 mutation 不加 --base 時，檢查整個專案。
門檻、語言、排除目錄寫在專案根目錄的 .quality.json。

結束碼：0 通過，1 沒過門檻，2 量測失敗（例如測試沒過、工具執行失敗）。

共用格式：
    函式   {file, name, start, end, complexity, coverage}   coverage 是 0～1
    突變體 {file, line, status, mutator}                     status 見 STATUSES
    file 一律是相對於專案根目錄、用 / 分隔的路徑。
"""

import argparse
import datetime
import importlib
import json
import math
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import QualityError, is_excluded, normalize, run  # noqa: E402

DEFAULTS = {
    "language": "",
    "base": "origin/main",
    "crap_threshold": 12,
    "efficacy_threshold": 80,
    "mutant_coverage_threshold": 0,
    "exclude": ["tools/", "vendor/", "node_modules/"],
}

# 突變體狀態。測試偵測到 = KILLED + TIMED_OUT（改壞之後測試卡住，也算抓到）。
STATUSES = ["KILLED", "TIMED_OUT", "LIVED", "NOT_COVERED", "NOT_VIABLE", "SKIPPED"]


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="三重約束的共用判定")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("test", help="第一重：單元測試")
    p = sub.add_parser("crap", help="第二重：CRAP")
    p.add_argument("--base", help="只檢查和這個分支相比有改到的函式，例如 origin/main")
    p = sub.add_parser("mutation", help="第三重：變異測試")
    p.add_argument("--base", help="只計算和這個分支相比有改到的行，例如 origin/main")
    p = sub.add_parser("baseline", help="量現況")
    p.add_argument("--out", default="docs/品質現況.md", help="報告檔名")
    args = parser.parse_args()

    # Windows 上執行目錄可能是 8.3 短檔名（例如 C:/Users/ALEXAN~1.LIN），Jest 在這種目錄下會找不到測試，
    # 其他工具回報的路徑也會跟執行目錄對不起來。先換成實際路徑，之後啟動的工具都會用這個目錄
    os.chdir(os.path.realpath(os.getcwd()))
    try:
        cfg = load_config()
        lang = load_language(cfg["language"])
        command = {"test": cmd_test, "crap": cmd_crap, "mutation": cmd_mutation, "baseline": cmd_baseline}
        sys.exit(command[args.command](args, cfg, lang))
    except QualityError as e:
        print(e, file=sys.stderr)
        sys.exit(2)


def load_config():
    if not os.path.exists(".quality.json"):
        raise QualityError("找不到 .quality.json，請在專案根目錄執行")
    with open(".quality.json", encoding="utf-8") as f:
        cfg = dict(DEFAULTS, **json.load(f))
    if not cfg["language"]:
        raise QualityError(".quality.json 沒有設定 language")
    return cfg


def load_language(name):
    try:
        return importlib.import_module("lang_" + name)
    except ImportError:
        raise QualityError("不支援的語言：{}（找不到 lang_{}.py）".format(name, name))


# ---------- 第一重：單元測試 ----------

def cmd_test(args, cfg, lang):
    return 0 if lang.run_tests(cfg) == 0 else 1


# ---------- 第二重：CRAP ----------

def cmd_crap(args, cfg, lang):
    threshold = cfg["crap_threshold"]
    funcs = scored_functions(cfg, lang)

    debt = 0
    if args.base:
        changed = changed_lines(args.base, lang, cfg)
        touched = [f for f in funcs if overlaps(changed.get(f["file"]), f["start"], f["end"])]
        debt = sum(1 for f in funcs if f not in touched and f["crap"] > threshold)
        funcs = touched
        print("只檢查和 {} 相比有改到的函式（共 {} 個）\n".format(args.base, len(funcs)))

    failed = print_crap_table(funcs, threshold, advice=bool(args.base))

    print()
    if debt:
        print("另有 {} 個沒改到的函式超過門檻，列為技術債，不計入這次判定。".format(debt))
    if failed:
        print("FAIL：{} 個函式的 CRAP 超過門檻 {}".format(failed, threshold))
        return 1
    if args.base and not funcs:
        print("PASS：這次沒有改到任何函式")
    else:
        print("PASS：所有函式的 CRAP 都在門檻 {} 以內".format(threshold))
    return 0


def scored_functions(cfg, lang):
    """量出每個函式並算好 CRAP，由高到低排序。"""
    funcs = lang.measure_functions(cfg)
    for f in funcs:
        c, p = f["complexity"], f["coverage"]
        f["crap"] = c * c * (1 - p) ** 3 + c
    funcs.sort(key=lambda f: -f["crap"])
    return funcs


def print_crap_table(funcs, threshold, advice):
    """印出 CRAP 表格，回傳超過門檻的函式數量。advice 為 True 時，超標的函式後面附上改善方向。"""
    print("{:<8} {:<6} {:<8} {:<24} {}".format("CRAP", "C", "Cover", "Func", "Pos"))
    failed = 0
    for f in funcs:
        mark = "  "
        if f["crap"] > threshold:
            failed += 1
            mark = "❌"
            if advice:
                mark += " " + crap_advice(f["complexity"], threshold)
        print("{:<8.1f} {:<6} {:<8} {:<24} {}:{} {}".format(
            f["crap"], f["complexity"], "{:.1f}%".format(f["coverage"] * 100), f["name"], f["file"], f["start"], mark))
    return failed


def crap_advice(c, threshold):
    """CRAP 最低就是 C，所以 C 超過門檻時，補測試沒有用。"""
    if c > threshold:
        return "要拆函式"
    # 解 C² × (1 − p)³ + C ≤ 門檻，得到 p ≥ 1 − ∛((門檻 − C) / C²)
    need = 1 - ((threshold - c) / (c * c)) ** (1 / 3)
    return "覆蓋率要到 {}%".format(math.ceil(round(need * 100, 6)))


# ---------- 第三重：變異測試 ----------

def cmd_mutation(args, cfg, lang):
    if args.base:
        changed = changed_lines(args.base, lang, cfg)
        prod = {f: s for f, s in changed.items() if not lang.is_test(f)}
        if not prod:
            print("PASS：這次沒有改到正式程式碼")
            return 0
        dirs = sorted({lang.package_dir(f) for f in prod})
        mutants = [m for m in lang.measure_mutants(cfg, dirs, sorted(prod))
                   if overlaps(prod.get(m["file"]), m["line"], m["line"])]
        print("只計算和 {} 相比有改到的行\n".format(args.base))
    else:
        mutants = lang.measure_mutants(cfg)

    count = Counter(m["status"] for m in mutants)
    for m in sorted(mutants, key=lambda m: (m["file"], m["line"])):
        if m["status"] in ("LIVED", "NOT_COVERED"):
            print("{:<12} {:<24} {}:{}".format(m["status"], m["mutator"], m["file"], m["line"]))

    detected = count["KILLED"] + count["TIMED_OUT"]
    covered = detected + count["LIVED"]
    efficacy = 100.0 * detected / covered if covered else None
    mcover = 100.0 * covered / (covered + count["NOT_COVERED"]) if covered + count["NOT_COVERED"] else None

    print()
    print("殺死 {}、超時 {}、存活 {}、沒覆蓋 {}".format(
        count["KILLED"], count["TIMED_OUT"], count["LIVED"], count["NOT_COVERED"]))
    print("效能：{}（門檻 {}%）".format(pct(efficacy), cfg["efficacy_threshold"]))
    print("突變體覆蓋率：{}（門檻 {}%）".format(pct(mcover), cfg["mutant_coverage_threshold"]))

    problems = []
    if efficacy is not None and efficacy < cfg["efficacy_threshold"]:
        problems.append("效能低於門檻，有突變體存活：補測試把它殺掉；認為是等價突變體的，在 PR 裡說明")
    if mcover is not None and mcover < cfg["mutant_coverage_threshold"]:
        problems.append("突變體覆蓋率低於門檻：有改到的程式碼沒有測試")
    print()
    if problems:
        for p in problems:
            print("FAIL：" + p)
        return 1
    if covered + count["NOT_COVERED"] == 0:
        print("PASS：改到的行沒有量到突變體（沒有可以突變的地方，或是所在的專案沒有測試，請看上方訊息）")
    else:
        print("PASS")
    return 0


def pct(v):
    return "—" if v is None else "{:.2f}%".format(v)


# ---------- 量現況 ----------

def cmd_baseline(args, cfg, lang):
    threshold = cfg["crap_threshold"]
    funcs = scored_functions(cfg, lang)
    mutants = lang.measure_mutants(cfg)

    out = []
    out.append("# 品質現況\n")
    out.append("量測日期：{}，commit：{}\n".format(datetime.date.today(), git("rev-parse", "--short", "HEAD").strip()))

    out.append("## CRAP\n")
    passed = sum(1 for f in funcs if f["crap"] <= threshold)
    split = sum(1 for f in funcs if f["crap"] > threshold and f["complexity"] > threshold)
    out.append("門檻 {}。函式總數 {}，通過 {}，超標 {}（補測試就能過 {}，要拆函式 {}）。\n".format(
        threshold, len(funcs), passed, len(funcs) - passed, len(funcs) - passed - split, split))
    out.append("| CRAP | C | 覆蓋率 | 函式 | 位置 | 改善方向 |")
    out.append("|---|---|---|---|---|---|")
    for f in funcs:
        if f["crap"] > threshold:
            out.append("| {:.1f} | {} | {:.1f}% | `{}` | `{}:{}` | {} |".format(
                f["crap"], f["complexity"], f["coverage"] * 100, f["name"], f["file"], f["start"],
                crap_advice(f["complexity"], threshold)))
    if passed == len(funcs):
        out.append("| — | — | — | 沒有超標的函式 | — | — |")
    out.append("")

    out.append("## 變異測試\n")
    out.append("效能 =（殺死 + 超時）÷（殺死 + 超時 + 存活），看有測到的程式碼測得夠不夠嚴。")
    out.append("突變體覆蓋率 =（殺死 + 超時 + 存活）÷（再加上沒覆蓋），看有多少程式碼有測試。兩個數字要一起看。\n")
    out.append("| 套件 | 殺死 | 超時 | 存活 | 沒覆蓋 | 效能 | 突變體覆蓋率 |")
    out.append("|---|---|---|---|---|---|---|")
    group = getattr(lang, "report_group", lang.package_dir)  # 語言模組可以指定比套件更細的分組
    by_pkg = defaultdict(Counter)
    for f in funcs:  # 讓沒有任何突變體的套件（例如沒有測試專案）也列出來
        by_pkg[group(f["file"])]
    for m in mutants:
        by_pkg[group(m["file"])][m["status"]] += 1
    for pkg in sorted(by_pkg):
        c = by_pkg[pkg]
        detected = c["KILLED"] + c["TIMED_OUT"]
        covered = detected + c["LIVED"]
        if not c:
            out.append("| `{}` | — | — | — | — | 沒有量到突變體 | — |".format(pkg))
            continue
        out.append("| `{}` | {} | {} | {} | {} | {} | {} |".format(
            pkg, c["KILLED"], c["TIMED_OUT"], c["LIVED"], c["NOT_COVERED"],
            pct(100.0 * detected / covered if covered else None),
            pct(100.0 * covered / (covered + c["NOT_COVERED"]) if covered + c["NOT_COVERED"] else None)))
    out.append("")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))
    print("已寫入 " + args.out)
    return 0


# ---------- 找出改到的部分 ----------

def git(*args):
    r = run(["git", "-c", "core.quotepath=false"] + list(args))
    if r.returncode != 0:
        raise QualityError("git {} 執行失敗：\n{}".format(" ".join(args), r.stderr))
    return r.stdout


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


if __name__ == "__main__":
    main()
