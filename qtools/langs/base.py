"""語言轉接的介面，加上各語言共用的版本檢查。

每個語言模組提供一個 Language 的子類別，只負責呼叫量測工具、轉成 qtools.model 的 Function 和 Mutant，
不判斷門檻、不印結果。找出改到的行、算 CRAP、算抓錯率、輸出報告，都是核心的事。
"""

import importlib

from qtools.proc import QualityError

MODULES = {"go": "go", "csharp": "csharp", "js": "js", "python": "python"}


class Language:
    SOURCE_GLOBS = []  # git ls-files 的樣式，用來列出這個語言的原始碼

    def __init__(self):
        self.tools = {}  # 這次實際用到的量測工具和版本，寫進 JSON 報告的 tools 欄位

    def is_test(self, path):
        raise NotImplementedError

    def package_dir(self, path):
        """檔案所屬的套件目錄（相對於專案根目錄）。"""
        raise NotImplementedError

    def report_group(self, path):
        """現況報告和 JSON 的抓錯統計依什麼分組，預設跟套件一樣；語言可以指定更細的分組。"""
        return self.package_dir(path)

    def run_tests(self, cfg):
        """執行專案的單元測試，回傳結束碼。測試輸出直接顯示。"""
        raise NotImplementedError

    def measure_functions(self, cfg):
        """回傳 [Function]：每個函式的圈複雜度、起訖行、覆蓋率（0～1）。測試沒過要丟 QualityError。"""
        raise NotImplementedError

    def measure_mutants(self, cfg, dirs=None, files=None):
        """回傳 [Mutant]。dirs 和 files 給了就只量這些套件和檔案，否則量整個專案。"""
        raise NotImplementedError


def load_language(name):
    if name not in MODULES:
        raise QualityError("不支援的語言：{}（支援 {}）".format(name, "、".join(MODULES)))
    module = importlib.import_module("qtools.langs." + MODULES[name])
    return module.LANGUAGE()


def check_version(name, actual, verified):
    """各 repo 自己安裝的量測工具（StrykerJS、cosmic-ray）必須是驗證過的版本，否則丟 QualityError（結束碼 2）。

    這些工具要跟專案的測試框架裝在一起，所以版本由各 repo 決定。工具只擋下沒驗證過的版本，
    免得 repo 自己升級之後，分數悄悄飄掉。要支援新版本時，改這裡的清單、跑 selftest、發新版。
    """
    if actual not in verified:
        raise QualityError("{} {} 不在這個版本的 quality-tools 驗證過的清單內，分數可能跟其他專案不能比。"
                           "驗證過的版本：{}".format(name, actual, "、".join(verified)))
