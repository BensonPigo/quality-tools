"""不需要語言工具的純函式測試：版本檢查、設定檔 v2 與 migrate、JSON 報告格式、CRAP 建議、抓錯比例。

selftest.py 一開始會先跑這支。檔名刻意不符合 test_*.py、*_test.py、*.test.*，專案的 pytest、Vitest、Jest
預設不會把掛在 tools/quality 底下的這支收進去。用標準函式庫 unittest：

    python dev/unit_checks.py
"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qtools import config, crap, mutation, report, report_schema  # noqa: E402
from qtools.langs import base, csharp, go, js, python  # noqa: E402
from qtools.model import Function, Mutant  # noqa: E402
from qtools.proc import QualityError  # noqa: E402


class VersionChecks(unittest.TestCase):
    def test_in_list_passes(self):
        base.check_version("cosmic-ray", "8.7.0", ["8.7.0"])

    def test_not_in_list_exits_2_and_lists_verified(self):
        with self.assertRaises(QualityError) as cm:
            base.check_version("cosmic-ray", "8.6.0", ["8.7.0"])
        self.assertEqual(cm.exception.exit_code, 2)
        self.assertIn("8.7.0", str(cm.exception))
        self.assertIn("8.6.0", str(cm.exception))

    def test_cosmic_ray_adapter(self):
        python.check_cosmic_ray("8.7.0")
        with self.assertRaises(QualityError) as cm:
            python.check_cosmic_ray("8.6.0")
        self.assertEqual(cm.exception.exit_code, 2)
        self.assertIn("8.7.0", str(cm.exception))

    def test_stryker_adapter_accepts_verified_combinations(self):
        js.check_stryker("10.0.0", "10.0.0", "jest")
        js.check_stryker("10.0.0", "10.0.0", "vitest", "4.0.0")
        js.check_stryker("10.1.1", "10.1.1", "vitest", "5.0.0")

    def test_stryker_adapter_rejects_unverified_core(self):
        with self.assertRaises(QualityError) as cm:
            js.check_stryker("9.0.0", "10.0.0", "jest")
        self.assertEqual(cm.exception.exit_code, 2)
        for version in ("10.0.0", "10.1.1"):
            self.assertIn(version, str(cm.exception))

    def test_stryker_adapter_rejects_unverified_runner(self):
        with self.assertRaises(QualityError) as cm:
            js.check_stryker("10.0.0", "10.0.1", "vitest", "4.0.0")
        self.assertIn("10.1.1", str(cm.exception))

    def test_stryker_vitest5_needs_10_1_1(self):
        with self.assertRaises(QualityError) as cm:
            js.check_stryker("10.0.0", "10.0.0", "vitest", "5.0.0")
        self.assertIn("Vitest 5.0.0", str(cm.exception))
        self.assertIn("10.1.1", str(cm.exception))

    def test_pinned_tool_versions(self):
        self.assertTrue(go.GOCYCLO.endswith("gocyclo@v0.6.0"))
        self.assertTrue(go.GREMLINS.endswith("gremlins@v0.6.0"))
        self.assertEqual(csharp.STRYKER_VERSION, "5.0.0")
        self.assertEqual(js.TYPESCRIPT_VERSION, "5.9.3")


class ConfigChecks(unittest.TestCase):
    def v2(self, **extra):
        raw = {"version": 2, "language": "go"}
        raw.update(extra)
        return raw

    def test_defaults_filled(self):
        cfg = config.validate(self.v2())
        self.assertEqual(cfg["crap"]["threshold"], 12)
        self.assertEqual(cfg["mutation"]["kill_rate_threshold"], 80)
        self.assertEqual(cfg["mutation"]["reach_rate_threshold"], 50)
        self.assertEqual(cfg["gates"], ["test", "crap", "mutation"])

    def test_partial_nested_section_keeps_other_defaults(self):
        cfg = config.validate(self.v2(mutation={"kill_rate_threshold": 90}))
        self.assertEqual(cfg["mutation"]["kill_rate_threshold"], 90)
        self.assertEqual(cfg["mutation"]["reach_rate_threshold"], 50)

    def test_v1_keys_point_to_migrate(self):
        for key, value in (("efficacy_threshold", 80), ("mutant_coverage_threshold", 0), ("crap_threshold", 12),
                           ("dotnet_solution", "a.sln"), ("js_test_runner", "jest"), ("python_mutant_timeout", 30)):
            with self.assertRaises(QualityError, msg=key) as cm:
                config.validate(self.v2(**{key: value}))
            self.assertIn("migrate", str(cm.exception))

    def test_missing_version_points_to_migrate(self):
        with self.assertRaises(QualityError) as cm:
            config.validate({"language": "go"})
        self.assertIn("migrate", str(cm.exception))

    def test_v1_python_string_points_to_migrate(self):
        with self.assertRaises(QualityError) as cm:
            config.validate(self.v2(python="/usr/bin/python3"))
        self.assertIn("migrate", str(cm.exception))

    def test_unknown_keys_rejected(self):
        with self.assertRaises(QualityError) as cm:
            config.validate(self.v2(crapp={"threshold": 1}))
        self.assertIn("crapp", str(cm.exception))
        with self.assertRaises(QualityError) as cm:
            config.validate(self.v2(mutation={"kill_rate": 1}))
        self.assertIn("mutation.kill_rate", str(cm.exception))

    def test_bad_values_rejected(self):
        for raw in (self.v2(language="java"), self.v2(gates=["lint"]), self.v2(crap={"threshold": "12"}),
                    self.v2(mutation={"workers": 0}), self.v2(js={"test_runner": "mocha"})):
            with self.assertRaises(QualityError):
                config.validate(raw)


class MigrateChecks(unittest.TestCase):
    """v1 → v2 設定對照表，每一列一個測試。"""

    V1 = {"language": "go"}

    def migrate(self, **extra):
        v1 = dict(self.V1)
        v1.update(extra)
        v2 = config.migrate_config(v1)
        config.validate(copy.deepcopy(v2))  # 轉出來的設定一定要能通過 v2 的驗證
        return v2

    def test_version(self):
        self.assertEqual(self.migrate()["version"], 2)

    def test_language_required(self):
        with self.assertRaises(QualityError):
            config.migrate_config({"base": "main"})

    def test_language_copied(self):
        self.assertEqual(self.migrate(language="python")["language"], "python")

    def test_base_default_and_copy(self):
        self.assertEqual(self.migrate()["base"], "origin/main")
        self.assertEqual(self.migrate(base="origin/develop")["base"], "origin/develop")

    def test_gates_are_v1_behaviour(self):
        self.assertEqual(self.migrate()["gates"], ["test", "crap", "mutation"])

    def test_exclude_default_and_copy(self):
        self.assertEqual(self.migrate()["exclude"], ["tools/", "vendor/", "node_modules/"])
        self.assertEqual(self.migrate(exclude=["gen/"])["exclude"], ["gen/"])

    def test_crap_threshold(self):
        self.assertEqual(self.migrate()["crap"]["threshold"], 12)
        self.assertEqual(self.migrate(crap_threshold=15)["crap"]["threshold"], 15)

    def test_efficacy_threshold(self):
        self.assertEqual(self.migrate()["mutation"]["kill_rate_threshold"], 80)
        self.assertEqual(self.migrate(efficacy_threshold=70)["mutation"]["kill_rate_threshold"], 70)

    def test_mutant_coverage_threshold_keeps_v1_behaviour(self):
        self.assertEqual(self.migrate()["mutation"]["reach_rate_threshold"], 0)  # 不自動調成 50
        self.assertEqual(self.migrate(mutant_coverage_threshold=40)["mutation"]["reach_rate_threshold"], 40)

    def test_python_mutant_timeout(self):
        self.assertNotIn("timeout_seconds", self.migrate()["mutation"])
        self.assertEqual(self.migrate(python_mutant_timeout=60)["mutation"]["timeout_seconds"], 60)

    def test_dotnet_solution(self):
        self.assertNotIn("csharp", self.migrate())
        self.assertEqual(self.migrate(dotnet_solution="A.sln")["csharp"], {"solution": "A.sln"})

    def test_js_test_runner(self):
        self.assertNotIn("js", self.migrate())
        self.assertEqual(self.migrate(js_test_runner="vitest")["js"], {"test_runner": "vitest"})

    def test_python_interpreter(self):
        self.assertNotIn("python", self.migrate())
        self.assertEqual(self.migrate(python="py/bin/python")["python"], {"interpreter": "py/bin/python"})

    def test_unknown_v1_key_rejected(self):
        with self.assertRaises(QualityError):
            config.migrate_config({"language": "go", "efficiency_threshold": 80})

    def test_already_v2_rejected(self):
        with self.assertRaises(QualityError):
            config.migrate_config({"version": 2, "language": "go"})

    def test_same_verdict_as_v1_with_defaults(self):
        # 沒有任何 v1 鍵時，v1 的判定是 CRAP 12、抓錯率 80、測到率不擋
        cfg = config.validate(self.migrate())
        self.assertEqual((cfg["crap"]["threshold"], cfg["mutation"]["kill_rate_threshold"],
                          cfg["mutation"]["reach_rate_threshold"]), (12, 80, 0))


class SchemaChecks(unittest.TestCase):
    def sample(self, command="baseline"):
        funcs = [Function("a.go", "Weight", 15, 18, 5, 0.0, crap=30.0), Function("a.go", "Fee", 4, 12, 3, 0.4, crap=4.9)]
        mutants = [Mutant("a.go", 5, "LIVED", "CONDITIONALS_BOUNDARY", column=7, line_text="if total >= 1000 {"),
                   Mutant("a.go", 9, "KILLED", "ARITHMETIC_BASE")]
        cfg = config.validate({"version": 2, "language": "go"})
        counts = mutation.count(mutants)
        lang = go.LANGUAGE()
        lang.tools["gocyclo"] = "v0.6.0"
        crap_part = report.crap_json(funcs, 12, 0) if command != "mutation" else None
        mutation_part = report.mutation_json(mutants, counts, cfg, lang.report_group) if command != "crap" else None
        return report.build_report(command, cfg, lang, "main", "abc123", True, crap_part, mutation_part)

    def test_valid_reports(self):
        for command in ("crap", "mutation", "baseline"):
            self.assertEqual(report_schema.validate(self.sample(command)), [], command)

    def test_missing_field_fails(self):
        for path in (("commit",), ("crap", "threshold"), ("crap", "functions", 0, "hot")):
            data = self.sample("crap")
            target = data
            for key in path[:-1]:
                target = target[key]
            del target[path[-1]]
            errors = report_schema.validate(data)
            self.assertTrue(errors and any("缺少欄位" in e for e in errors), path)

    def test_extra_field_fails(self):
        data = self.sample("mutation")
        data["mutation"]["mutants"][0]["extra"] = 1
        self.assertTrue(any("多出欄位" in e for e in report_schema.validate(data)))
        data = self.sample("mutation")
        data["surprise"] = True
        self.assertTrue(any("多出欄位" in e for e in report_schema.validate(data)))

    def test_wrong_type_fails(self):
        data = self.sample("crap")
        data["crap"]["functions"][0]["start"] = "15"
        self.assertTrue(report_schema.validate(data))
        data = self.sample("crap")
        data["crap"]["functions"][0]["over"] = 1  # int 不是 bool
        self.assertTrue(report_schema.validate(data))
        data = self.sample("crap")
        data["schema"] = True  # bool 不是 int
        self.assertTrue(report_schema.validate(data))
        data = self.sample("crap")
        data["result"] = "ok"
        self.assertTrue(report_schema.validate(data))

    def test_command_decides_which_parts_exist(self):
        data = self.sample("crap")
        data["mutation"] = self.sample("mutation")["mutation"]
        self.assertTrue(report_schema.validate(data))
        data = self.sample("mutation")
        data["crap"] = None
        data["mutation"] = None
        self.assertTrue(report_schema.validate(data))

    def test_nullable_fields_accept_null(self):
        data = self.sample("mutation")
        self.assertIsNone(data["mutation"]["mutants"][1]["column"])
        self.assertEqual(report_schema.validate(data), [])


class CrapChecks(unittest.TestCase):
    def test_formula(self):
        self.assertEqual(crap.crap_score(5, 0.0), 30.0)
        self.assertEqual(crap.crap_score(14, 1.0), 14.0)

    def test_over_complexity_needs_split(self):
        self.assertEqual(crap.advice(14, 12), ("split", None))
        self.assertEqual(crap.advice_text(14, 12), "要拆函式")

    def test_cover_target(self):
        self.assertEqual(crap.advice(5, 12), ("cover", 35))
        self.assertEqual(crap.advice_text(5, 12), "覆蓋率要到 35%")
        self.assertEqual(crap.advice(12, 12), ("cover", 100))  # C 剛好等於門檻，要全覆蓋才過

    def test_sorted_high_to_low(self):
        funcs = crap.score_functions([Function("a", "low", 1, 2, 1, 1.0), Function("a", "high", 3, 9, 6, 0.0)])
        self.assertEqual([f.name for f in funcs], ["high", "low"])


class MutationChecks(unittest.TestCase):
    def counts(self, **n):
        c = mutation.count([])
        c.update(n)
        return c

    def test_rates(self):
        c = self.counts(KILLED=6, TIMED_OUT=2, LIVED=2, NOT_COVERED=10)
        self.assertEqual(mutation.kill_rate(c), 80.0)
        self.assertEqual(mutation.reach_rate(c), 50.0)

    def test_excluded_statuses_not_counted(self):
        c = self.counts(KILLED=1, LIVED=1, EQUIVALENT=5, EXCLUDED_MUTATOR=5, NOT_VIABLE=5, SKIPPED=5)
        self.assertEqual(mutation.kill_rate(c), 50.0)
        self.assertEqual(mutation.reach_rate(c), 100.0)

    def test_no_mutants_gives_none(self):
        c = self.counts()
        self.assertIsNone(mutation.kill_rate(c))
        self.assertIsNone(mutation.reach_rate(c))

    def test_judge_uses_thresholds(self):
        cfg = config.validate({"version": 2, "language": "go",
                               "mutation": {"kill_rate_threshold": 80, "reach_rate_threshold": 50}})
        self.assertEqual(mutation.judge(self.counts(KILLED=8, LIVED=2, NOT_COVERED=10), cfg), [])
        self.assertEqual(len(mutation.judge(self.counts(KILLED=7, LIVED=3), cfg)), 1)
        self.assertEqual(len(mutation.judge(self.counts(KILLED=1, NOT_COVERED=9), cfg)), 1)


if __name__ == "__main__":
    unittest.main()
