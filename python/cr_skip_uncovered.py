"""cosmic-ray 過濾器：把落在沒被測試執行到的行上的突變體標成略過，不用真的去跑。

用法（由 lang_python.py 呼叫，要用裝了 cosmic-ray 的 Python 執行）：

    python cr_skip_uncovered.py <session.sqlite> <executed.json>

executed.json 的格式是 {檔案相對路徑: [執行到的行號, ...]}，行號來自 coverage.py，
是每個敘述的第一行。突變體可能落在跨多行敘述的中間，所以先找出包住它的最內層敘述，
再看那個敘述的第一行有沒有執行到。

被略過的突變體，output 會標上 NOT_COVERED_MARK，lang_python.py 據此歸類成「沒覆蓋」。
"""

import ast
import json
import sys

from cosmic_ray.work_db import use_db, WorkDB
from cosmic_ray.work_item import WorkResult, WorkerOutcome

NOT_COVERED_MARK = "quality:not-covered"


def main(session, executed_path):
    with open(executed_path, encoding="utf-8") as fp:
        executed = {k: set(v) for k, v in json.load(fp).items()}

    statements = {}
    skip = []
    with use_db(session, WorkDB.Mode.open) as db:
        for item in db.pending_work_items:
            m = item.mutations[0]
            file = str(m.module_path).replace("\\", "/")
            if file not in statements:
                statements[file] = _statement_ranges(file)
            first = _first_line(statements[file], m.start_pos[0])
            if first not in executed.get(file, ()):
                skip.append(item.job_id)
        if skip:
            db.set_multiple_results(skip, WorkResult(output=NOT_COVERED_MARK, worker_outcome=WorkerOutcome.SKIPPED))
    print("略過 {} 個沒被測試執行到的突變體".format(len(skip)), file=sys.stderr)


def _statement_ranges(file):
    with open(file, encoding="utf-8") as fp:
        tree = ast.parse(fp.read(), filename=file)
    return [(n.lineno, n.end_lineno) for n in ast.walk(tree) if isinstance(n, ast.stmt)]


def _first_line(ranges, line):
    """包住 line 的最內層敘述的第一行。找不到就回傳 line 本身。"""
    inside = [r for r in ranges if r[0] <= line <= r[1]]
    if not inside:
        return line
    return min(inside, key=lambda r: (r[1] - r[0], -r[0]))[0]


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
