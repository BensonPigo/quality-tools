"""執行外部指令、路徑和檔案清單的共用工具。只用 Python 標準函式庫。"""

import os
import subprocess

# 工具本身的根目錄（quality.py 所在的目錄），qtools/helpers/ 底下的輔助程式從這裡找
TOOL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class QualityError(Exception):
    """量測沒辦法完成，或設定有誤，例如測試沒過、工具執行失敗。訊息會直接顯示給使用者，結束碼 2。"""

    exit_code = 2


def run(cmd, cwd=None, env=None):
    """執行指令並回傳 CompletedProcess，stdout 和 stderr 分開以文字保存。"""
    try:
        return subprocess.run(
            cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        raise QualityError("找不到指令 {}，請確認已安裝並加入 PATH".format(cmd[0]))


def git(*args):
    r = run(["git", "-c", "core.quotepath=false"] + list(args))
    if r.returncode != 0:
        raise QualityError("git {} 執行失敗：\n{}".format(" ".join(args), r.stderr))
    return r.stdout


def normalize(path):
    """路徑統一用 / 分隔，去掉開頭的 ./"""
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def project_path(path, base=None):
    """工具回報的路徑轉成相對於專案根目錄、用 / 分隔的路徑。相對路徑以 base 為起點，預設是專案根目錄。

    Windows 上同一個目錄可能有兩種寫法：8.3 短檔名（C:/Users/ALEXAN~1.LIN）和長檔名（C:/Users/alexander.lin）。
    工具回報的通常是長檔名，執行目錄卻可能是短檔名，直接算相對路徑會對不起來，所以兩邊都先轉成實際路徑。
    """
    if not os.path.isabs(path):
        path = os.path.join(base or os.getcwd(), path)
    return normalize(os.path.relpath(os.path.realpath(path), os.path.realpath(os.getcwd())))


def list_files(globs):
    """列出符合樣式的檔案：git 追蹤中的，加上還沒加入 git 的新檔案（不含 .gitignore 排除的）。"""
    files = set()
    for args in (["ls-files"], ["ls-files", "--others", "--exclude-standard"]):
        r = run(["git", "-c", "core.quotepath=false"] + args + ["--"] + list(globs))
        if r.returncode != 0:
            raise QualityError("git ls-files 執行失敗：\n" + r.stderr)
        files.update(normalize(line) for line in r.stdout.splitlines() if line.strip())
    # 已刪除但還沒 commit 的檔案不算；submodule（例如掛在 tools/quality 的本工具）在清單裡是目錄，也不算
    return sorted(f for f in files if os.path.isfile(f))


def tools_dir():
    """外部工具（Stryker、建置好的量測程式）的快取目錄，可以用環境變數 QUALITY_TOOLS_DIR 指定。

    預設放在使用者目錄底下的短路徑：Windows 上路徑超過 260 字元時，有些工具會讀不到檔案的版本資訊而當掉。
    """
    return os.environ.get("QUALITY_TOOLS_DIR") or os.path.join(os.path.expanduser("~"), ".cache", "quality-tools")


def is_excluded(path, cfg):
    """path 是否在 .quality.json 的 exclude 目錄底下。"""
    path = normalize(path)
    for e in cfg["exclude"]:
        e = normalize(e).rstrip("/")
        if path == e or path.startswith(e + "/"):
            return True
    return False


def tail(text, n=40):
    return "\n".join(text.rstrip().splitlines()[-n:])
