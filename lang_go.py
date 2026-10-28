"""Go 的量測轉換：覆蓋率用 go test -cover，圈複雜度用 gocyclo，變異測試用 gremlins。"""

import json
import os
import posixpath
import subprocess
import sys
import tempfile

from common import QualityError, is_excluded, normalize, run

SOURCE_GLOBS = ["*.go"]
GOCYCLO = "github.com/fzipp/gocyclo/cmd/gocyclo@v0.6.0"
GREMLINS = "github.com/go-gremlins/gremlins/cmd/gremlins@v0.6.0"


def is_test(path):
    return path.endswith("_test.go")


def package_dir(path):
    return posixpath.dirname(normalize(path)) or "."


def run_tests(cfg):
    return subprocess.call(["go", "test", "./..."])


def measure_functions(cfg):
    module = _module()
    pkgs = _packages(cfg, module)

    with tempfile.TemporaryDirectory() as tmp:
        profile = os.path.join(tmp, "cover.out")
        r = run(["go", "test", "-coverprofile=" + profile] + [p for p, _ in pkgs])
        print(r.stdout, end="")
        if r.returncode != 0:
            raise QualityError("測試沒有全部通過，請先修好第一重約束（單元測試）再量 CRAP：\n" + r.stderr)
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
    funcs = []
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        file, lineno, _ = parts[-1].rsplit(":", 2)
        file, lineno = normalize(file), int(lineno)
        if is_test(file) or is_excluded(file, cfg):
            continue
        funcs.append({
            "file": file,
            "name": " ".join(parts[2:-1]),
            "start": lineno,
            "end": _func_end(file, lineno),
            "complexity": int(parts[0]),
            "coverage": coverage.get((file, lineno), 0.0),
        })
    return funcs


def measure_mutants(cfg, dirs=None, files=None):
    # files 用不到：gremlins 沒有可靠的方式只突變指定檔案，整個套件跑完後由 quality.py 過濾
    if dirs is None:
        dirs = [d for _, d in _packages(cfg, _module())]

    mutants = []
    for d in dirs:
        if not os.path.isdir(d):  # 整個目錄被刪掉
            continue
        print("變異測試：{} ...".format(d), file=sys.stderr, flush=True)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "gremlins.json")
            r = run(["go", "run", GREMLINS, "unleash", "./" + d,
                     "--timeout-coefficient", "30",  # 測試很快時，gremlins 估的時限太短，會誤判成 TIMED OUT
                     "--invert-logical",             # 預設關閉的 && ↔ || 互換
                     "-o", out] + _exclude_subdirs(d))
            if not os.path.exists(out):
                raise QualityError("gremlins 執行失敗（{}）：\n{}{}".format(d, r.stdout, r.stderr))
            with open(out, encoding="utf-8") as f:
                result = json.load(f)

        # 檔名是相對於套件目錄的路徑
        for f in result.get("files") or []:
            file = normalize(f["file_name"] if d == "." else d + "/" + f["file_name"])
            for m in f.get("mutations") or []:
                mutants.append({
                    "file": file,
                    "line": m["line"],
                    "status": m["status"].replace(" ", "_"),
                    "mutator": m["type"],
                })
    return mutants


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


def _exclude_subdirs(d):
    """gremlins 掃一個目錄時會連子目錄一起掃，但子目錄的覆蓋率抓不到，全部算成 NOT COVERED，所以要排除。

    Windows 上路徑用 \\ 分隔，為了不在正規表示式裡放反斜線，用「子目錄名稱後面接一個不會出現在檔名裡的字元」來比對。
    """
    args = []
    for sub in sorted(os.listdir(d)):
        if os.path.isdir(os.path.join(d, sub)):
            args += ["-E", "^" + sub.replace(".", "[.]") + "[^a-zA-Z0-9_.-]"]
    return args


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
