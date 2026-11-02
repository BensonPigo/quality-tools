"""v2 和 v1.0.0 的分數對照。不屬於發布內容，只在開發重寫時用。

v2 的量測算法必須跟 v1 一模一樣，分數才能跟各 repo 第 0 步的報告比較。這支腳本用五個範例專案證明這件事：

    python dev/v1_parity.py record [範例...]    # 用 v1.0.0 跑一遍，結果寫到 dev/v1-parity.json
    python dev/v1_parity.py check [範例...]     # 用目前的工具跑一遍，跟 v1-parity.json 比對

record：git worktree 取出 v1.0.0，範例用 v1.0.0 自己的打包檔解開（設定檔是 v1 鍵名），
        用 v1 的 quality.py 跑整個專案（不加 --base）的 crap 和 mutation，解析 v1 的文字輸出。
check： 範例用目前的打包檔解開（設定檔是 v2），照 selftest 的方式掛上工具，跑 crap --json 和 mutation --json。

比對規則：
- CRAP 表每一列（CRAP 取一位小數、C、覆蓋率取一位小數、函式、檔案:行）逐列完全相同，順序也要一樣。
- 抓到 + 逾時的合計、沒抓到、測試沒跑到三個數字完全相同。抓到和逾時會因為機器負載互換
  （測試卡住的時限差一點點，結果就從抓到變逾時），所以合計比對。
有差異時自動重跑該範例一次，仍然不同就結束碼 1 並印出差異。

結束碼：0 一致，1 有差異，2 執行失敗。
"""

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import selftest  # noqa: E402

RECORD = os.path.join(HERE, "v1-parity.json")
V1_REF = "v1.0.0"

# v1 的 CRAP 表每列：CRAP、C、覆蓋率%、函式名稱（可能含空白）、檔案:行，超標的後面接 ❌ 和建議
CRAP_ROW = re.compile(r"^(\d+\.\d)\s+(\d+)\s+(\d+\.\d)%\s+(.+?)\s+(\S+:\d+)(?:\s+❌.*)?\s*$")
V1_COUNTS = re.compile(r"殺死 (\d+)、超時 (\d+)、存活 (\d+)、沒覆蓋 (\d+)")


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="v2 和 v1.0.0 的分數對照")
    parser.add_argument("mode", choices=["record", "check"])
    parser.add_argument("samples", nargs="*", help="要跑的範例，預設全部")
    args = parser.parse_args()

    names = args.samples or sorted(f[:-len(".json")] for f in os.listdir(selftest.CASES) if f.endswith(".json"))
    try:
        sys.exit(record(names) if args.mode == "record" else check(names))
    except RuntimeError as e:
        print(e, file=sys.stderr)
        sys.exit(2)


# ---------- record：用 v1.0.0 量 ----------

def record(names):
    recorded = {}
    if os.path.exists(RECORD):
        with open(RECORD, encoding="utf-8") as fp:
            recorded = json.load(fp)["samples"]

    tmp = tempfile.mkdtemp(prefix="qp-")
    worktree = os.path.join(tmp, "v1")
    git(["worktree", "add", "--detach", worktree, V1_REF])
    try:
        v1_selftest = _load_v1_selftest(worktree)
        for name in names:
            print("=== record {}".format(name), flush=True)
            recorded[name] = _measure_v1(name, tmp, worktree, v1_selftest)
            print("  CRAP {} 列；{}".format(len(recorded[name]["crap"]), recorded[name]["mutation"]), flush=True)
    finally:
        git(["worktree", "remove", "--force", worktree])
        shutil.rmtree(tmp, onerror=selftest._force_remove)

    with open(RECORD, "w", encoding="utf-8", newline="\n") as fp:
        json.dump({"v1_ref": V1_REF, "samples": dict(sorted(recorded.items()))}, fp, ensure_ascii=False, indent=2)
        fp.write("\n")
    print("已寫入 " + os.path.relpath(RECORD, ROOT))
    return 0


def _load_v1_selftest(worktree):
    """載入 v1.0.0 的 selftest.py，用它的 unpack 和它的打包檔（設定檔是 v1 鍵名）。"""
    spec = importlib.util.spec_from_file_location("selftest_v1", os.path.join(worktree, "selftest.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _measure_v1(name, tmp, worktree, v1_selftest):
    with open(os.path.join(worktree, "selftest", name + ".json"), encoding="utf-8") as fp:
        setup = json.load(fp).get("setup", [])
    proj = os.path.join(tmp, name)
    error = selftest.prepare(name, proj, setup, unpack_fn=v1_selftest.unpack, mount=False)
    if error:
        raise RuntimeError(name + "：" + error)
    try:
        quality = os.path.join(worktree, "quality.py")
        r = selftest.run([sys.executable, quality, "crap"], proj)
        if r.returncode == 2:
            raise RuntimeError("{}：v1 crap 執行失敗\n{}{}".format(name, r.stdout[-2000:], r.stderr[-2000:]))
        crap = _parse_v1_crap(r.stdout)
        r = selftest.run([sys.executable, quality, "mutation"], proj)
        if r.returncode == 2:
            raise RuntimeError("{}：v1 mutation 執行失敗\n{}{}".format(name, r.stdout[-2000:], r.stderr[-2000:]))
        m = V1_COUNTS.search(r.stdout)
        if not m:
            raise RuntimeError("{}：v1 mutation 輸出找不到計數行\n{}".format(name, r.stdout[-2000:]))
        killed, timed_out, lived, not_covered = (int(x) for x in m.groups())
        return {"crap": crap,
                "mutation": {"killed": killed, "timed_out": timed_out, "lived": lived, "not_covered": not_covered}}
    finally:
        shutil.rmtree(proj, onerror=selftest._force_remove)


def _parse_v1_crap(stdout):
    lines = stdout.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("CRAP ")), None)
    if start is None:
        raise RuntimeError("v1 crap 輸出找不到表頭\n" + stdout[-2000:])
    rows = []
    for line in lines[start + 1:]:
        if not line.strip():  # 表格後面第一個空行
            break
        m = CRAP_ROW.match(line)
        if not m:
            raise RuntimeError("看不懂 v1 的 CRAP 列：" + line)
        crap, c, cover, func, pos = m.groups()
        rows.append([crap, int(c), cover, func, pos])
    return rows


# ---------- check：用目前的工具量，跟紀錄比對 ----------

def check(names):
    if not os.path.exists(RECORD):
        raise RuntimeError("找不到 {}，先執行 record".format(os.path.relpath(RECORD, ROOT)))
    with open(RECORD, encoding="utf-8") as fp:
        recorded = json.load(fp)["samples"]

    bad = []
    for name in names:
        print("=== check {}".format(name), flush=True)
        if name not in recorded:
            raise RuntimeError("{} 不在紀錄裡，先執行 record {}".format(name, name))
        diffs = _compare(name, recorded[name], _measure_v2(name))
        if diffs:
            print("  有差異，重跑一次（抓到和逾時的判定可能受機器負載影響）", flush=True)
            diffs = _compare(name, recorded[name], _measure_v2(name))
        if diffs:
            bad.append(name)
            print("  ❌ {} 和 v1 不一致：".format(name))
            for d in diffs:
                print("     " + d)
        else:
            print("  ✅ {} 和 v1 一致".format(name), flush=True)

    print()
    if bad:
        print("FAIL：{} 不一致".format("、".join(bad)))
        return 1
    print("PASS：{} 個範例的 CRAP 表和抓錯計數都跟 v1 一致".format(len(names)))
    return 0


def _measure_v2(name):
    with open(os.path.join(selftest.CASES, name + ".json"), encoding="utf-8") as fp:
        setup = json.load(fp).get("setup", [])
    tmp = tempfile.mkdtemp(prefix="qp-")
    proj = os.path.join(tmp, name)
    try:
        error = selftest.prepare(name, proj, setup)
        if error:
            raise RuntimeError(name + "：" + error)
        out = {}
        for command in ("crap", "mutation"):
            r = selftest.quality(proj, [command, "--json", "out-{}.json".format(command)])
            if r.returncode == 2 or not os.path.exists(os.path.join(proj, "out-{}.json".format(command))):
                return {"error": "v2 {} 執行失敗（結束碼 {}）\n{}{}".format(
                    command, r.returncode, r.stdout[-2000:], r.stderr[-2000:])}
            with open(os.path.join(proj, "out-{}.json".format(command)), encoding="utf-8") as fp:
                out[command] = json.load(fp)
        c = out["mutation"]["mutation"]["counts"]
        return {
            "crap": [["{:.1f}".format(f["crap"]), f["complexity"], "{:.1f}".format(f["coverage"] * 100), f["name"],
                      "{}:{}".format(f["file"], f["start"])] for f in out["crap"]["crap"]["functions"]],
            "mutation": {"killed": c["KILLED"], "timed_out": c["TIMED_OUT"], "lived": c["LIVED"],
                         "not_covered": c["NOT_COVERED"]},
        }
    finally:
        shutil.rmtree(tmp, onerror=selftest._force_remove)


def _compare(name, v1, v2):
    if "error" in v2:
        return [v2["error"]]
    diffs = []
    if v1["crap"] != v2["crap"]:
        for i in range(max(len(v1["crap"]), len(v2["crap"]))):
            a = v1["crap"][i] if i < len(v1["crap"]) else None
            b = v2["crap"][i] if i < len(v2["crap"]) else None
            if a != b:
                diffs.append("CRAP 第 {} 列：v1 {}，v2 {}".format(i + 1, a, b))
    a, b = v1["mutation"], v2["mutation"]
    for label, x, y in (("抓到+逾時", a["killed"] + a["timed_out"], b["killed"] + b["timed_out"]),
                        ("沒抓到", a["lived"], b["lived"]),
                        ("測試沒跑到", a["not_covered"], b["not_covered"])):
        if x != y:
            diffs.append("{}：v1 {}，v2 {}".format(label, x, y))
    return diffs


def git(args):
    r = subprocess.run(["git"] + args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError("git {} 失敗：\n{}".format(" ".join(args), r.stderr))
    return r.stdout


if __name__ == "__main__":
    main()
