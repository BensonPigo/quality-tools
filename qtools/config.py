"""讀取、驗證 .quality.json（v2）。

設定檔寫錯不能默默變成預設值：沒有 version 或不是 2、未知的鍵、型別不對都直接報錯（結束碼 2）。
"""

import copy
import json
import os

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
    if raw.get("version") != 2:
        raise QualityError("{} 的 version 必須是 2".format(CONFIG_FILE))

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
