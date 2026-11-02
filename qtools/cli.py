"""指令解析和各指令的流程。

用法（在專案根目錄執行）：

    python tools/quality/quality.py test                          # 第一關：單元測試
    python tools/quality/quality.py crap --base origin/main       # 第二關：只檢查改到的函式
    python tools/quality/quality.py mutation --base origin/main   # 第三關：抓錯檢查，只計算改到的行
    python tools/quality/quality.py check --base origin/main      # 依 gates 依序跑，第一個沒過就停
    python tools/quality/quality.py baseline                      # 量現況，寫成 docs/品質現況.md 和 .json
    python tools/quality/quality.py baseline --compare 舊.json    # 量完跟上一次的現況報告比較
    python tools/quality/quality.py compare 舊.json 新.json       # 只比較兩份現況報告，不量測

crap 和 mutation 不加 --base 時，檢查整個專案；加 --json 檔名，另外寫一份 JSON 報告。
門檻、語言、排除目錄、啟用哪幾關（gates）寫在專案根目錄的 .quality.json。
單獨執行的那一關不在 gates 裡，會印「還沒啟用」並以結束碼 0 結束。

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
    p = sub.add_parser("check", help="依 gates 依序跑，第一個沒過就停")
    p.add_argument("--base", help="比較基準，沒給就用 .quality.json 的 base")
    p.add_argument("--skip", nargs="+", default=[], metavar="名稱", help="這次不跑的關：{}".format("、".join(config.GATES)))
    p.add_argument("--json", metavar="目錄", help="crap 和 mutation 兩關各寫一份 JSON 報告到這個目錄")
    p = sub.add_parser("baseline", help="量現況")
    p.add_argument("--out", help="報告檔名，預設用設定檔的 baseline.out；JSON 寫到同名的 .json")
    p.add_argument("--compare", metavar="舊.json", help="跟上一次的現況報告（JSON）比較，印出前後差")
    p = sub.add_parser("compare", help="比較兩份現況報告（JSON），不量測")
    p.add_argument("old", metavar="舊.json")
    p.add_argument("new", metavar="新.json")
    args = parser.parse_args(argv)

    # Windows 上執行目錄可能是 8.3 短檔名（例如 C:/Users/ALEXAN~1.LIN），Jest 在這種目錄下會找不到測試，
    # 其他工具回報的路徑也會跟執行目錄對不起來。先換成實際路徑，之後啟動的工具都會用這個目錄
    os.chdir(os.path.realpath(os.getcwd()))
    try:
        if args.command == "compare":
            sys.exit(cmd_compare(args))
        cfg = config.load_config()
        lang = load_language(cfg["language"])
        command = {"test": cmd_test, "crap": cmd_crap, "mutation": cmd_mutation, "check": cmd_check,
                   "baseline": cmd_baseline}
        sys.exit(command[args.command](args, cfg, lang))
    except QualityError as e:
        print(e, file=sys.stderr)
        sys.exit(e.exit_code)


# ---------- 關卡 ----------

def not_enabled(gate, args, cfg, lang):
    """單獨執行的那一關不在 gates 裡：印「還沒啟用」，有 --json 就寫 result 為 skipped 的報告。

    回傳 True 代表這一關沒啟用，呼叫的指令直接以結束碼 0 結束，不跑任何量測。
    """
    if gate in cfg["gates"]:
        return False
    print("第 {} 關（{}）還沒啟用：{} 的 gates 沒有 {}".format(config.GATES.index(gate) + 1, gate, config.CONFIG_FILE, gate))
    if getattr(args, "json", None):
        report.write_json(args.json, report.build_report(
            gate, cfg, lang, args.base, _commit(), True, skipped=True))
    return True


# ---------- 第一關：單元測試 ----------

def cmd_test(args, cfg, lang):
    if not_enabled("test", args, cfg, lang):
        return 0
    return 0 if lang.run_tests(cfg) == 0 else 1


# ---------- 第二關：CRAP ----------

def cmd_crap(args, cfg, lang):
    if not_enabled("crap", args, cfg, lang):
        return 0
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
    if not_enabled("mutation", args, cfg, lang):
        return 0
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


# ---------- check：依序跑已啟用的關 ----------

def plan_gates(gates, skip):
    """回傳 (要跑的關, 略過的關, 還沒啟用的關)。順序固定是 test → crap → mutation，跟 gates 裡的排列無關。

    --skip 給了不認得的名稱，丟 QualityError（結束碼 2）。
    """
    bad = [s for s in skip if s not in config.GATES]
    if bad:
        raise QualityError("--skip 不認得的關：{}（可用：{}）".format("、".join(bad), "、".join(config.GATES)))
    ordered = [g for g in config.GATES if g in gates]
    run = [g for g in ordered if g not in skip]
    return run, [g for g in ordered if g in skip], [g for g in config.GATES if g not in gates]


def cmd_check(args, cfg, lang):
    run, skipped, disabled = plan_gates(cfg["gates"], args.skip)
    base = args.base or cfg["base"]
    print("比較基準：" + base)
    gate_cmds = {"test": cmd_test, "crap": cmd_crap, "mutation": cmd_mutation}
    if args.json:
        os.makedirs(args.json, exist_ok=True)
    for gate in run:
        n = config.GATES.index(gate) + 1
        print("== 第 {} 關：{} ==".format(n, gate), flush=True)
        # test 沒有 JSON 報告；沒跑到的關不寫檔
        json_path = os.path.join(args.json, gate + ".json") if args.json and gate != "test" else None
        try:
            code = gate_cmds[gate](argparse.Namespace(base=base, json=json_path), cfg, lang)
        except QualityError as e:
            sys.stdout.flush()  # stdout 和 stderr 接到同一條管線時，前面的輸出要先出去，順序才對
            print(e, file=sys.stderr, flush=True)
            code = e.exit_code
        if code != 0:
            print("\n停在第 {} 關".format(n))
            return code
    print("\nPASS：已啟用的 {} 關都通過（略過：{}；還沒啟用：{}）".format(
        len(run), "、".join(skipped) or "無", "、".join(disabled) or "無"))
    return 0


# ---------- 量現況 ----------

def cmd_baseline(args, cfg, lang):
    old = baseline.load_report(args.compare) if args.compare else None  # 舊報告讀不了就先停，不浪費量測時間
    entries = equivalents.load(cfg["mutation"]["equivalents_file"])
    funcs = crap.score_functions(lang.measure_functions(cfg))
    mutants = lang.measure_mutants(cfg)
    settings = lang.settings(cfg)
    unused = classify(mutants, mutants, settings, entries, None)
    churn = baseline.compute_churn(funcs, cfg)
    data = baseline.build_json(funcs, mutants, cfg, lang, churn, settings, unused)
    diff = baseline.compare_lines(old, data) if old else None
    out = args.out or cfg["baseline"]["out"]
    baseline.write_baseline(funcs, mutants, cfg, lang, out, unused, churn, diff)
    report.write_json(baseline.json_path(out), data)
    print("已寫入 {} 和 {}".format(out, baseline.json_path(out)))
    if diff:
        print("\n跟上一次比較（{}）".format(args.compare))
        print("\n".join(diff))
    return 0


def cmd_compare(args):
    """不量測，只讀兩份 baseline JSON 印出前後差。只呈現，不判定，結束碼一律 0（讀不了或格式不對是 2）。"""
    print("\n".join(baseline.compare_lines(baseline.load_report(args.old), baseline.load_report(args.new))))
    return 0


def _commit():
    return git("rev-parse", "HEAD").strip()
