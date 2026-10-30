"""Python 的量測轉換。

- 圈複雜度和函式起訖行：Python 內建的 ast 模組，規則見 _complexity
- 覆蓋率：coverage.py，取敘述覆蓋率，再依函式範圍計算
- 變異測試：cosmic-ray（mutmut 需要 fork，在 Windows 上只能透過 WSL 執行，所以不用）

測試框架是 pytest。pytest、coverage、cosmic-ray 要裝在專案的 Python 環境裡：
專案根目錄有 .venv 就用它，否則用執行 quality.py 的 Python，也可以在 .quality.json 用 python.interpreter 指定。
「套件」對應到 .py 檔所在的目錄。
"""

import ast
import json
import os
import posixpath
import shutil
import subprocess
import sys
import tempfile

from qtools.langs.base import Language, check_version
from qtools.model import Function, KILLED, LIVED, NOT_COVERED, NOT_VIABLE, SKIPPED, Mutant
from qtools.proc import TOOL_ROOT, QualityError, is_excluded, list_files, normalize, project_path, run, tail

SKIP_FILTER = os.path.join(TOOL_ROOT, "python", "cr_skip_uncovered.py")
NOT_COVERED_MARK = "quality:not-covered"  # 要跟 cr_skip_uncovered.py 一致
PYTEST = ["-m", "pytest", "-q", "-p", "no:cacheprovider"]
DEFAULT_TIMEOUT = 30  # cosmic-ray 每個突變體的時限（秒）

# 各 repo 自己安裝的 cosmic-ray，這個版本跑過 selftest，分數對得上
COSMIC_RAY_VERIFIED = ["8.7.0"]


class Python(Language):
    SOURCE_GLOBS = ["*.py"]

    def is_test(self, path):
        path = normalize(path)
        name = posixpath.basename(path)
        return (name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"
                or any(part in ("tests", "test") for part in path.split("/")[:-1]))

    def package_dir(self, path):
        return posixpath.dirname(normalize(path)) or "."

    def run_tests(self, cfg):
        return subprocess.call([_python(cfg)] + PYTEST, env=_env())

    def measure_functions(self, cfg):
        funcs = []
        for file in self._source_files(cfg):
            with open(file, encoding="utf-8") as fp:
                tree = ast.parse(fp.read(), filename=file)
            for node, name in _functions(tree):
                f = Function(file=file, name=name, start=node.lineno, end=node.end_lineno,
                             complexity=_complexity(node), coverage=0.0)
                # def 那一行在載入模組時就會執行，不能算成函式有被測試，所以覆蓋率從本體第一行算起
                funcs.append((f, node.body[0].lineno))

        executed, statements = _coverage(cfg)
        for f, body in funcs:
            lines = [n for n in statements.get(f.file, ()) if body <= n <= f.end]
            f.coverage = sum(1 for n in lines if n in executed[f.file]) / len(lines) if lines else 0.0
        return [f for f, _ in funcs]

    def measure_mutants(self, cfg, dirs=None, files=None):
        python = _python(cfg)
        if files is None:
            files = self._source_files(cfg)
        if dirs is not None:
            files = [f for f in files if self.package_dir(f) in dirs]
        files = [f for f in files if not self.is_test(f)]
        if not files:
            return []

        self.tools["cosmic-ray"] = _check_cosmic_ray(python)
        executed, _ = _coverage(cfg)

        # cosmic-ray 會直接改原始碼檔案再改回來，中途被打斷就會留下改壞的程式，所以複製一份到暫存目錄再跑
        with tempfile.TemporaryDirectory() as tmp:
            for f in list_files(["*"]):
                dest = os.path.join(tmp, f)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(f, dest)

            config = os.path.join(tmp, "cosmic-ray.toml")
            with open(config, "w", encoding="utf-8") as fp:
                fp.write("[cosmic-ray]\n")
                fp.write("module-path = [{}]\n".format(", ".join(_toml(f) for f in files)))
                fp.write("timeout = {}\n".format(float(cfg["mutation"]["timeout_seconds"] or DEFAULT_TIMEOUT)))
                fp.write("excluded-modules = []\n")
                # TOML 單引號字串不處理跳脫字元，Windows 路徑可以直接放
                fp.write("test-command = '\"{}\" {} -x'\n".format(python, " ".join(PYTEST)))
                fp.write('\n[cosmic-ray.distributor]\nname = "local"\n')
            executed_json = os.path.join(tmp, "executed.json")
            with open(executed_json, "w", encoding="utf-8") as fp:
                json.dump({k: sorted(v) for k, v in executed.items()}, fp)

            session = os.path.join(tmp, "session.sqlite")
            env = _env(pythonpath=[tmp, os.path.join(tmp, "src")])
            print("抓錯檢查：{} 個檔案 ...".format(len(files)), file=sys.stderr, flush=True)
            for args in (["-m", "cosmic_ray.cli", "init", config, session],
                         [SKIP_FILTER, session, executed_json],
                         ["-m", "cosmic_ray.cli", "exec", config, session]):
                r = run([python] + args, cwd=tmp, env=env)
                if r.returncode != 0:
                    raise QualityError("cosmic-ray 執行失敗（請確認專案環境有安裝 cosmic-ray）：\n" + tail(r.stdout + r.stderr))
            r = run([python, "-m", "cosmic_ray.cli", "dump", session], cwd=tmp, env=env)

        mutants = []
        for line in r.stdout.splitlines():
            item, result = json.loads(line)
            m = item["mutations"][0]
            mutants.append(Mutant(
                file=normalize(m["module_path"]),
                line=m["start_pos"][0],
                column=m["start_pos"][1] + 1,  # cosmic-ray 的欄位從 0 起算，這裡統一成從 1 起算
                status=_status(result),
                mutator=m["operator_name"].replace("core/", ""),
            ))
        return mutants

    def _source_files(self, cfg):
        return [f for f in list_files(self.SOURCE_GLOBS) if not self.is_test(f) and not is_excluded(f, cfg)]


LANGUAGE = Python


def check_cosmic_ray(version):
    check_version("cosmic-ray", version, COSMIC_RAY_VERIFIED)


def _check_cosmic_ray(python):
    """讀專案環境裡 cosmic-ray 的實際版本，不是驗證過的版本就丟 QualityError。回傳版本。"""
    r = run([python, "-c", "import importlib.metadata as m; print(m.version('cosmic-ray'))"], env=_env())
    if r.returncode != 0:
        raise QualityError("專案的 Python 環境（{}）沒有安裝 cosmic-ray，請先安裝驗證過的版本：pip install cosmic-ray=={}"
                           .format(python, COSMIC_RAY_VERIFIED[-1]))
    version = r.stdout.strip()
    check_cosmic_ray(version)
    return version


def _status(result):
    if not result:
        return SKIPPED
    if result.get("worker_outcome") == "skipped":
        return NOT_COVERED if result.get("output") == NOT_COVERED_MARK else SKIPPED
    if result.get("worker_outcome") != "normal":
        return NOT_VIABLE
    return {"killed": KILLED, "survived": LIVED}.get(result.get("test_outcome"), NOT_VIABLE)


def _functions(tree):
    """最外層的函式和 class 的方法（含巢狀 class）。函式裡面的函式和 lambda 算進外層。"""
    def walk(nodes, prefix):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield node, prefix + node.name
            elif isinstance(node, ast.ClassDef):
                yield from walk(node.body, prefix + node.name + ".")
    return walk(tree.body, "")


def _complexity(func):
    """圈複雜度 = 1 + 判斷點數量，規則對齊 Go 的 gocyclo，再補上 Python 才有的語法：

    +1：if（含 elif）、for、async for、while、except、條件運算式（a if c else b）、
        生成式裡的每個 for 和 if、match 中每個不是 _ 的 case
    and、or：一串 a and b and c 有兩個運算子，加 2
    不加：else、try、finally、with、return、break、continue
    """
    n = 1
    for node in ast.walk(func):
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp)):
            n += 1
        elif isinstance(node, ast.comprehension):
            n += 1 + len(node.ifs)
        elif isinstance(node, ast.BoolOp):
            n += len(node.values) - 1
        elif hasattr(ast, "match_case") and isinstance(node, ast.match_case):
            p = node.pattern
            if not (isinstance(p, ast.MatchAs) and p.pattern is None and node.guard is None):
                n += 1
    return n


def _coverage(cfg):
    """執行測試並收集覆蓋率，回傳（{檔案: 執行到的行}, {檔案: 所有敘述的行}）。"""
    python = _python(cfg)
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, ".coverage")
        report = os.path.join(tmp, "coverage.json")
        r = run([python, "-m", "coverage", "run", "--data-file=" + data] + PYTEST, env=_env())
        if r.returncode != 0:
            raise QualityError("測試沒有全部通過，或專案環境沒有安裝 pytest、coverage，"
                               "請先修好第一關（單元測試）再量 CRAP：\n" + tail(r.stdout + r.stderr))
        r = run([python, "-m", "coverage", "json", "--data-file=" + data, "-o", report], env=_env())
        if r.returncode != 0:
            raise QualityError("coverage json 執行失敗：\n" + r.stderr)
        with open(report, encoding="utf-8") as fp:
            files = json.load(fp)["files"]

    executed, statements = {}, {}
    for path, info in files.items():
        file = project_path(path)
        executed[file] = set(info["executed_lines"])
        statements[file] = set(info["executed_lines"]) | set(info["missing_lines"])
    return _Missing(executed), statements


class _Missing(dict):
    """沒出現在覆蓋率報告裡的檔案，等於一行都沒執行。"""

    def __missing__(self, key):
        return set()


def _python(cfg):
    if cfg["python"]["interpreter"]:
        return cfg["python"]["interpreter"]
    for venv in (os.path.join(".venv", "Scripts", "python.exe"), os.path.join(".venv", "bin", "python")):
        if os.path.exists(venv):
            return os.path.abspath(venv)
    return sys.executable


def _env(pythonpath=None):
    env = dict(os.environ)
    # 測試輸出有中文時，Windows 預設用 Big5，cosmic-ray 用 UTF-8 讀會出錯，把被殺死的突變體誤判成無效
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if pythonpath:
        # 讓測試匯入暫存目錄裡被突變的程式，而不是原本的（例如用 pip install -e 安裝的）
        env["PYTHONPATH"] = os.pathsep.join(pythonpath + [env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    return env


def _toml(s):
    return "'" + s + "'"
