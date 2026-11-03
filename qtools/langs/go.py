"""Go 的量測轉換：覆蓋率用 go test -cover，圈複雜度用 gocyclo，抓錯檢查用 gremlins。"""

import json
import os
import posixpath
import subprocess
import sys
import tempfile

from qtools.langs.base import DEFAULTS as BASE_DEFAULTS
from qtools.langs.base import Language
from qtools.model import Function, Mutant
from qtools.mutation import source_lines
from qtools.proc import QualityError, is_excluded, normalize, run

GOCYCLO = "github.com/fzipp/gocyclo/cmd/gocyclo@v0.6.0"
GREMLINS = "github.com/go-gremlins/gremlins/cmd/gremlins@v0.6.0"

DEFAULTS = dict(BASE_DEFAULTS)  # 不排除任何改法；gremlins 沒有 timeout 設定，維持 --timeout-coefficient 30
NO_RESULTS = "No results to report."  # gremlins v0.6.0 沒有任何改壞的版本時印這行，不寫結果檔
TIMEOUT_COEFFICIENT = "30"  # 測試很快時，gremlins 估的時限太短，會誤判成 TIMED OUT

# 下面兩張表抄自 gremlins v0.6.0 原始碼（Go module cache 的 github.com/go-gremlins/gremlins@v0.6.0）：
#   internal/mutator/mutator.go  的 Type.String()：報告裡 type 欄位的名稱
#   internal/engine/mappings.go  的 tokenMutations：每種 type 把哪個 token 換成哪個 token
# token 換成它在 Go 裡的寫法（go/token 的 Token.String()）。報告只給 type 和位置，原本的 token 要回原始檔取，
# 取出來之後查這張表就知道改成什麼。
_ASSIGN_OPS = ["+=", "&=", "&^=", "*=", "|=", "/=", "%=", "<<=", ">>=", "-=", "^="]
GREMLINS_TOKENS = {
    "ARITHMETIC_BASE": {"+": "-", "*": "/", "/": "*", "%": "*", "-": "+"},
    "CONDITIONALS_BOUNDARY": {">=": ">", ">": ">=", "<=": "<", "<": "<="},
    "CONDITIONALS_NEGATION": {"==": "!=", ">=": "<", ">": "<=", "<=": ">", "<": ">=", "!=": "=="},
    "INCREMENT_DECREMENT": {"--": "++", "++": "--"},
    # 原始碼裡 REM_ASSIGN 對到它自己（%= 改成 %=），照抄；這個改壞版本等於沒改
    "INVERT_ASSIGNMENTS": {"+=": "-=", "*=": "/=", "/=": "*=", "%=": "%=", "-=": "+="},
    "INVERT_BITWISE": {"&": "|", "|": "&", "^": "&", "&^": "&", "<<": ">>", ">>": "<<"},
    "INVERT_BWASSIGN": {"&=": "|=", "|=": "&=", "^=": "&=", "&^=": "&=", "<<=": ">>=", ">>=": "<<="},
    "INVERT_LOGICAL": {"&&": "||", "||": "&&"},
    "INVERT_LOOPCTRL": {"break": "continue", "continue": "break"},
    "INVERT_NEGATIVES": {"-": "+"},
    "REMOVE_SELF_ASSIGNMENTS": {op: "=" for op in _ASSIGN_OPS},
}


def gremlins_describe(mutator, line, column):
    """依 type 和欄位（從 1 起算的位元組位置）從該行取出原本的 token，回傳 (original, replacement)，取不到回傳 (None, None)。"""
    table = GREMLINS_TOKENS.get(mutator)
    if not table or not column:
        return None, None
    rest = line.encode("utf-8")[column - 1:].decode("utf-8", errors="replace")
    for token in sorted(table, key=len, reverse=True):  # 先比長的：>>= 在 >> 和 > 之前
        if rest.startswith(token):
            return token, table[token]
    return None, None


def gremlins_args(settings, d, out, subdirs=(), skip_files=()):
    """gremlins unleash 的命令列參數。settings 是 Language.settings 的結果，沒設的項目不傳（維持 v1 行為）。

    skip_files 是套件目錄底下不產生改壞版本的檔名。
    """
    args = ["unleash", "./" + d,
            "--timeout-coefficient", TIMEOUT_COEFFICIENT,
            "--invert-logical",  # 預設關閉的 && ↔ || 互換
            "-o", out]
    if settings["workers"] is not None:
        args += ["--workers", str(settings["workers"])]
    for sub in subdirs:
        args += ["-E", "^" + sub.replace(".", "[.]") + "[^a-zA-Z0-9_.-]"]
    for name in skip_files:
        args += ["-E", skip_pattern(name)]
    return args


def skip_pattern(name):
    """比對整個檔名的 Go 正規表示式。ASCII 英數和 _ 以外的字元都寫成 \\x{碼位}，不用處理哪些字元要跳脫。

    gremlins 比對的是相對於套件目錄、用 / 分隔的路徑，套件目錄底下的檔案就是檔名本身。
    """
    return "^" + "".join(
        c if (c.isascii() and c.isalnum()) or c == "_" else "\\x{%X}" % ord(c) for c in name) + "$"


def unchanged_files(d, files):
    """套件目錄 d 底下（不含子目錄）、不是 _test.go 的 .go 檔中，不在 files 裡的檔名，排序後回傳。

    files 是改到的檔案，相對 repo 根目錄、用 / 分隔。
    """
    changed = {normalize(f) for f in files}
    names = []
    for name in sorted(os.listdir(d)):
        if not name.endswith(".go") or name.endswith("_test.go") or not os.path.isfile(os.path.join(d, name)):
            continue
        if (name if d == "." else d + "/" + name) not in changed:
            names.append(name)
    return names


def check_skipped(result, skip_files):
    """gremlins 的結果裡還有應該略過的檔案，代表 -E 沒有比對到，丟 QualityError，不讓速度問題默默變成看不見。"""
    leaked = sorted({f["file_name"] for f in result.get("files") or []} & set(skip_files))
    if leaked:
        raise QualityError("排除沒改到的檔案沒有生效：" + "、".join(leaked))


class Go(Language):
    SOURCE_GLOBS = ["*.go"]
    DEFAULTS = DEFAULTS

    def unsupported_warnings(self, settings):
        if settings["timeout_seconds"] is not None:
            return ["警告：Go 的量測工具（gremlins）不支援 timeout_seconds，這個設定沒有作用"]
        return []

    def is_test(self, path):
        return path.endswith("_test.go")

    def package_dir(self, path):
        return posixpath.dirname(normalize(path)) or "."

    def run_tests(self, cfg):
        return subprocess.call(["go", "test", "./..."])

    def measure_functions(self, cfg):
        module = _module()
        pkgs = _packages(cfg, module)

        with tempfile.TemporaryDirectory() as tmp:
            profile = os.path.join(tmp, "cover.out")
            r = run(["go", "test", "-coverprofile=" + profile] + [p for p, _ in pkgs])
            print(r.stdout, end="")
            if r.returncode != 0:
                raise QualityError("測試沒有全部通過，請先修好第一關（單元測試）再量 CRAP：\n" + r.stderr)
            r = run(["go", "tool", "cover", "-func=" + profile])
            if r.returncode != 0:
                raise QualityError("go tool cover 執行失敗：\n" + r.stderr)

        # 每行格式：shop/shipping/fee.go:4:	Fee	40.0%，開頭的模組名稱去掉後就是相對路徑
        coverage = {}
        for line in r.stdout.splitlines():
            fields = line.split()
            if len(fields) != 3 or fields[0] == "total:":
                continue
            file, _, lineno = fields[0].rstrip(":").rpartition(":")
            file = file[len(module) + 1:] if file.startswith(module + "/") else file
            coverage[(file, int(lineno))] = float(fields[2].rstrip("%")) / 100

        # 每行格式：14 shop Checkout checkout.go:31:1
        r = run(["go", "run", GOCYCLO, "."])
        if r.returncode != 0:
            raise QualityError("gocyclo 執行失敗：\n" + r.stderr)
        self.tools["gocyclo"] = GOCYCLO.rsplit("@", 1)[1]
        funcs = []
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            file, lineno, _ = parts[-1].rsplit(":", 2)
            file, lineno = normalize(file), int(lineno)
            if self.is_test(file) or is_excluded(file, cfg):
                continue
            funcs.append(Function(
                file=file,
                name=" ".join(parts[2:-1]),
                start=lineno,
                end=_func_end(file, lineno),
                complexity=int(parts[0]),
                coverage=coverage.get((file, lineno), 0.0),
            ))
        return funcs

    def measure_mutants(self, cfg, dirs=None, files=None):
        # 有 files（--base）時，套件裡沒改到的檔案用 -E 排除，不產生改壞的版本；只算改到的行仍由核心過濾。
        # 不用 gremlins 的 --diff：一段 diff 裡有兩處分開的修改時，它只算到第一處
        if dirs is None:
            dirs = [d for _, d in _packages(cfg, _module())]

        settings = self.settings(cfg)
        for w in self.unsupported_warnings(settings):
            print(w, file=sys.stderr, flush=True)
        mutants = []
        for d in dirs:
            if not os.path.isdir(d):  # 整個目錄被刪掉
                continue
            print("抓錯檢查：{} ...".format(d), file=sys.stderr, flush=True)
            skip = unchanged_files(d, files) if files is not None else []
            if skip:
                print("只對改到的檔案產生改壞的版本，略過 {} 個沒改到的檔案".format(len(skip)),
                      file=sys.stderr, flush=True)
            with tempfile.TemporaryDirectory() as tmp:
                out = os.path.join(tmp, "gremlins.json")
                r = run(["go", "run", GREMLINS] + gremlins_args(settings, d, out, _subdirs(d), skip))
                if os.path.exists(out):
                    with open(out, encoding="utf-8") as f:
                        result = json.load(f)
                elif NO_RESULTS in r.stdout + r.stderr:
                    # 套件裡沒有可以改壞的地方（只有測試、常數、型別或 doc.go），或是 --base 時改到的檔案沒有可以
                    # 改壞的地方、其他檔案又都略過了。gremlins 只在成功執行且沒有改壞的版本時印這行，不寫結果檔
                    result = {}
                else:
                    raise QualityError("gremlins 執行失敗（{}）：\n{}{}".format(d, r.stdout, r.stderr))
            check_skipped(result, skip)
            self.tools["gremlins"] = GREMLINS.rsplit("@", 1)[1]

            # 檔名是相對於套件目錄的路徑
            for f in result.get("files") or []:
                file = normalize(f["file_name"] if d == "." else d + "/" + f["file_name"])
                for m in f.get("mutations") or []:
                    lines = source_lines(file)
                    text = lines[m["line"] - 1] if 0 < m["line"] <= len(lines) else ""
                    original, replacement = gremlins_describe(m["type"], text, m.get("column"))
                    mutants.append(Mutant(
                        file=file,
                        line=m["line"],
                        column=m.get("column"),
                        status=m["status"].replace(" ", "_"),
                        mutator=m["type"],
                        original=original,
                        replacement=replacement,
                    ))
        return mutants


LANGUAGE = Go


def _module():
    r = run(["go", "list", "-m"])
    if r.returncode != 0:
        raise QualityError("讀不到模組名稱，請在 go.mod 所在的目錄執行：\n" + r.stderr)
    return r.stdout.strip()


def _packages(cfg, module):
    """回傳 [(import path, 相對目錄)]，排除 exclude 底下的套件。"""
    r = run(["go", "list", "./..."])
    if r.returncode != 0:
        raise QualityError("go list 執行失敗：\n" + r.stderr)
    pkgs = []
    for p in r.stdout.split():
        rel = p[len(module) + 1:] if p.startswith(module + "/") else "."
        if rel == "." or not is_excluded(rel + "/", cfg):
            pkgs.append((p, rel))
    return pkgs


def _subdirs(d):
    """gremlins 掃一個目錄時會連子目錄一起掃，但子目錄的覆蓋率抓不到，全部算成 NOT COVERED，所以要排除。

    回傳要排除的子目錄名稱，gremlins_args 轉成 -E 的樣式。Windows 上路徑用 \\ 分隔，為了不在正規表示式裡
    放反斜線，用「子目錄名稱後面接一個不會出現在檔名裡的字元」來比對。
    """
    return [sub for sub in sorted(os.listdir(d)) if os.path.isdir(os.path.join(d, sub))]


_lines = {}


def _func_end(file, start):
    """找函式結尾的行號。程式碼經過 gofmt，頂層函式的結尾一定是單獨一行、從第一欄開始的 }。"""
    if file not in _lines:
        with open(file, encoding="utf-8", errors="replace") as f:
            _lines[file] = f.read().splitlines()
    lines = _lines[file]
    first = lines[start - 1].rstrip()
    if first.endswith("}") and first.count("{") == first.count("}"):  # 一行寫完的函式
        return start
    for i in range(start, len(lines)):
        if lines[i].rstrip() == "}":
            return i + 1
    return start
