"""工具本身的回歸測試：用範例專案跑一遍，結果要跟 selftest/ 記錄的預期一致。

改了工具的任何程式，打新版本標籤之前都要跑過：

    python selftest.py                 # 全部範例
    python selftest.py go python       # 只跑指定的範例
    python selftest.py --update go     # 確認新的 CRAP 表格是對的之後，用它更新快照

範例專案打包成一個文字檔 selftest/<範例>.sample.txt。這個工具會被掛進各專案 repo 的 tools/quality/，
範例如果是一般的檔案，專案的 Vitest、Jest、tsc、ESLint 會把範例的程式和測試當成專案的一起處理。
要修改範例時，先解開，改完再存回：

    python selftest.py --unpack go 暫存目錄/go
    python selftest.py --pack 暫存目錄/go go

每個範例的流程：
1. 解開到暫存目錄，執行 selftest/<範例>.json 的 setup（例如 npm ci），git init 並 commit 到 main
2. test 要通過；crap（整個專案）的表格要跟 selftest/<範例>.crap.txt 一致
3. 依序執行 scenarios：每個情境先把整個 repo 還原成初始 commit（情境裡做的 commit 也一併丟掉），再照 edits 改檔案，執行指令，檢查結束碼和輸出

每個範例在 git init 之前，先把本工具 git ls-files 列出的檔案複製到範例的 tools/quality/，模擬 submodule 掛載，
所有情境都在這個狀態下跑。selftest.py 一開始會先跑 dev/unit_checks.py（不需要語言工具的純函式測試），沒過就整體失敗。

情境（scenarios）可以用 run + exit + contains 寫單一步驟，也可以用 steps 寫多個步驟。每一步是
{run, exit, contains, in_order, not_contains, equals, json, json_values, no_files}：同一個情境的各步之間不還原；
equals 是整份輸出去掉頭尾空白後要完全等於的文字；
exit 可以是一個數字，也可以是可接受的數字串列（例如 [0, 1]）；in_order 是要依序出現的文字串列；
json 是該步 --json 寫出的檔名（也可以是檔名串列），
讀檔後用 qtools.report_schema.validate 比對，不符就算該步失敗；json_values 是 {"欄位.路徑": 預期值}，
比對 json 檔裡對應欄位的值（路徑用 . 分隔，遇到陣列時，數字是索引，欄位=值 是找第一個符合的元素，
例如 crap.functions.name=Checkout.churn）；no_files 是檔名樣式（fnmatch）的串列，這一步結束後範例專案裡不能有符合的檔案。
run 的第一個元素是 {venv_python} 時，直接執行範例 venv 的 Python，不經過 quality.py。

步驟可以用 "shell": [指令...] 取代 run，直接執行任意指令（不經過殼層），cwd 是範例專案，stdin 給 {}，
環境變數加 CLAUDE_PROJECT_DIR=<範例專案>（QUALITY_BASE 會先清掉，免得外面的設定干擾），
git 身分固定是 selftest <selftest@example.com>（跟 init commit 一致），情境裡的 git commit 不用依賴全域 git 設定，
步驟另外用 "env": {名稱: 值} 加環境變數。指令的每個元素裡，{gate_sh} 換成範本 gate.sh 的絕對路徑，
{bash} 換成 bash：Windows 用 Git for Windows 的 bash.exe（不用 System32 底下 WSL 的 bash），找不到該步就失敗。

範例專案需要的語言工具（Go、.NET SDK、Node、Python）要先裝好。
"""

import argparse
import fnmatch
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE_SH = os.path.join(HERE, "docs", "範本_三道防線", "專案repo範本", ".claude", "hooks", "gate.sh")
CASES = os.path.join(HERE, "selftest")
UNIT_CHECKS = os.path.join(HERE, "dev", "unit_checks.py")
FILE_MARK = "--- file: "  # 打包檔裡每個檔案的開頭
PACK_SKIP = {".git", "node_modules", ".venv", "__pycache__", "bin", "obj", "coverage", "reports", ".stryker-tmp"}
VENV_PYTHON = os.path.join(".venv", "Scripts", "python.exe") if os.name == "nt" else os.path.join(".venv", "bin", "python")


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="用範例專案測試工具本身")
    parser.add_argument("samples", nargs="*", help="要跑的範例，預設全部")
    parser.add_argument("--update", action="store_true", help="把 crap 的輸出寫回快照，不比對")
    parser.add_argument("--keep", action="store_true", help="保留暫存目錄，方便查問題")
    parser.add_argument("--unpack", nargs=2, metavar=("範例", "目錄"), help="把範例解開到目錄，用來修改範例")
    parser.add_argument("--pack", nargs=2, metavar=("目錄", "範例"), help="把目錄打包存回範例")
    args = parser.parse_args()

    if args.unpack:
        unpack(args.unpack[0], args.unpack[1])
        return
    if args.pack:
        pack(args.pack[0], args.pack[1])
        return

    # 純函式的單元測試先跑，不需要語言工具，幾秒內就能知道版本檢查、設定檔驗證、schema 有沒有壞
    print("=== dev/unit_checks.py", flush=True)
    if subprocess.call([sys.executable, UNIT_CHECKS], env=dict(os.environ, PYTHONUTF8="1")) != 0:
        print("\nFAIL：dev/unit_checks.py 沒過")
        sys.exit(1)

    names = args.samples or sorted(f[:-len(".json")] for f in os.listdir(CASES) if f.endswith(".json"))
    failed = []
    for name in names:
        print("=== {}".format(name), flush=True)
        failed += ["{}：{}".format(name, c) for c in run_sample(name, args)]

    print()
    if failed:
        print("FAIL：{} 項沒過".format(len(failed)))
        for f in failed:
            print("  " + f)
        sys.exit(1)
    print("PASS：{} 個範例全部通過".format(len(names)))


def run_sample(name, args):
    with open(os.path.join(CASES, name + ".json"), encoding="utf-8") as fp:
        case = json.load(fp)
    tmp = tempfile.mkdtemp(prefix="qs-")
    proj = os.path.join(tmp, name)
    failed = []
    try:
        error = prepare(name, proj, case.get("setup", []))
        if error:
            return [error]

        failed += check("test", proj, ["test"], 0)

        r = quality(proj, ["crap"])
        table = crap_table(r.stdout)
        snapshot = os.path.join(CASES, name + ".crap.txt")
        if args.update:
            with open(snapshot, "w", encoding="utf-8", newline="\n") as fp:
                fp.write(table)
            print("  已更新 " + os.path.relpath(snapshot, HERE))
        else:
            with open(snapshot, encoding="utf-8") as fp:
                expected = fp.read()
            failed += report("crap 整個專案，表格要跟快照一致", r, table == expected,
                             "預期：\n" + expected)

        init_commit = run(["git", "rev-parse", "HEAD"], proj, check=True).stdout.strip()
        for sc in case["scenarios"]:
            # 還原成初始 commit：情境裡做的 commit 不會留到下一個情境
            run(["git", "reset", "-q", "--hard", init_commit], proj, check=True)
            run(["git", "clean", "-fdq"], proj, check=True)
            for e in sc.get("edits", []):
                path = os.path.join(proj, e["file"])
                if "old" in e:
                    with open(path, encoding="utf-8", newline="") as fp:
                        text = fp.read()
                    if text.count(e["old"]) != 1:
                        failed.append("{}：{} 裡找不到唯一的 {!r}".format(sc["name"], e["file"], e["old"]))
                        break
                    text = text.replace(e["old"], e["new"])
                else:
                    text = e["content"]  # 新增檔案，或整份換掉
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8", newline="") as fp:
                    fp.write(text)
            else:
                # 單一步驟的舊格式，等於只有一步的 steps；各步之間不還原工作目錄
                steps = sc.get("steps") or [sc]
                for i, step in enumerate(steps, 1):
                    title = sc["name"] if len(steps) == 1 else "{}（步驟 {}）".format(sc["name"], i)
                    failed += check(title, proj, step.get("run"), step["exit"], step.get("contains", []),
                                    step.get("not_contains", []), step.get("json"), step.get("json_values"),
                                    step.get("no_files") or (), step.get("shell"), step.get("env"), step.get("in_order", []),
                                    step.get("equals"))
    finally:
        if args.keep:
            print("  暫存目錄：" + proj)
        else:
            shutil.rmtree(tmp, onerror=_force_remove)
    return failed


def prepare(name, proj, setup, unpack_fn=None, mount=True):
    """解開範例、掛上本工具、執行 setup、git init 並 commit 到 main。成功回傳 None，失敗回傳訊息。

    dev/v1_parity.py 也用這個函式準備範例：unpack_fn 換成 v1.0.0 的解包函式，mount 設成 False。
    """
    (unpack_fn or unpack)(name, proj)
    if mount:
        mount_tool(proj)
    for cmd in setup:
        cmd = [sys.executable if c == "{python}" else os.path.join(proj, VENV_PYTHON) if c == "{venv_python}" else c
               for c in cmd]
        r = run(cmd, proj)
        if r.returncode != 0:
            return "setup 失敗：{}\n{}".format(" ".join(cmd), r.stdout[-3000:])
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"],
                ["-c", "user.name=selftest", "-c", "user.email=selftest@example.com", "commit", "-q", "-m", "init"]):
        run(["git"] + cmd, proj, check=True)
    return None


def mount_tool(proj):
    """把本工具複製到 proj/tools/quality，模擬 submodule 掛載。

    用 git ls-files 列檔，所以只有進版控的檔案會被複製；還沒 git add 的新檔案也算（開發中的工具），已刪除但還沒 commit 的不算。
    """
    files = set()
    for args in (["ls-files"], ["ls-files", "--others", "--exclude-standard"]):
        r = run(["git", "-c", "core.quotepath=false"] + args, HERE, check=True)
        files.update(line for line in r.stdout.splitlines() if line.strip())
    for f in sorted(files):
        src = os.path.join(HERE, f)
        if not os.path.isfile(src):
            continue
        dest = os.path.join(proj, "tools", "quality", f)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(src, dest)


def unpack(name, dest):
    """把 selftest/<name>.sample.txt 解開到 dest。"""
    # 不指定 newline：打包檔被 git 換成 CRLF 時，讀進來一樣是 LF
    with open(os.path.join(CASES, name + ".sample.txt"), encoding="utf-8") as fp:
        lines = fp.read().split("\n")
    files, current = {}, None
    for line in lines[1:]:  # 第一行是說明
        if line.startswith(FILE_MARK):
            current = line[len(FILE_MARK):]
            files[current] = []
        elif current is not None:
            files[current].append(line)
    for path, content in files.items():
        if content and content[-1] == "":  # 檔案之間的分隔空行
            content.pop()
        target = os.path.join(dest, path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as fp:
            fp.write("\n".join(content) + "\n" if content else "")


def pack(src, name):
    """把 src 目錄打包成 selftest/<name>.sample.txt。檔案一律用 LF 換行、以換行結尾。"""
    out = ["# 範例專案 {}。不要直接編輯，用 python selftest.py --unpack {} <目錄> 解開，改完用 --pack 存回".format(name, name)]
    for root, dirs, names in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in PACK_SKIP)
        for n in sorted(names):
            path = os.path.join(root, n)
            with open(path, encoding="utf-8", newline="") as fp:
                text = fp.read().replace("\r\n", "\n")
            if any(line.startswith(FILE_MARK) for line in text.split("\n")):
                sys.exit("{} 裡有以 {!r} 開頭的行，沒辦法打包".format(path, FILE_MARK))
            if text and not text.endswith("\n"):
                text += "\n"
            out.append(FILE_MARK + normalize(os.path.relpath(path, src)))
            out.append(text)  # text 以換行結尾，加上 join 的換行，形成檔案之間的分隔空行
    with open(os.path.join(CASES, name + ".sample.txt"), "w", encoding="utf-8", newline="\n") as fp:
        fp.write("\n".join(out))
    print("已存回 selftest/{}.sample.txt".format(name))


def normalize(path):
    return path.replace("\\", "/")


def crap_table(stdout):
    """crap 輸出中，從表頭開始的部分。前面是測試工具自己的輸出，含執行時間，每次都不一樣。"""
    lines = stdout.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.startswith("CRAP ")), len(lines))
    return "".join(lines[start:])


def check(title, proj, cmd, code, contains=(), not_contains=(), json_file=None, json_values=None, no_files=(),
          shell=None, env=None, in_order=(), equals=None):
    if shell is not None:
        r = run_shell(proj, shell, env or {})
    elif cmd and cmd[0] == "{venv_python}":
        r = run([os.path.join(proj, VENV_PYTHON)] + cmd[1:], proj)
    else:
        r = quality(proj, cmd)
    output = r.stdout + r.stderr  # 錯誤訊息（結束碼 2）印在 stderr
    missing = [c for c in contains if c not in output]
    unexpected = [c for c in not_contains if c in output]
    problems = []
    codes = code if isinstance(code, list) else [code]
    if r.returncode not in codes:
        problems.append("結束碼 {}（預期 {}）".format(r.returncode, " 或 ".join(map(str, codes))))
    if missing:
        problems.append("輸出缺少：" + "、".join(missing))
    if unexpected:
        problems.append("輸出不該出現：" + "、".join(unexpected))
    if equals is not None and output.strip() != equals:
        problems.append("輸出是 {!r}（預期 {!r}）".format(output.strip(), equals))
    pos = 0
    for c in in_order:
        found = output.find(c, pos)
        if found < 0:
            problems.append("輸出沒有依序出現：" + "、".join(in_order))
            break
        pos = found + len(c)
    for name in [json_file] if isinstance(json_file, str) else json_file or ():
        problems += _json_problems(os.path.join(proj, name), name, json_values or {})
    problems += _leftover_files(proj, no_files)
    return report(title, r, not problems, "；".join(problems))


def _json_problems(path, name, values):
    """讀 --json 寫出的檔案，用 report_schema 比對格式，再比對 values 指定的欄位值。"""
    from qtools import report_schema
    if not os.path.exists(path):
        return ["沒有寫出 " + name]
    with open(path, encoding="utf-8") as fp:
        data = json.load(fp)
    problems = ["{} 格式不符：{}".format(name, e) for e in report_schema.validate(data)]
    for dotted, expected in values.items():
        actual = data
        for key in dotted.split("."):
            actual = _step_into(actual, key)
        if actual != expected:
            problems.append("{} 的 {} 是 {!r}（預期 {!r}）".format(name, dotted, actual, expected))
    return problems


def _step_into(value, key):
    """json_values 路徑的一步：物件取欄位；陣列用數字取索引，或用 欄位=值 找第一個符合的元素。找不到回傳 None。"""
    if isinstance(value, dict):
        return value.get(key)
    if isinstance(value, list):
        if key.isdigit():
            return value[int(key)] if int(key) < len(value) else None
        field, _, wanted = key.partition("=")
        return next((x for x in value if isinstance(x, dict) and str(x.get(field)) == wanted), None)
    return None


def _leftover_files(proj, patterns):
    """專案裡（不含 .git、node_modules）符合樣式的檔案，用來確認工具沒有留下自己產生的設定檔。"""
    found = []
    for root, dirs, names in os.walk(proj):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules")]
        for n in names:
            if any(fnmatch.fnmatch(n, p) for p in patterns):
                found.append(normalize(os.path.relpath(os.path.join(root, n), proj)))
    return ["專案裡多出不該留下的檔案：" + "、".join(found)] if found else []


def report(title, r, ok, detail):
    print("  {} {}".format("✅" if ok else "❌", title), flush=True)
    if ok:
        return []
    print("     " + detail.replace("\n", "\n     "))
    print("     實際輸出：\n     " + (r.stdout + r.stderr)[-3000:].replace("\n", "\n     "))
    return [title]


def find_bash():
    """找 bash 的路徑，找不到回傳 None。

    Windows 上 PATH 裡的 bash 可能是 System32 底下的 WSL 啟動器，跑起來是另一個 Linux 環境，
    gate.sh 在那裡找不到 Git Bash 的工具。所以先從 git 的安裝目錄找（git --exec-path 在
    <安裝目錄>/mingw64/libexec/git-core，往上三層是安裝目錄，bash.exe 在 bin/ 底下），
    找不到才用 PATH 裡的 bash，而且要略過 System32 和 WindowsApps。
    """
    if os.name != "nt":
        return shutil.which("bash")
    candidates = []
    r = run(["git", "--exec-path"], HERE)
    if r.returncode == 0:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.normpath(r.stdout.strip()))))
        candidates += [os.path.join(root, "bin", "bash.exe"), os.path.join(root, "usr", "bin", "bash.exe")]
    candidates.append(shutil.which("bash"))
    for c in candidates:
        if c and os.path.isfile(c) and not any(
                bad in c.replace("/", "\\").lower() for bad in ("\\windows\\system32\\", "\\windowsapps\\")):
            return c
    return None


def run_shell(proj, cmd, extra_env):
    """執行 shell 步驟：換掉 {gate_sh}、{bash}，cwd 是範例專案，stdin 給 {}。"""
    bash = None
    if any("{bash}" in c for c in cmd):
        bash = find_bash()
        if not bash:
            return subprocess.CompletedProcess(cmd, 2, "", "找不到 Git Bash 的 bash（Windows 上不能用 System32 底下 WSL 的 bash），"
                                                          "請安裝 Git for Windows")
    gate_sh = GATE_SH.replace("\\", "/")
    cmd = [c.replace("{bash}", bash or "").replace("{gate_sh}", gate_sh) for c in cmd]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", CLAUDE_PROJECT_DIR=proj.replace("\\", "/"),
               GIT_AUTHOR_NAME="selftest", GIT_AUTHOR_EMAIL="selftest@example.com",
               GIT_COMMITTER_NAME="selftest", GIT_COMMITTER_EMAIL="selftest@example.com")
    env.pop("QUALITY_BASE", None)
    env.update(extra_env)
    r = subprocess.run(cmd, cwd=proj, env=env, input="{}", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       encoding="utf-8", errors="replace")
    r.stdout = r.stdout.replace("\r\n", "\n")
    r.stderr = r.stderr.replace("\r\n", "\n")
    return r


def quality(proj, cmd):
    # 跑掛在範例裡的那一份，跟各專案用 submodule 的方式一樣
    return run([sys.executable, os.path.join(proj, "tools", "quality", "quality.py")] + cmd, proj)


def run(cmd, cwd, check=False):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")  # 不要在掛載的工具目錄留下 .pyc
    r = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       encoding="utf-8", errors="replace", shell=os.name == "nt" and cmd[0] == "npm")
    if check and r.returncode != 0:
        raise RuntimeError("{} 失敗：\n{}".format(" ".join(cmd), r.stdout + r.stderr))
    r.stdout = r.stdout.replace("\r\n", "\n")
    return r


def _force_remove(func, path, _):
    """Windows 上 .git 和 node_modules 有唯讀檔案，要先取消唯讀才刪得掉。"""
    os.chmod(path, stat.S_IWRITE)
    func(path)


if __name__ == "__main__":
    main()
