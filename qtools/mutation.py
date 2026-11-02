"""抓錯率、測到率和改壞版本的整理。

抓錯率 = (抓到 + 逾時) ÷ (抓到 + 逾時 + 沒抓到)：有測到的改壞版本裡，抓到幾成。
測到率 = (抓到 + 逾時 + 沒抓到) ÷ (抓到 + 逾時 + 沒抓到 + 測試沒跑到)：全部改壞版本裡，有幾成被測試跑到。
已排除（改了也沒差、設定排除的改法）、無效、略過，都不算進這兩個比例。
"""

from collections import defaultdict

from qtools.model import EXCLUDED_MUTATOR, KILLED, LIVED, NOT_COVERED, STATUSES, TIMED_OUT


def count(mutants):
    counts = {s: 0 for s in STATUSES}
    for m in mutants:
        counts[m.status] += 1
    return counts


def detected(counts):
    return counts[KILLED] + counts[TIMED_OUT]


def kill_rate(counts):
    covered = detected(counts) + counts[LIVED]
    return 100.0 * detected(counts) / covered if covered else None


def reach_rate(counts):
    covered = detected(counts) + counts[LIVED]
    total = covered + counts[NOT_COVERED]
    return 100.0 * covered / total if total else None


def judge(counts, cfg):
    """依門檻判斷，回傳沒過的原因（空串列代表通過）。"""
    m = cfg["mutation"]
    problems = []
    k, r = kill_rate(counts), reach_rate(counts)
    if k is not None and k < m["kill_rate_threshold"]:
        problems.append("抓錯率低於門檻，有改壞的版本沒被抓到：補測試把它抓出來；認為改了也沒差的，在 PR 裡說明")
    if r is not None and r < m["reach_rate_threshold"]:
        problems.append("測到率低於門檻：有改到的程式碼沒有測試")
    return problems


def by_package(mutants, group):
    """{套件: 各狀態的數量}。group 是語言轉接提供的分組函式。"""
    packages = defaultdict(list)
    for m in mutants:
        packages[group(m.file)].append(m)
    return {p: count(ms) for p, ms in packages.items()}


_source_cache = {}


def source_lines(file):
    """檔案的每一行（不含換行字元），讀過的檔案會快取。檔案不見了（例如被刪掉）回傳空串列。"""
    if file not in _source_cache:
        try:
            # utf-8-sig：檔案開頭有 BOM 時，第一行的欄位位置才跟工具回報的對得上
            with open(file, encoding="utf-8-sig", errors="replace") as f:
                _source_cache[file] = f.read().splitlines()
        except OSError:
            _source_cache[file] = []
    return _source_cache[file]


def fill_line_text(mutants):
    """填入每個改壞版本所在那一行的原文（去頭尾空白）。"""
    for m in mutants:
        lines = source_lines(m.file)
        m.line_text = lines[m.line - 1].strip() if 0 < m.line <= len(lines) else ""
    return mutants


def span_text(file, start, end):
    """原始檔裡 start 到 end 之間的文字，位置是 (行, 欄)，行從 1 起算，欄從 0 起算，end 不含。

    跨行時只取第一行，結尾加「…」。讀不到（檔案不見、位置超出）回傳 None。
    """
    lines = source_lines(file)
    (sl, sc), (el, ec) = start, end
    if not 0 < sl <= len(lines) or el < sl:
        return None
    first = lines[sl - 1]
    if el == sl:
        text = first[sc:ec]
    elif el == sl + 1 and ec == 0:  # 結尾落在下一行行首，等於包含這一行的換行字元
        text = first[sc:]
    else:
        return first[sc:] + "…"
    return text if text else None


def location_text(file, location):
    """Stryker 系列（Stryker.NET、StrykerJS）報告的 location 對應的原文。報告的行、欄都從 1 起算，end 不含。"""
    try:
        start, end = location["start"], location["end"]
        return span_text(file, (start["line"], start["column"] - 1), (end["line"], end["column"] - 1))
    except (KeyError, TypeError):
        return None


def exclude_mutators(mutants, names):
    """名稱在 names 裡的改壞版本一律標成 EXCLUDED_MUTATOR，不看原本的狀態。名稱用各工具報告裡的名稱。"""
    names = set(names)
    for m in mutants:
        if m.mutator in names:
            m.status = EXCLUDED_MUTATOR
    return mutants


def describe(m):
    """一個改壞版本改了什麼，例如「把 `>=` 改成 `>`」。取不到改成什麼時，退回「改法 名稱」。"""
    if m.replacement is None or not m.original:
        return "改法 " + m.mutator
    if m.replacement == "":
        return "把 `{}` 刪掉".format(_one_line(m.original))
    return "把 `{}` 改成 `{}`".format(_one_line(m.original), _one_line(m.replacement))


def _one_line(text):
    """多行的文字只取第一行，結尾加「…」。"""
    lines = text.splitlines()
    return lines[0] + "…" if len(lines) > 1 else text
