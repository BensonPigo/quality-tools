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
3. 依序執行 scenarios：每個情境先把工作目錄還原，再照 edits 改檔案，執行指令，檢查結束碼和輸出

範例專案需要的語言工具（Go、.NET SDK、Node、Python）要先裝好。
"""

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
QUALITY = os.path.join(HERE, "quality.py")
CASES = os.path.join(HERE, "selftest")
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
        unpack(name, proj)
        for cmd in case.get("setup", []):
            cmd = [sys.executable if c == "{python}" else os.path.join(proj, VENV_PYTHON) if c == "{venv_python}" else c
                   for c in cmd]
            r = run(cmd, proj)
            if r.returncode != 0:
                return ["setup 失敗：{}\n{}".format(" ".join(cmd), r.stdout[-3000:])]
        for cmd in (["init", "-q", "-b", "main"], ["add", "-A"],
                    ["-c", "user.name=selftest", "-c", "user.email=selftest@example.com", "commit", "-q", "-m", "init"]):
            run(["git"] + cmd, proj, check=True)

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

        for sc in case["scenarios"]:
            run(["git", "checkout", "-q", "--", "."], proj, check=True)
            run(["git", "clean", "-q", "-fd"], proj, check=True)
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
                    text = e["content"]  # 新增檔案
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8", newline="") as fp:
                    fp.write(text)
            else:
                failed += check(sc["name"], proj, sc["run"], sc["exit"], sc.get("contains", []))
    finally:
        if args.keep:
            print("  暫存目錄：" + proj)
        else:
            shutil.rmtree(tmp, onerror=_force_remove)
    return failed


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


def check(title, proj, cmd, code, contains=()):
    r = quality(proj, cmd)
    missing = [c for c in contains if c not in r.stdout]
    ok = r.returncode == code and not missing
    detail = "結束碼 {}（預期 {}）".format(r.returncode, code)
    if missing:
        detail += "；輸出缺少：" + "、".join(missing)
    return report(title, r, ok, detail)


def report(title, r, ok, detail):
    print("  {} {}".format("✅" if ok else "❌", title), flush=True)
    if ok:
        return []
    print("     " + detail.replace("\n", "\n     "))
    print("     實際輸出：\n     " + (r.stdout + r.stderr)[-3000:].replace("\n", "\n     "))
    return [title]


def quality(proj, cmd):
    return run([sys.executable, QUALITY] + cmd, proj)


def run(cmd, cwd, check=False):
    env = dict(os.environ, PYTHONUTF8="1")
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
