"""指令解析和各指令的流程。

用法（在專案根目錄執行）：

    python tools/quality/quality.py test                          # 第一關：單元測試
    python tools/quality/quality.py crap --base origin/main       # 第二關：只檢查改到的函式
    python tools/quality/quality.py mutation --base origin/main   # 第三關：抓錯檢查，只計算改到的行
    python tools/quality/quality.py baseline                      # 量現況，寫成 docs/品質現況.md
    python tools/quality/quality.py migrate                       # v1 的 .quality.json 轉成 v2

crap 和 mutation 不加 --base 時，檢查整個專案；加 --json 檔名，另外寫一份 JSON 報告。
門檻、語言、排除目錄寫在專案根目錄的 .quality.json。

結束碼：0 通過，1 沒過門檻，2 量測失敗或設定有誤（例如測試沒過、工具執行失敗）。
"""

import argparse
import os
import sys

from qtools import baseline, changes, config, crap, equivalents, mutation, report
from qtools.langs.base import load_language
from qtools.model import KILLED, LIVED, NOT_COVERED, TIMED_OUT
from qtools.proc import QualityError, git


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="三道檢查的共用判定")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("test", help="第一關：單元測試")
    p = sub.add_parser("crap", help="第二關：CRAP")
    p.add_argument("--base", help="只檢查和這個分支相比有改到的函式，例如 origin/main")
    p.add_argument("--json", metavar="檔名", help="另外寫一份 JSON 報告")
    p = sub.add_parser("mutation", help="第三關：抓錯檢查")
    p.add_argument("--base", help="只計算和這個分支相比有改到的行，例如 origin/main")
    p.add_argument("--json", metavar="檔名", help="另外寫一份 JSON 報告")
    p = sub.add_parser("baseline", help="量現況")
    p.add_argument("--out", help="報告檔名，預設用設定檔的 baseline.out")
    sub.add_parser("migrate", help="把 v1 的 .quality.json 轉成 v2")
    args = parser.parse_args(argv)

    # Windows 上執行目錄可能是 8.3 短檔名（例如 C:/Users/ALEXAN~1.LIN），Jest 在這種目錄下會找不到測試，
    # 其他工具回報的路徑也會跟執行目錄對不起來。先換成實際路徑，之後啟動的工具都會用這個目錄
    os.chdir(os.path.realpath(os.getcwd()))
    try:
        if args.command == "migrate":
            sys.exit(cmd_migrate())
        cfg = config.load_config()
        lang = load_language(cfg["language"])
        command = {"test": cmd_test, "crap": cmd_crap, "mutation": cmd_mutation, "baseline": cmd_baseline}
        sys.exit(command[args.command](args, cfg, lang))
    except QualityError as e:
        print(e, file=sys.stderr)
        sys.exit(e.exit_code)


# ---------- 第一關：單元測試 ----------

def cmd_test(args, cfg, lang):
    return 0 if lang.run_tests(cfg) == 0 else 1


# ---------- 第二關：CRAP ----------

def cmd_crap(args, cfg, lang):
    threshold = cfg["crap"]["threshold"]
    funcs = crap.score_functions(lang.measure_functions(cfg))

    untouched_over = 0
    if args.base:
        changed = changes.changed_lines(args.base, lang, cfg)
        touched = [f for f in funcs if changes.overlaps(changed.get(f.file), f.start, f.end)]
        untouched_over = sum(1 for f in funcs if f not in touched and f.crap > threshold)
        funcs = touched
        print("只檢查和 {} 相比有改到的函式（共 {} 個）\n".format(args.base, len(funcs)))

    failed = report.print_crap_table(funcs, threshold, with_advice=bool(args.base))

    print()
    if untouched_over:
        print("另有 {} 個沒改到的函式超過門檻，列為技術債，不計入這次判定。".format(untouched_over))
    if failed:
        print("FAIL：{} 個函式的 CRAP 超過門檻 {}".format(failed, threshold))
    elif args.base and not funcs:
        print("PASS：這次沒有改到任何函式")
    else:
        print("PASS：所有函式的 CRAP 都在門檻 {} 以內".format(threshold))

    if args.json:
        report.write_json(args.json, report.build_report(
            "crap", cfg, lang, args.base, _commit(), not failed,
            crap_part=report.crap_json(funcs, threshold, untouched_over)))
    return 1 if failed else 0


# ---------- 第三關：抓錯檢查 ----------

def cmd_mutation(args, cfg, lang):
    entries = equivalents.load(cfg["mutation"]["equivalents_file"])
    settings = lang.settings(cfg)
    if args.base:
        changed = changes.changed_lines(args.base, lang, cfg)
        prod = {f: s for f, s in changed.items() if not lang.is_test(f)}
        if not prod:
            print("PASS：這次沒有改到正式程式碼")
            return _finish_mutation(args, cfg, lang, settings, [], [])
        dirs = sorted({lang.package_dir(f) for f in prod})
        measured = lang.measure_mutants(cfg, dirs, sorted(prod))
        mutants = [m for m in measured if changes.overlaps(prod.get(m.file), m.line, m.line)]
        scope = set(prod)
        print("只計算和 {} 相比有改到的行\n".format(args.base))
    else:
        measured = mutants = lang.measure_mutants(cfg)
        scope = None

    unused = classify(measured, mutants, settings, entries, scope)
    counts = mutation.count(mutants)
    report.print_mutation_result(mutants, counts, cfg, settings, unused)

    problems = mutation.judge(counts, cfg)
    print()
    for p in problems:
        print("FAIL：" + p)
    if not problems:
        if counts[KILLED] + counts[TIMED_OUT] + counts[LIVED] + counts[NOT_COVERED] == 0:
            print("PASS：改到的行沒有量到改壞的版本（沒有可以改的地方，或是所在的專案沒有測試，請看上方訊息）")
        else:
            print("PASS")
    return _finish_mutation(args, cfg, lang, settings, mutants, problems, unused)


def classify(measured, mutants, settings, entries, scope):
    """填入行原文，再依序做兩件事：設定排除的改法（EXCLUDED_MUTATOR）、排除清單比對（EQUIVALENT）。

    measured 是量到的全部改壞版本，mutants 是其中這次要計算的（用 --base 時只有改到的行）。排除清單有沒有用到
    要看全部量到的，所以兩者都標記，回傳排除清單裡沒用到的項目。
    """
    mutation.fill_line_text(measured)
    mutation.exclude_mutators(measured, settings["exclude_mutators"])
    return equivalents.apply(mutants, entries, measured, scope)


def _finish_mutation(args, cfg, lang, settings, mutants, problems, unused=()):
    if args.json:
        counts = mutation.count(mutants)
        report.write_json(args.json, report.build_report(
            "mutation", cfg, lang, args.base, _commit(), not problems,
            mutation_part=report.mutation_json(mutants, counts, cfg, lang.report_group, settings, unused)))
    return 1 if problems else 0


# ---------- 量現況 ----------

def cmd_baseline(args, cfg, lang):
    entries = equivalents.load(cfg["mutation"]["equivalents_file"])
    funcs = crap.score_functions(lang.measure_functions(cfg))
    mutants = lang.measure_mutants(cfg)
    unused = classify(mutants, mutants, lang.settings(cfg), entries, None)
    out = args.out or cfg["baseline"]["out"]
    baseline.write_baseline(funcs, mutants, cfg, lang, out, unused)
    print("已寫入 " + out)
    return 0


# ---------- v1 → v2 ----------

def cmd_migrate():
    diff = config.migrate_file()
    print("已把 {} 轉成 v2 格式。變更如下：\n".format(config.CONFIG_FILE))
    print(diff)
    return 0


def _commit():
    return git("rev-parse", "HEAD").strip()
