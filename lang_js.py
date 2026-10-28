"""JavaScript / TypeScript 的量測轉換。

- 圈複雜度和函式起訖行：js/complexity.cjs（用 TypeScript 的解析器，規則見檔案開頭）
- 覆蓋率：Vitest（@vitest/coverage-v8）或 Jest 內建，取敘述覆蓋率，再依函式範圍計算
- 變異測試：StrykerJS

測試框架依 package.json 的相依套件自動判斷，也可以在 .quality.json 用 js_test_runner 指定 vitest 或 jest。
「套件」對應到 package.json 所在的目錄；現況報告的變異測試表則依資料夾分組。
"""

import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile

from common import QualityError, is_excluded, list_files, normalize, project_path, run, tools_dir

SOURCE_GLOBS = ["*.js", "*.jsx", "*.mjs", "*.cjs", "*.ts", "*.tsx", "*.mts", "*.cts"]
TYPESCRIPT_VERSION = "5.9.3"  # 只用來解析原始碼。TypeScript 7 改用 Go 重寫，原本的 JavaScript API 不一定還在
COMPLEXITY_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js", "complexity.cjs")

STATUS = {
    "Killed": "KILLED", "Timeout": "TIMED_OUT", "Survived": "LIVED", "NoCoverage": "NOT_COVERED",
    "CompileError": "NOT_VIABLE", "RuntimeError": "NOT_VIABLE", "Ignored": "SKIPPED", "Pending": "SKIPPED",
}

_TEST = re.compile(r"(\.(test|spec)\.[cm]?[jt]sx?$)|(^|/)__tests__/")
_NOT_SOURCE = re.compile(r"(\.d\.[cm]?ts$)|((^|/)[^/]*\.config\.[cm]?[jt]s$)|((^|/)stryker\.conf\.[cm]?[jt]s(on)?$)")


def is_test(path):
    return _TEST.search(normalize(path)) is not None


def package_dir(path):
    """往上找最近一個有 package.json 的目錄。"""
    d = posixpath.dirname(normalize(path))
    while True:
        if os.path.exists(os.path.join(d or ".", "package.json")):
            return d or "."
        if not d:
            return "."
        d = posixpath.dirname(d)


def report_group(path):
    """現況報告依資料夾分組，比依 package.json 分組細。"""
    return posixpath.dirname(normalize(path)) or "."


def run_tests(cfg):
    code = 0
    for d, runner in _packages(cfg).items():
        args = ["vitest", "run"] if runner == "vitest" else ["jest"]
        code |= subprocess.call(_npx(args), cwd=d)
    return code


def measure_functions(cfg):
    files = _source_files(cfg)
    if not files:
        return []
    r = subprocess.run(["node", COMPLEXITY_JS, _typescript()], input="\n".join(files),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise QualityError("complexity.cjs 執行失敗：\n" + r.stderr)
    funcs = json.loads(r.stdout)

    statements = _statement_hits(cfg)
    for f in funcs:
        f["file"] = normalize(f["file"])
        # 只算函式起點之後的敘述。函式前面同一行的宣告（const f = ...）、以及 Jest 記在函式起點、
        # 代表「建立這個箭頭函式」的敘述，都在載入模組時就會執行，不能算成函式有被測試
        begin = (f["start"], f.pop("startColumn"))
        hits = [h for line, col, h in statements.get(f["file"], []) if begin < (line, col) and line <= f["end"]]
        f["coverage"] = sum(1 for h in hits if h > 0) / len(hits) if hits else 0.0
    return funcs


def measure_mutants(cfg, dirs=None, files=None):
    packages = _packages(cfg)
    if dirs is None:
        dirs = list(packages)
    sources = files if files is not None else _source_files(cfg)

    mutants = []
    for d in sorted(dirs):
        runner = packages.get(d)
        mutate = [normalize(posixpath.relpath(f, d)) for f in sources if package_dir(f) == d]
        if not runner or not mutate:
            continue
        stryker = _stryker_bin(d, runner)

        print("變異測試：{} ...".format(d), file=sys.stderr, flush=True)
        with tempfile.TemporaryDirectory() as tmp:
            report = os.path.join(tmp, "mutation.json")
            config = os.path.join(tmp, "stryker.config.json")
            with open(config, "w", encoding="utf-8") as fp:
                json.dump({
                    "testRunner": runner,
                    "reporters": ["json"],
                    "jsonReporter": {"fileName": report},
                    "mutate": mutate,
                    "coverageAnalysis": "perTest",
                }, fp)
            r = run(["node", stryker, "run", config], cwd=d)
            if not os.path.exists(report):
                raise QualityError("StrykerJS 執行失敗（{}）：\n{}".format(d, _tail(r.stdout + r.stderr)))
            with open(report, encoding="utf-8") as fp:
                result = json.load(fp)

        for path, info in result["files"].items():
            file = project_path(path, d)
            for m in info["mutants"]:
                mutants.append({
                    "file": file,
                    "line": m["location"]["start"]["line"],
                    "status": STATUS.get(m["status"], "SKIPPED"),
                    "mutator": m["mutatorName"],
                })
    return mutants


def _source_files(cfg):
    return [f for f in list_files(SOURCE_GLOBS)
            if not is_test(f) and not is_excluded(f, cfg) and not _NOT_SOURCE.search(f)]


def _packages(cfg):
    """回傳 {package.json 所在目錄: "vitest" 或 "jest"}，只包含有測試框架的套件。"""
    packages = {}
    for f in list_files(["*package.json"]):  # git 的樣式裡 * 也比對 /，所以子目錄的 package.json 也找得到
        d = posixpath.dirname(f) or "."
        if posixpath.basename(f) != "package.json" or is_excluded(f, cfg):
            continue
        with open(f, encoding="utf-8") as fp:
            pkg = json.load(fp)
        deps = dict(pkg.get("dependencies") or {}, **(pkg.get("devDependencies") or {}))
        runner = cfg.get("js_test_runner") or ("vitest" if "vitest" in deps else "jest" if "jest" in deps else None)
        if runner:
            packages[d] = runner
    if not packages:
        raise QualityError("找不到使用 Vitest 或 Jest 的 package.json")
    return packages


def _statement_hits(cfg):
    """執行測試並收集覆蓋率，回傳 {檔案: [(敘述的起始行, 起始欄位, 執行次數), ...]}。"""
    hits = {}
    for d, runner in _packages(cfg).items():
        with tempfile.TemporaryDirectory() as tmp:
            if runner == "vitest":
                args = ["vitest", "run", "--coverage.enabled=true", "--coverage.provider=v8",
                        "--coverage.reporter=json", "--coverage.reportsDirectory=" + tmp]
            else:
                args = ["jest", "--coverage", "--coverageReporters=json", "--coverageDirectory=" + tmp]
            r = run(_npx(args), cwd=d)
            if r.returncode != 0:
                raise QualityError("測試沒有全部通過，或覆蓋率套件沒有安裝（Vitest 要裝 @vitest/coverage-v8），"
                                   "請先修好第一重約束（單元測試）再量 CRAP（{}）：\n{}".format(d, _tail(r.stdout + r.stderr)))
            with open(os.path.join(tmp, "coverage-final.json"), encoding="utf-8") as fp:
                data = json.load(fp)
        for path, info in data.items():
            file = project_path(path, d)
            hits[file] = [(loc["start"]["line"], loc["start"]["column"] or 0, info["s"][sid])
                          for sid, loc in info["statementMap"].items()]
    return hits


def _npx(args):
    npx = shutil.which("npx")
    if not npx:
        raise QualityError("找不到 npx，請確認已安裝 Node.js")
    return [npx, "--no", "--"] + args  # --no：沒裝就報錯，不要自動從網路下載


def _stryker_bin(d, runner):
    """找專案裡安裝的 StrykerJS，並檢查跟測試框架的版本是否相容。"""
    core = _installed(d, "@stryker-mutator/core")
    plugin = _installed(d, "@stryker-mutator/{}-runner".format(runner))
    if not core or not plugin:
        raise QualityError(
            "{} 沒有安裝 StrykerJS，請在該目錄執行：\n"
            "  npm install -D @stryker-mutator/core@10.0.0 @stryker-mutator/{}-runner@10.0.0".format(d, runner))
    if runner == "vitest":
        vitest = _installed(d, "vitest")
        if vitest and _major(vitest["version"]) >= 5 and _version(core["version"]) < (10, 1, 1):
            raise QualityError(
                "Vitest {} 要搭配 StrykerJS 10.1.1 以上（目前是 {}）。"
                "版本不合時，所有突變體都會被判成存活，結果不可信。".format(vitest["version"], core["version"]))
    return os.path.join(core["_dir"], core["bin"]["stryker"] if isinstance(core.get("bin"), dict) else "bin/stryker.js")


def _installed(d, name):
    """往上找 node_modules/<name>/package.json（monorepo 的套件可能裝在上層），回傳內容。"""
    d = os.path.abspath(d)
    while True:
        path = os.path.join(d, "node_modules", *name.split("/"), "package.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fp:
                pkg = json.load(fp)
            pkg["_dir"] = os.path.dirname(path)
            return pkg
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _version(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def _major(v):
    return _version(v)[0]


def _typescript():
    """第一次使用時安裝 TypeScript 解析器到工具快取目錄。"""
    prefix = os.path.join(tools_dir(), "typescript-" + TYPESCRIPT_VERSION)
    path = os.path.join(prefix, "node_modules", "typescript")
    if not os.path.exists(os.path.join(path, "package.json")):
        print("安裝 TypeScript {}（只有第一次）...".format(TYPESCRIPT_VERSION), file=sys.stderr, flush=True)
        npm = shutil.which("npm")
        if not npm:
            raise QualityError("找不到 npm，請確認已安裝 Node.js")
        r = run([npm, "install", "--prefix", prefix, "typescript@" + TYPESCRIPT_VERSION, "--no-audit", "--no-fund"])
        if r.returncode != 0:
            raise QualityError("TypeScript 安裝失敗：\n" + r.stdout + r.stderr)
    return path


def _tail(text, n=40):
    return "\n".join(text.rstrip().splitlines()[-n:])
