"""文字輸出和 JSON 報告。四種語言共用同一份格式（見 report_schema.py）。"""

import json

from qtools import __version__, crap, mutation
from qtools.model import KILLED, LIVED, NOT_COVERED, STATUS_NAMES, TIMED_OUT
from qtools.report_schema import SCHEMA_VERSION


def pct(v):
    return "—" if v is None else "{:.2f}%".format(v)


# ---------- CRAP ----------

def print_crap_table(funcs, threshold, with_advice):
    """印出 CRAP 表格，回傳超過門檻的函式數量。with_advice 為 True 時，超標的函式後面附上改善方向。"""
    print("{:<8} {:<6} {:<8} {:<24} {}".format("CRAP", "C", "覆蓋率", "函式", "位置"))
    failed = 0
    for f in funcs:
        mark = "  "
        if f.crap > threshold:
            failed += 1
            mark = "❌"
            if with_advice:
                mark += " " + crap.advice_text(f.complexity, threshold)
        print("{:<8.1f} {:<6} {:<8} {:<24} {}:{} {}".format(
            f.crap, f.complexity, "{:.1f}%".format(f.coverage * 100), f.name, f.file, f.start, mark))
    return failed


def crap_json(funcs, threshold, untouched_over):
    items = []
    for f in funcs:
        over = f.crap > threshold
        kind, need = crap.advice(f.complexity, threshold) if over else (None, None)
        items.append({
            "file": f.file, "name": f.name, "start": f.start, "end": f.end,
            "complexity": f.complexity, "coverage": f.coverage, "crap": f.crap, "over": over,
            "advice": kind, "need_coverage": need,
            "churn": None, "hot": False,  # 修改次數和優先處理由 baseline 填入（S4）
        })
    return {"threshold": threshold, "functions": items, "untouched_over": untouched_over}


# ---------- 抓錯檢查 ----------

def print_mutation_result(mutants, counts, cfg):
    """列出沒抓到和測試沒跑到的改壞版本，加上計數、抓錯率和測到率。"""
    for m in sorted(mutants, key=lambda m: (m.file, m.line)):
        if m.status in (LIVED, NOT_COVERED):
            print("{:<12} {:<24} {}:{}  {}".format(
                STATUS_NAMES[m.status].split("（")[0], m.mutator, m.file, m.line, m.line_text))

    k = cfg["mutation"]["kill_rate_threshold"]
    r = cfg["mutation"]["reach_rate_threshold"]
    print()
    print("抓到 {}、逾時 {}（算抓到）、沒抓到 {}、測試沒跑到 {}".format(
        counts[KILLED], counts[TIMED_OUT], counts[LIVED], counts[NOT_COVERED]))
    print("抓錯率：{}（門檻 {}%）".format(pct(mutation.kill_rate(counts)), k))
    print("測到率：{}（門檻 {}%）".format(pct(mutation.reach_rate(counts)), r))


def mutation_json(mutants, counts, cfg, group):
    m = cfg["mutation"]
    items = [{
        "file": x.file, "line": x.line, "column": x.column, "function": None, "mutator": x.mutator,
        "status": x.status, "original": x.original, "replacement": x.replacement, "line_text": x.line_text,
    } for x in sorted(mutants, key=lambda x: (x.file, x.line))]
    packages = [{"package": p, "counts": c, "kill_rate": mutation.kill_rate(c), "reach_rate": mutation.reach_rate(c)}
                for p, c in sorted(mutation.by_package(mutants, group).items())]
    return {
        "kill_rate_threshold": m["kill_rate_threshold"],
        "reach_rate_threshold": m["reach_rate_threshold"],
        "counts": counts,
        "kill_rate": mutation.kill_rate(counts),
        "reach_rate": mutation.reach_rate(counts),
        "mutants": items,
        "packages": packages,
        "unused_equivalents": [],  # 排除清單比對由 S2 加入
    }


# ---------- JSON 報告 ----------

def build_report(command, cfg, lang, base, commit, passed, crap_part=None, mutation_part=None):
    return {
        "schema": SCHEMA_VERSION,
        "command": command,
        "tool_version": __version__,
        "language": cfg["language"],
        "base": base,
        "commit": commit,
        "result": "pass" if passed else "fail",
        "tools": dict(lang.tools),
        "crap": crap_part,
        "mutation": mutation_part,
    }


def write_json(path, data):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
