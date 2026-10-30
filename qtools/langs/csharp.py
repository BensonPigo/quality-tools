"""C# / .NET 的量測轉換。

- 圈複雜度和函式起訖行：qtools/helpers/dotnet/CsMetrics（用 Roslyn 解析原始碼，規則見 Program.cs）
- 覆蓋率：coverlet（dotnet test --collect:"XPlat Code Coverage"），只取每一行有沒有執行，再依函式範圍計算
- 抓錯檢查：Stryker.NET

coverlet 報告裡也有複雜度，但那是用編譯後的 IL 算的，數字大約是原始碼圈複雜度的兩倍，不能拿來跟門檻 12 比，所以不用。
「套件」對應到 .csproj 所在的目錄。
"""

import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from qtools.langs.base import DEFAULTS as BASE_DEFAULTS
from qtools.langs.base import Language
from qtools.model import Function, LIVED, KILLED, NOT_COVERED, NOT_VIABLE, SKIPPED, TIMED_OUT, Mutant
from qtools.mutation import location_text
from qtools.proc import (TOOL_ROOT, QualityError, is_excluded, list_files, normalize, project_path, run, tail,
                         tools_dir)

STRYKER_VERSION = "5.0.0"
CSMETRICS_SRC = os.path.join(TOOL_ROOT, "qtools", "helpers", "dotnet", "CsMetrics")

DEFAULTS = dict(BASE_DEFAULTS)  # 不排除任何改法，逾時和並行用 Stryker.NET 自己的預設

# Stryker 的狀態對應到共用格式
STATUS = {
    "Killed": KILLED, "Timeout": TIMED_OUT, "Survived": LIVED, "NoCoverage": NOT_COVERED,
    "CompileError": NOT_VIABLE, "RuntimeError": NOT_VIABLE, "Ignored": SKIPPED, "Pending": SKIPPED,
}


class CSharp(Language):
    SOURCE_GLOBS = ["*.cs"]
    DEFAULTS = DEFAULTS

    def is_test(self, path):
        project = _projects().get(self.package_dir(path))
        return bool(project and project["test"])

    def package_dir(self, path):
        """往上找最近一個有 .csproj 的目錄。"""
        projects = _projects()
        d = os.path.dirname(normalize(path))
        while True:
            if (d or ".") in projects:
                return d or "."
            if not d:
                return "."
            d = os.path.dirname(d)

    def run_tests(self, cfg):
        return subprocess.call(["dotnet", "test"] + _target(cfg))

    def measure_functions(self, cfg):
        files = [f for f in list_files(self.SOURCE_GLOBS)
                 if not self.is_test(f) and not is_excluded(f, cfg) and not _in_build_output(f)]
        if not files:
            return []

        r = subprocess.run(_csmetrics(), input="\n".join(files), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise QualityError("CsMetrics 執行失敗：\n" + r.stderr)
        funcs = [Function(file=normalize(f["file"]), name=f["name"], start=f["start"], end=f["end"],
                          complexity=f["complexity"], coverage=0.0) for f in json.loads(r.stdout)]

        hits = _line_hits(cfg)
        for f in funcs:
            lines = [h for n, h in hits.get(f.file, {}).items() if f.start <= n <= f.end]
            f.coverage = sum(1 for h in lines if h > 0) / len(lines) if lines else 0.0
        return funcs

    def measure_mutants(self, cfg, dirs=None, files=None):
        projects = _projects()
        if dirs is None:
            dirs = [d for d, p in projects.items() if not p["test"] and not is_excluded(d + "/", cfg)]

        settings = self.settings(cfg)
        mutants = []
        for d in sorted(dirs):
            project = projects.get(d)
            if not project or project["test"]:
                continue
            tests = [p["file"] for p in projects.values() if p["test"] and project["file"].lower() in p["refs"]]
            if not tests:
                print("抓錯檢查：{} 沒有測試專案參照它，略過".format(d), file=sys.stderr, flush=True)
                continue

            print("抓錯檢查：{} ...".format(d), file=sys.stderr, flush=True)
            # 設定檔和報告都放在暫存目錄，離開 with 就整個刪掉，不會留在專案裡
            with tempfile.TemporaryDirectory() as tmp:
                config_file = None
                if settings["timeout_seconds"] is not None:
                    config_file = os.path.join(tmp, "stryker-config.json")
                    with open(config_file, "w", encoding="utf-8") as fp:
                        json.dump(stryker_config(settings), fp)
                args = stryker_args(settings, os.path.basename(project["file"]), tmp, config_file)
                for t in tests:
                    args += ["--test-project", os.path.relpath(t, d)]
                for f in files or []:
                    if self.package_dir(f) == d:
                        args += ["--mutate", normalize(os.path.relpath(f, d))]
                r = run([_stryker()] + args, cwd=d)
                report = os.path.join(tmp, "reports", "mutation-report.json")
                if not os.path.exists(report):
                    raise QualityError("Stryker 執行失敗（{}）：\n{}".format(d, tail(r.stdout + r.stderr)))
                with open(report, encoding="utf-8") as fp:
                    result = json.load(fp)
            self.tools["stryker-net"] = STRYKER_VERSION

            for path, info in result["files"].items():
                file = project_path(path)
                for m in info["mutants"]:
                    start = m["location"]["start"]
                    mutants.append(Mutant(
                        file=file,
                        line=start["line"],
                        column=start.get("column"),
                        status=STATUS.get(m["status"], SKIPPED),
                        mutator=m["mutatorName"],
                        original=location_text(file, m["location"]),
                        replacement=m.get("replacement"),
                    ))
        return mutants


LANGUAGE = CSharp


def stryker_config(settings):
    """Stryker.NET 設定檔的內容，只放命令列沒有的選項。

    additional-timeout 單位是毫秒，加在每個改壞版本「依初始測試時間算出的時限」之外。鍵名和最外層的
    "stryker-config" 物件來自 Stryker.NET 5.0.0：dotnet-stryker.exe 的 Stryker.Configuration.dll 有
    AdditionalTimeoutInput，Stryker.CLI.dll 要求設定檔「must contain a single "stryker-config" root object」；
    --help 沒有這個選項，所以只能走設定檔。用 -V debug 實測過，設定檔裡的值會出現在 "AdditionalTimeout"。
    """
    return {"stryker-config": {"additional-timeout": int(round(settings["timeout_seconds"] * 1000))}}


def stryker_args(settings, project_file, output_dir, config_file=None):
    """dotnet-stryker 的命令列參數（不含執行檔，--test-project 和 --mutate 由呼叫端加）。

    --config-file 的說明寫「相對於目前工作目錄」，但 Windows 上暫存目錄和專案可能在不同磁碟，算不出相對路徑，
    所以傳絕對路徑；5.0.0 在 Windows 上實測絕對路徑可用。
    """
    args = ["--project", project_file, "--reporter", "json", "--output", output_dir, "--skip-version-check"]
    if config_file:
        args += ["--config-file", config_file]
    if settings["workers"] is not None:
        args += ["--concurrency", str(settings["workers"])]
    return args


def _target(cfg):
    """dotnet test 的對象。根目錄有多個 .sln 時，要在 .quality.json 設定 csharp.solution。"""
    return [cfg["csharp"]["solution"]] if cfg["csharp"]["solution"] else []


def _line_hits(cfg):
    """執行測試並收集覆蓋率，回傳 {檔案: {行號: 執行次數}}，只包含可以執行的行。"""
    with tempfile.TemporaryDirectory() as tmp:
        r = run(["dotnet", "test"] + _target(cfg) + ["--collect:XPlat Code Coverage", "--results-directory", tmp])
        if r.returncode != 0:
            raise QualityError("測試沒有全部通過，請先修好第一關（單元測試）再量 CRAP：\n" + tail(r.stdout + r.stderr))

        hits = {}
        for report in glob.glob(os.path.join(tmp, "**", "*.cobertura.xml"), recursive=True):
            root = ET.parse(report).getroot()
            sources = [s.text or "" for s in root.iter("source")]
            for cls in root.iter("class"):
                path = _resolve(sources, cls.get("filename"))
                if path is None:
                    continue
                file_hits = hits.setdefault(path, {})
                lines = cls.find("lines")
                for line in lines if lines is not None else []:
                    n, h = int(line.get("number")), int(line.get("hits"))
                    file_hits[n] = max(file_hits.get(n, 0), h)
        return hits


def _resolve(sources, filename):
    """cobertura 的檔名是相對於某個 source 目錄，找出實際存在的那個，轉成相對於專案根目錄的路徑。"""
    for s in sources or [""]:
        path = os.path.join(s, filename)
        if os.path.exists(path):
            return project_path(path)
    return None


_project_cache = None


def _projects():
    """回傳 {專案目錄: {file, test, refs}}。refs 是它參照的專案（.csproj 路徑，小寫）。"""
    global _project_cache
    if _project_cache is None:
        _project_cache = {}
        for root, dirs, names in os.walk("."):
            dirs[:] = [d for d in dirs if d not in ("bin", "obj", ".git", "node_modules")]
            for name in names:
                if not name.endswith(".csproj"):
                    continue
                file = normalize(os.path.join(root, name))
                with open(file, encoding="utf-8-sig", errors="replace") as fp:
                    text = fp.read()
                refs = set()
                for inc in re.findall(r'<ProjectReference\s+Include="([^"]+)"', text):
                    ref = os.path.normpath(os.path.join(os.path.dirname(file), inc.replace("\\", "/")))
                    refs.add(normalize(os.path.relpath(ref)).lower())
                _project_cache[normalize(os.path.dirname(file)) or "."] = {
                    "file": file,
                    "test": "Microsoft.NET.Test.Sdk" in text or re.search(r"<IsTestProject>\s*true", text, re.I) is not None,
                    "refs": refs,
                }
    return _project_cache


def _in_build_output(path):
    return any(part in ("bin", "obj") for part in normalize(path).split("/"))


def _csmetrics():
    """第一次使用時建置 CsMetrics，放在工具快取目錄。原始碼改了會重新建置。"""
    digest = hashlib.sha256()
    for name in sorted(os.listdir(CSMETRICS_SRC)):
        if name.endswith((".cs", ".csproj")):
            with open(os.path.join(CSMETRICS_SRC, name), "rb") as fp:
                digest.update(name.encode() + fp.read())
    out = os.path.join(tools_dir(), "csmetrics-" + digest.hexdigest()[:12])
    dll = os.path.join(out, "CsMetrics.dll")
    if not os.path.exists(dll):
        print("建置 CsMetrics（只有第一次）...", file=sys.stderr, flush=True)
        src = out + "-src"
        shutil.rmtree(src, ignore_errors=True)
        shutil.copytree(CSMETRICS_SRC, src, ignore=shutil.ignore_patterns("bin", "obj"))
        r = run(["dotnet", "build", "-c", "Release", "-o", out], cwd=src)
        if r.returncode != 0:
            raise QualityError("CsMetrics 建置失敗：\n" + tail(r.stdout + r.stderr))
    return ["dotnet", dll]


def _stryker():
    """第一次使用時安裝 Stryker.NET 到工具快取目錄。"""
    path = os.path.join(tools_dir(), "stryker-" + STRYKER_VERSION)
    exe = os.path.join(path, "dotnet-stryker.exe" if os.name == "nt" else "dotnet-stryker")
    if not os.path.exists(exe):
        print("安裝 Stryker.NET {}（只有第一次）...".format(STRYKER_VERSION), file=sys.stderr, flush=True)
        r = run(["dotnet", "tool", "install", "dotnet-stryker", "--version", STRYKER_VERSION, "--tool-path", path])
        if r.returncode != 0:
            raise QualityError("Stryker.NET 安裝失敗：\n" + r.stdout + r.stderr)
    return exe
