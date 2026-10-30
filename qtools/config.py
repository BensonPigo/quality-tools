"""讀取、驗證 .quality.json（v2），以及把 v1 設定檔轉成 v2（migrate）。

設定檔寫錯不能默默變成預設值：未知的鍵、型別不對都直接報錯（結束碼 2）。
讀到 v1 的鍵名，或沒有 version，訊息會叫人執行 quality.py migrate。
"""

import copy
import difflib
import json
import os
import re

from qtools.proc import QualityError

CONFIG_FILE = ".quality.json"
LANGUAGES = ["go", "csharp", "js", "python"]
GATES = ["test", "crap", "mutation"]

DEFAULTS = {
    "version": 2,
    "language": "",
    "base": "origin/main",
    "gates": ["test", "crap", "mutation"],
    "exclude": ["tools/", "vendor/", "node_modules/"],
    "crap": {"threshold": 12},
    "mutation": {
        "kill_rate_threshold": 80,
        "reach_rate_threshold": 50,  # 測到率一定要設門檻：沒有門檻，新寫的程式完全沒有測試也能過關
        "timeout_seconds": None,
        "workers": None,
        "exclude_mutators": None,
        "equivalents_file": ".quality-equivalents.json",
    },
    "baseline": {"out": "docs/品質現況.md", "churn_since": "6 months ago", "hot_churn": 5},
    "csharp": {"solution": None},
    "js": {"test_runner": None},
    "python": {"interpreter": None},
}

# v1 的鍵名。出現其中任何一個，就是還沒轉換的設定檔
V1_KEYS = ["efficacy_threshold", "mutant_coverage_threshold", "crap_threshold", "dotnet_solution",
           "js_test_runner", "python_mutant_timeout"]

MIGRATE_HINT = "請在專案根目錄執行 python tools/quality/quality.py migrate，把設定檔轉成 v2"


def load_config(path=CONFIG_FILE):
    if not os.path.exists(path):
        raise QualityError("找不到 {}，請在專案根目錄執行".format(path))
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except ValueError as e:
        raise QualityError("{} 不是合法的 JSON：{}".format(path, e))
    return validate(raw)


def validate(raw):
    """檢查設定檔內容，回傳補上預設值的完整設定。"""
    if not isinstance(raw, dict):
        raise QualityError("{} 的最外層必須是物件".format(CONFIG_FILE))
    if _is_v1(raw):
        raise QualityError("{} 是 v1 格式（沒有 version，或用了 v1 的鍵名）。{}".format(CONFIG_FILE, MIGRATE_HINT))
    if raw["version"] != 2:
        raise QualityError("{} 的 version 是 {!r}，這個版本的工具只認得 2".format(CONFIG_FILE, raw["version"]))

    problems = []
    cfg = copy.deepcopy(DEFAULTS)
    for key, value in raw.items():
        if key not in DEFAULTS:
            problems.append("不認得的鍵：{}".format(key))
        elif isinstance(DEFAULTS[key], dict):
            if not isinstance(value, dict):
                problems.append("{} 必須是物件".format(key))
                continue
            for sub, subvalue in value.items():
                if sub not in DEFAULTS[key]:
                    problems.append("不認得的鍵：{}.{}".format(key, sub))
                else:
                    cfg[key][sub] = subvalue
        else:
            cfg[key] = value

    if not problems:
        problems = _check_values(cfg)
    if problems:
        raise QualityError("{} 有誤：\n  ".format(CONFIG_FILE) + "\n  ".join(problems))
    return cfg


def _is_v1(raw):
    # v1 的 python 鍵是字串（直譯器路徑），v2 的 python 是物件
    return "version" not in raw or any(k in raw for k in V1_KEYS) or isinstance(raw.get("python"), str)


def _check_values(cfg):
    problems = []

    def need(ok, message):
        if not ok:
            problems.append(message)

    need(cfg["language"] in LANGUAGES, "language 必須是 {} 其中之一（目前是 {!r}）".format("、".join(LANGUAGES), cfg["language"]))
    need(isinstance(cfg["base"], str) and cfg["base"], "base 必須是分支名稱的字串")
    need(isinstance(cfg["gates"], list) and all(g in GATES for g in cfg["gates"]),
         "gates 必須是 {} 的子集合的陣列".format("、".join(GATES)))
    need(isinstance(cfg["exclude"], list) and all(isinstance(e, str) for e in cfg["exclude"]), "exclude 必須是字串陣列")
    need(_number(cfg["crap"]["threshold"]), "crap.threshold 必須是數字")
    m = cfg["mutation"]
    need(_number(m["kill_rate_threshold"]), "mutation.kill_rate_threshold 必須是數字")
    need(_number(m["reach_rate_threshold"]), "mutation.reach_rate_threshold 必須是數字")
    need(m["timeout_seconds"] is None or (_number(m["timeout_seconds"]) and m["timeout_seconds"] > 0),
         "mutation.timeout_seconds 必須是正數，或 null（用工具預設）")
    need(m["workers"] is None or (isinstance(m["workers"], int) and not isinstance(m["workers"], bool) and m["workers"] > 0),
         "mutation.workers 必須是正整數，或 null（用工具預設）")
    need(m["exclude_mutators"] is None
         or (isinstance(m["exclude_mutators"], list) and all(isinstance(x, str) for x in m["exclude_mutators"])),
         "mutation.exclude_mutators 必須是字串陣列，或 null（用工具預設）")
    need(isinstance(m["equivalents_file"], str) and m["equivalents_file"], "mutation.equivalents_file 必須是檔名的字串")
    b = cfg["baseline"]
    need(isinstance(b["out"], str) and b["out"], "baseline.out 必須是檔名的字串")
    need(isinstance(b["churn_since"], str) and b["churn_since"], "baseline.churn_since 必須是字串，例如 \"6 months ago\"")
    need(isinstance(b["hot_churn"], int) and not isinstance(b["hot_churn"], bool), "baseline.hot_churn 必須是整數")
    need(cfg["csharp"]["solution"] is None or isinstance(cfg["csharp"]["solution"], str), "csharp.solution 必須是字串或 null")
    need(cfg["js"]["test_runner"] in (None, "vitest", "jest"), "js.test_runner 必須是 vitest、jest 或 null")
    need(cfg["python"]["interpreter"] is None or isinstance(cfg["python"]["interpreter"], str),
         "python.interpreter 必須是字串或 null")
    return problems


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ---------- migrate：v1 → v2 ----------

def migrate_config(v1, notes=None):
    """v1 設定（dict）轉成 v2（dict）。每個有預設值的門檻都明寫出來，轉換後的判定結果跟 v1 一樣。

    v1 沒寫 mutant_coverage_threshold 時，實際行為是 0（不擋），所以照搬 0，不自動調成 v2 新設定檔的 50。
    notes 給了就把轉換時略過的鍵寫進去（字串串列），由呼叫端印給使用者看。
    """
    if "version" in v1:
        raise QualityError("{} 已經是 v2 格式".format(CONFIG_FILE))
    known = set(V1_KEYS) | {"language", "base", "exclude", "python"}
    unknown = sorted(set(v1) - known)
    if unknown:
        raise QualityError("{} 有 v1 也不認得的鍵：{}。確認拼字後再執行 migrate".format(CONFIG_FILE, "、".join(unknown)))
    if not v1.get("language"):
        raise QualityError("{} 沒有 language，沒辦法轉換".format(CONFIG_FILE))

    mutation = {
        "kill_rate_threshold": v1.get("efficacy_threshold", 80),
        "reach_rate_threshold": v1.get("mutant_coverage_threshold", 0),
    }
    if "python_mutant_timeout" in v1:
        # v1 只有 Python 讀這個鍵；其他語言原本就沒作用，轉成 timeout_seconds 會讓 C#、JS 的行為悄悄改變
        if v1["language"] == "python":
            mutation["timeout_seconds"] = v1["python_mutant_timeout"]
        elif notes is not None:
            notes.append("python_mutant_timeout：這個鍵只對 Python 有效，已略過")
    v2 = {
        "version": 2,
        "language": v1["language"],
        "base": v1.get("base", "origin/main"),
        "gates": ["test", "crap", "mutation"],  # v1 的行為：三關都跑
        "exclude": v1.get("exclude", ["tools/", "vendor/", "node_modules/"]),
        "crap": {"threshold": v1.get("crap_threshold", 12)},
        "mutation": mutation,
    }
    for old, section, key in (("dotnet_solution", "csharp", "solution"), ("js_test_runner", "js", "test_runner"),
                              ("python", "python", "interpreter")):
        if v1.get(old):
            v2[section] = {key: v1[old]}
    return v2


def migrate_file(path=CONFIG_FILE):
    """改寫 .quality.json，回傳前後差異的文字。"""
    if not os.path.exists(path):
        raise QualityError("找不到 {}，請在專案根目錄執行".format(path))
    with open(path, encoding="utf-8") as f:
        old_text = f.read()
    try:
        v1 = json.loads(old_text)
    except ValueError as e:
        raise QualityError("{} 不是合法的 JSON：{}".format(path, e))
    if not isinstance(v1, dict):
        raise QualityError("{} 的最外層必須是物件".format(path))
    notes = []
    new_text = _dumps(migrate_config(v1, notes))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_text)
    diff = "".join(difflib.unified_diff(old_text.splitlines(True), new_text.splitlines(True), "舊（v1）", "新（v2）"))
    return diff + "".join(n + "\n" for n in notes)


def _dumps(data):
    """縮排 2 格；字串陣列寫成一行，gates 和 exclude 才好讀。"""
    text = json.dumps(data, ensure_ascii=False, indent=2)
    return re.sub(r'\[\s*("[^"\n]*"(?:,\s*"[^"\n]*")*)\s*\]',
                  lambda m: "[" + re.sub(r",\s+", ", ", m.group(1)) + "]", text) + "\n"
