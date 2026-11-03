"""現況報告：在現有程式上量一次，寫成 markdown 和同名的 JSON，當作技術債清單。

超標的函式另外算修改次數（git log -L），修改次數夠多的標「優先處理」。
也可以跟上一次的 JSON 報告比較（compare_lines）。
"""

import datetime
import json
import os
import re

from qtools import crap, mutation
from qtools.model import EQUIVALENT, EXCLUDED_MUTATOR, KILLED, LIVED, NOT_COVERED, STATUS_NAMES, TIMED_OUT
from qtools.proc import QualityError, git, run
from qtools.report import build_report, crap_json, hot, mutation_json, pct
from qtools.report_schema import SCHEMA_VERSION, validate

COMMIT_MARK = "commit:"  # git log -L 的 --format，用來切開每個 commit


# ---------- 修改次數 ----------

def parse_churn(log_output):
    """數 git log -L 輸出（--format=commit:%H，帶 patch）裡有幾個 commit，不算建立這段程式的那個。

    輸出由新到舊，每個 commit 是一行 commit:<hash>，接著是這段範圍的 diff。最舊的那個 commit 如果它的每個 hunk
    舊側長度都是 0（@@ -X,0 +...，含新檔案的 --- /dev/null），就是建立的 commit（建立不算修改），不計入。
    只新增行但舊側長度不是 0（例如在既有函式裡加一行註解）是修改，要算。
    """
    commits = []  # 每個元素是這個 commit 各 hunk 的舊側長度
    for line in log_output.splitlines():
        if line.startswith(COMMIT_MARK):
            commits.append([])
        elif line.startswith("@@") and commits:
            m = re.match(r"@@ -\d+(?:,(\d+))? ", line)
            commits[-1].append(int(m.group(1)) if m and m.group(1) is not None else 1)
    churn = len(commits)
    if commits and commits[-1] and all(n == 0 for n in commits[-1]):
        churn -= 1
    return churn


def count_churn(file, start, end, since):
    """一個函式在 since 之後被修改過幾次。檔案還沒 commit、git 回報找不到這段行，都算 0。"""
    r = run(["git", "-c", "core.quotepath=false", "log", "--no-color", "--since=" + since,
             "--format=" + COMMIT_MARK + "%H", "-L", "{},{}:{}".format(start, end, file)])
    return parse_churn(r.stdout) if r.returncode == 0 else 0


def churn_key(f):
    return (f.file, f.name, f.start)


def compute_churn(funcs, cfg):
    """只對超標的函式算修改次數，回傳 {(file, name, start): 次數}。沒超標的不在裡面。"""
    threshold = cfg["crap"]["threshold"]
    since = cfg["baseline"]["churn_since"]
    return {churn_key(f): count_churn(f.file, f.start, f.end, since) for f in funcs if f.crap > threshold}


def is_hot(f, churn, cfg):
    return hot(f.crap > cfg["crap"]["threshold"], churn.get(churn_key(f)), cfg["baseline"]["hot_churn"])


def order_functions(funcs, churn, cfg):
    """優先處理的排最前面，其餘照 CRAP 由高到低。"""
    return sorted(funcs, key=lambda f: (not is_hot(f, churn, cfg), -f.crap))


# ---------- 報告 ----------

def build_json(funcs, mutants, cfg, lang, churn, settings, unused=()):
    """baseline 的 JSON 報告：command 是 baseline，crap 和 mutation 都有，functions 列出全部函式。"""
    funcs = order_functions(funcs, churn, cfg)
    return build_report(
        "baseline", cfg, lang, None, git("rev-parse", "HEAD").strip(), True,
        crap_part=crap_json(funcs, cfg["crap"]["threshold"], 0, churn, cfg["baseline"]["hot_churn"]),
        mutation_part=mutation_json(mutants, mutation.count(mutants), cfg, lang.report_group, settings, unused))


def json_path(out_path):
    """報告檔名去掉副檔名，加上 .json。"""
    return os.path.splitext(out_path)[0] + ".json"


SCOPE_TEXT = {
    "package": "覆蓋率只算同一個套件的測試（go.coverage_scope = package）。",
    "module": "覆蓋率算整個模組的測試，其他套件的測試執行到的程式碼也算（go.coverage_scope = module）。",
}
MUTATION_SCOPE_TEXT = {
    "package": "每個改壞的版本只跑同一個套件的測試（go.coverage_scope = package）。",
    "module": "每個改壞的版本跑整個模組的測試（go.coverage_scope = module，gremlins --integration --coverpkg）。",
}


def write_baseline(funcs, mutants, cfg, lang, out_path, unused=(), churn=None, diff=None):
    """diff 是 compare_lines 的結果，有的話在最後加「## 跟上一次比較」。"""
    threshold = cfg["crap"]["threshold"]
    hot_churn = cfg["baseline"]["hot_churn"]
    churn = churn or {}
    funcs = order_functions(funcs, churn, cfg)

    out = []
    out.append("# 品質現況\n")
    out.append("量測日期：{}，commit：{}\n".format(datetime.date.today(), git("rev-parse", "--short", "HEAD").strip()))

    out.append("## CRAP\n")
    passed = sum(1 for f in funcs if f.crap <= threshold)
    split = sum(1 for f in funcs if f.crap > threshold and f.complexity > threshold)
    hot_count = sum(1 for f in funcs if is_hot(f, churn, cfg))
    out.append("門檻 {}。函式總數 {}，通過 {}，超標 {}（補測試就能過 {}，要拆函式 {}），優先處理 {}。\n".format(
        threshold, len(funcs), passed, len(funcs) - passed, len(funcs) - passed - split, split, hot_count))
    if "coverage_scope" in lang.tools:
        out.append(SCOPE_TEXT[lang.tools["coverage_scope"]] + "\n")
    out.append("修改次數是 {} 以來改到這個函式的 commit 數（建立的那一次不算），只算超標的函式。"
               "超標且修改次數 ≥ {} 的標「優先處理」，排在最前面。\n".format(cfg["baseline"]["churn_since"], hot_churn))
    out.append("| CRAP | C | 覆蓋率 | 修改次數 | 函式 | 位置 | 改善方向 | 優先處理 |")
    out.append("|---|---|---|---|---|---|---|---|")
    for f in funcs:
        if f.crap > threshold:
            out.append("| {:.1f} | {} | {:.1f}% | {} | `{}` | `{}:{}` | {} | {} |".format(
                f.crap, f.complexity, f.coverage * 100, churn.get(churn_key(f), 0), f.name, f.file, f.start,
                crap.advice_text(f.complexity, threshold), "優先處理" if is_hot(f, churn, cfg) else ""))
    if passed == len(funcs):
        out.append("| — | — | — | — | 沒有超標的函式 | — | — | — |")
    out.append("")

    out.append("## 抓錯檢查\n")
    out.append("抓錯率 =（抓到 + 逾時）÷（抓到 + 逾時 + 沒抓到），看有測到的程式碼測得夠不夠嚴。")
    out.append("測到率 =（抓到 + 逾時 + 沒抓到）÷（再加上測試沒跑到），看有多少程式碼有測試。兩個數字要一起看。\n")
    if "mutation_scope" in lang.tools:
        out.append(MUTATION_SCOPE_TEXT[lang.tools["mutation_scope"]] + "\n")
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
    counts = mutation.count(mutants)
    excluded = ["{} {}".format(STATUS_NAMES[s], counts[s]) for s in (EQUIVALENT, EXCLUDED_MUTATOR) if counts[s]]
    if excluded:
        out += ["{}（不算進上表的抓錯率和測到率）。".format("、".join(excluded)), ""]
    if unused:
        out += ["排除清單有 {} 項沒用到：那一行的原文或改法已經變了，請重新判斷，或從清單刪掉。".format(len(unused)), ""]
    if diff:
        out += ["## 跟上一次比較\n"] + ["- " + line for line in diff] + [""]

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))


# ---------- 比較 ----------

def load_report(path):
    """讀一份 baseline JSON。不是 baseline、schema 版本不同、或格式比對沒過，都丟 QualityError（結束碼 2）。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        raise QualityError("讀不到 {}：{}".format(path, e))
    except ValueError as e:
        raise QualityError("{} 不是合法的 JSON：{}".format(path, e))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        raise QualityError("{} 的 schema 版本是 {!r}，這個版本的工具只認得 {}".format(
            path, data.get("schema") if isinstance(data, dict) else None, SCHEMA_VERSION))
    errors = validate(data)
    if errors:
        raise QualityError("{} 格式不符：\n  {}".format(path, "\n  ".join(errors[:10])))
    if data["command"] != "baseline":
        raise QualityError("{} 不是現況報告（command 是 {}，要是 baseline）".format(path, data["command"]))
    return data


def _count_change(old, new):
    """「舊 → 新（差）」，用在整數。"""
    return "{} → {}（{}）".format(old, new, "±0" if new == old else "{:+d}".format(new - old))


def _rate_change(old, new):
    if old is None or new is None:  # 其中一邊沒量到改壞的版本，不算差
        return "{} → {}".format(pct(old), pct(new))
    delta = round(new - old, 2)  # 四捨五入到百分點的小數第二位，免得浮點誤差印出 +0.0000001
    return "{} → {}（{}）".format(pct(old), pct(new), "±0 百分點" if delta == 0 else "{:+.2f} 百分點".format(delta))


def _count_summary(report):
    funcs = report["crap"]["functions"]
    return {
        "函式總數": len(funcs),
        "超標函式數": sum(1 for f in funcs if f["over"]),
        "要拆函式數": sum(1 for f in funcs if f["over"] and f["advice"] == "split"),
        "優先處理數": sum(1 for f in funcs if f["hot"]),
    }


def _go_scope(report, key):
    scope = report["tools"].get(key)
    if scope is None and report["language"] == "go":
        return "package"
    return scope


def coverage_scope(report):
    """Go 報告 CRAP 的覆蓋率範圍。v2.1.0 以前的 Go 報告沒有記錄，那時只有 package；其他語言回傳 None。"""
    return _go_scope(report, "coverage_scope")


def mutation_scope(report):
    """Go 報告抓錯檢查的範圍。v2.2.0 以前的 Go 報告沒有記錄，那時一律分套件（package）；其他語言回傳 None。"""
    return _go_scope(report, "mutation_scope")


def compare_lines(old, new):
    """兩份 baseline JSON 的前後差，每項一行「舊 → 新（差）」，比例差用百分點。"""
    lines = ["舊報告：commit {}；新報告：commit {}".format(old["commit"][:7], new["commit"][:7])]
    old_scope, new_scope = coverage_scope(old), coverage_scope(new)
    if old_scope != new_scope:
        lines.append("覆蓋率範圍不同（{} → {}），CRAP 的變化主要來自量法改變".format(old_scope, new_scope))
    old_scope, new_scope = mutation_scope(old), mutation_scope(new)
    if old_scope != new_scope:
        lines.append("抓錯檢查的範圍不同（{} → {}），抓錯率和測到率的變化主要來自量法改變".format(old_scope, new_scope))
    old_counts, new_counts = _count_summary(old), _count_summary(new)
    for name in old_counts:
        lines.append("{}：{}".format(name, _count_change(old_counts[name], new_counts[name])))
    om, nm = old["mutation"], new["mutation"]
    lines.append("整體抓錯率：" + _rate_change(om["kill_rate"], nm["kill_rate"]))
    lines.append("整體測到率：" + _rate_change(om["reach_rate"], nm["reach_rate"]))
    old_pkgs = {p["package"]: p for p in om["packages"]}
    new_pkgs = {p["package"]: p for p in nm["packages"]}
    for pkg in sorted(set(old_pkgs) | set(new_pkgs)):
        if pkg not in old_pkgs:
            lines.append("套件 {}：新增（抓錯率 {}，測到率 {}）".format(
                pkg, pct(new_pkgs[pkg]["kill_rate"]), pct(new_pkgs[pkg]["reach_rate"])))
        elif pkg not in new_pkgs:
            lines.append("套件 {}：已移除（原本抓錯率 {}，測到率 {}）".format(
                pkg, pct(old_pkgs[pkg]["kill_rate"]), pct(old_pkgs[pkg]["reach_rate"])))
        else:
            lines.append("套件 {}：抓錯率 {}；測到率 {}".format(
                pkg, _rate_change(old_pkgs[pkg]["kill_rate"], new_pkgs[pkg]["kill_rate"]),
                _rate_change(old_pkgs[pkg]["reach_rate"], new_pkgs[pkg]["reach_rate"])))
    return lines
