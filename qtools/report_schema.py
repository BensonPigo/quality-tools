"""JSON 報告的格式，四種語言共用同一份。用 Python 的 dict 描述必填欄位和型別，validate 用標準函式庫比對。

欄位多或少都算錯：多出來的欄位代表程式和格式說明對不上，應該在這裡補上，不能默默放行。

描述方式：
    str / int / bool       該型別（int 不收 bool）
    Num                    int 或 float（不收 bool）
    Opt(x)                 x 或 null
    Lst(x)                 x 的陣列
    Dic(x)                 字串鍵、x 值的物件
    Enum(a, b, ...)        其中之一
    {欄位: 描述, ...}      物件，欄位要完全一致
"""


class Num:
    pass


class Opt:
    def __init__(self, spec):
        self.spec = spec


class Lst:
    def __init__(self, spec):
        self.spec = spec


class Dic:
    def __init__(self, spec):
        self.spec = spec


class Enum:
    def __init__(self, *values):
        self.values = values


COUNTS = Dic(int)

CRAP_FUNCTION = {
    "file": str, "name": str, "start": int, "end": int, "complexity": int,
    "coverage": Num, "crap": Num, "over": bool,
    "advice": Opt(Enum("split", "cover")), "need_coverage": Opt(Num),
    "churn": Opt(int), "hot": bool,
}

MUTANT = {
    "file": str, "line": int, "column": Opt(int), "function": Opt(str), "mutator": str, "status": str,
    "original": Opt(str), "replacement": Opt(str), "line_text": str,
}

REPORT = {
    "schema": int,
    "command": Enum("crap", "mutation", "baseline"),
    "tool_version": str,
    "language": str,
    "base": Opt(str),
    "commit": str,
    "result": Enum("pass", "fail"),
    "tools": Dic(str),
    "crap": Opt({
        "threshold": Num,
        "functions": Lst(CRAP_FUNCTION),
        "untouched_over": int,
    }),
    "mutation": Opt({
        "kill_rate_threshold": Num,
        "reach_rate_threshold": Num,
        "counts": COUNTS,
        "kill_rate": Opt(Num),
        "reach_rate": Opt(Num),
        "mutants": Lst(MUTANT),
        "packages": Lst({"package": str, "counts": COUNTS, "kill_rate": Opt(Num), "reach_rate": Opt(Num)}),
        "settings": {"timeout_seconds": Opt(Num), "workers": Opt(int), "exclude_mutators": Lst(str)},
        "unused_equivalents": Lst(dict),
    }),
}

SCHEMA_VERSION = 1


def validate(data):
    """回傳錯誤訊息的串列，空串列代表格式正確。"""
    errors = []
    _check(data, REPORT, "$", errors)
    if isinstance(data, dict) and not errors:
        # crap 指令的 mutation 是 null，mutation 指令的 crap 是 null，baseline 兩者都有
        want = {"crap": (True, False), "mutation": (False, True), "baseline": (True, True)}[data["command"]]
        have = (data["crap"] is not None, data["mutation"] is not None)
        if have != want:
            errors.append("$：command 是 {} 時，crap 和 mutation 要{}有值".format(
                data["command"], "、".join(n for n, w in zip(("crap", "mutation"), want) if w) or "都沒"))
    return errors


def _check(value, spec, path, errors):
    if isinstance(spec, Opt):
        if value is not None:
            _check(value, spec.spec, path, errors)
    elif isinstance(spec, dict):
        if not isinstance(value, dict):
            errors.append("{}：應該是物件".format(path))
            return
        for key in spec:
            if key not in value:
                errors.append("{}：缺少欄位 {}".format(path, key))
        for key in value:
            if key not in spec:
                errors.append("{}：多出欄位 {}".format(path, key))
        for key in spec:
            if key in value:
                _check(value[key], spec[key], "{}.{}".format(path, key), errors)
    elif isinstance(spec, Lst):
        if not isinstance(value, list):
            errors.append("{}：應該是陣列".format(path))
            return
        for i, item in enumerate(value):
            _check(item, spec.spec, "{}[{}]".format(path, i), errors)
    elif isinstance(spec, Dic):
        if not isinstance(value, dict):
            errors.append("{}：應該是物件".format(path))
            return
        for key, item in value.items():
            if not isinstance(key, str):
                errors.append("{}：鍵必須是字串".format(path))
            _check(item, spec.spec, "{}.{}".format(path, key), errors)
    elif isinstance(spec, Enum):
        if value not in spec.values:
            errors.append("{}：應該是 {} 其中之一（目前是 {!r}）".format(path, "、".join(map(repr, spec.values)), value))
    elif spec is Num:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append("{}：應該是數字（目前是 {!r}）".format(path, value))
    elif spec is dict:
        if not isinstance(value, dict):
            errors.append("{}：應該是物件".format(path))
    elif spec is int:
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append("{}：應該是整數（目前是 {!r}）".format(path, value))
    elif spec is bool:
        if not isinstance(value, bool):
            errors.append("{}：應該是 true 或 false（目前是 {!r}）".format(path, value))
    elif spec is str:
        if not isinstance(value, str):
            errors.append("{}：應該是字串（目前是 {!r}）".format(path, value))
