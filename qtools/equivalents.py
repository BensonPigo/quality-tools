"""改了也沒差的版本排除清單：讀取、驗證、比對。

清單放在各 repo 的 .quality-equivalents.json，由人判斷後寫入，格式見 docs。比對鍵是
file + mutator + 該行去頭尾空白後的原文，不用行號：前面插幾行也還對得上；那一行被改了就失效，
要人重新判斷，這是刻意的。function 只用來顯示和人工檢查，不參與比對。
"""

import json
import os

from qtools.model import EQUIVALENT, EXCLUDED_MUTATOR
from qtools.proc import QualityError, normalize

REQUIRED = ("file", "mutator", "line_text", "reason", "approved_by")
OPTIONAL = ("function",)


def load(path):
    """讀排除清單。檔案不存在等於空清單；格式錯誤、缺必填欄位、有不認得的鍵都丟 QualityError（結束碼 2）。"""
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except ValueError as e:
        raise QualityError("{} 不是合法的 JSON：{}".format(path, e))
    return validate(data, path)


def validate(data, path=".quality-equivalents.json"):
    if not isinstance(data, list):
        raise QualityError("{} 的最外層必須是陣列，每一項描述一個改了也沒差的改壞版本".format(path))
    problems = []
    for i, item in enumerate(data, 1):
        if not isinstance(item, dict):
            problems.append("第 {} 項必須是物件".format(i))
            continue
        for key in item:
            if key not in REQUIRED and key not in OPTIONAL:
                problems.append("第 {} 項有不認得的鍵：{}".format(i, key))
        for key in REQUIRED:
            if key not in item:
                problems.append("第 {} 項缺少必填欄位 {}".format(i, key))
            elif not isinstance(item[key], str) or not item[key].strip():
                problems.append("第 {} 項的 {} 必須是非空白的字串".format(i, key))
        if "function" in item and not isinstance(item["function"], str):
            problems.append("第 {} 項的 function 必須是字串".format(i))
    if problems:
        raise QualityError("{} 有誤：\n  ".format(path) + "\n  ".join(problems))
    return data


def _key(file, mutator, line_text):
    # 清單裡的路徑可能寫成 ./x.go 或用 \ 分隔，跟量測工具回報的相對路徑統一成同一種寫法再比
    return (normalize(file), mutator, line_text.strip())


def apply(mutants, entries, universe=None, scope=None):
    """把對得上排除清單的改壞版本標成 EQUIVALENT，回傳沒用到的項目（清單原樣）。

    universe 是這次量到的全部改壞版本（含 --base 過濾掉的），沒給就用 mutants；對得上 universe 的項目都算有用到。
    scope 是這次量測範圍內的檔案集合，「沒用到」只算 file 在 scope 裡的項目：--base 時沒改到的檔案不在範圍內，
    不能因此說它沒用到。scope 是 None 代表整個專案都在範圍內。
    已經被 exclude_mutators 排除的改壞版本不再比對，免得同一個改壞版本被算兩次。
    """
    universe = mutants if universe is None else universe
    wanted = {}
    for e in entries:
        wanted.setdefault(_key(e["file"], e["mutator"], e["line_text"]), []).append(e)
    in_scope = None if scope is None else {normalize(f) for f in scope}

    used = set()
    for m in universe:
        if m.status != EXCLUDED_MUTATOR and _key(m.file, m.mutator, m.line_text) in wanted:
            used.add(_key(m.file, m.mutator, m.line_text))
    for m in mutants:
        if m.status != EXCLUDED_MUTATOR and _key(m.file, m.mutator, m.line_text) in wanted:
            m.status = EQUIVALENT

    return [e for e in entries
            if (in_scope is None or normalize(e["file"]) in in_scope) and _key(e["file"], e["mutator"], e["line_text"]) not in used]
