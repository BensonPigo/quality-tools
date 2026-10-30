"""不需要語言工具的純函式測試：版本檢查、設定檔 v2 與 migrate、JSON 報告格式、CRAP 建議、抓錯比例。

selftest.py 一開始會先跑這支。檔名刻意不符合 test_*.py、*_test.py、*.test.*，專案的 pytest、Vitest、Jest
預設不會把掛在 tools/quality 底下的這支收進去。用標準函式庫 unittest：

    python dev/unit_checks.py
"""

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qtools import cli, config, crap, equivalents, mutation, report, report_schema  # noqa: E402
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

    def test_python_mutant_timeout_only_for_python(self):
        self.assertNotIn("timeout_seconds", self.migrate()["mutation"])
        self.assertEqual(self.migrate(language="python", python_mutant_timeout=60)["mutation"]["timeout_seconds"], 60)
        for language in ("go", "csharp", "js"):
            notes = []
            v2 = config.migrate_config({"language": language, "python_mutant_timeout": 60}, notes)
            self.assertNotIn("timeout_seconds", v2["mutation"], language)
            self.assertEqual(len(notes), 1, language)
            self.assertIn("只對 Python 有效，已略過", notes[0])
        notes = []
        config.migrate_config({"language": "python", "python_mutant_timeout": 60}, notes)
        self.assertEqual(notes, [])

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
        settings = lang.settings(cfg)
        mutation_part = report.mutation_json(mutants, counts, cfg, lang.report_group, settings) if command != "crap" else None
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

    def test_settings_required_and_typed(self):
        data = self.sample("mutation")
        self.assertEqual(data["mutation"]["settings"], {"timeout_seconds": None, "workers": None, "exclude_mutators": []})
        del data["mutation"]["settings"]["workers"]
        self.assertTrue(any("缺少欄位 workers" in e for e in report_schema.validate(data)))
        data = self.sample("mutation")
        del data["mutation"]["settings"]
        self.assertTrue(any("缺少欄位 settings" in e for e in report_schema.validate(data)))
        data = self.sample("mutation")
        data["mutation"]["settings"] = {"timeout_seconds": 60, "workers": "2", "exclude_mutators": ["A"]}
        self.assertTrue(report_schema.validate(data))
        data["mutation"]["settings"] = {"timeout_seconds": 60.5, "workers": 2, "exclude_mutators": ["A"]}
        self.assertEqual(report_schema.validate(data), [])

    def test_result_skipped_needs_both_parts_null(self):
        data = self.sample("crap")
        data["result"] = "skipped"
        self.assertTrue(any("skipped" in e for e in report_schema.validate(data)))  # crap 不是 null
        data = self.sample("mutation")
        data["result"] = "skipped"
        self.assertTrue(report_schema.validate(data))  # mutation 不是 null
        data["mutation"] = None
        self.assertEqual(report_schema.validate(data), [])  # 兩者都 null 才合格

    def test_pass_and_fail_still_follow_command(self):
        for result in ("pass", "fail"):
            data = self.sample("crap")
            data["result"] = result
            data["crap"] = None  # crap 指令 crap 是 null：不合格
            self.assertTrue(report_schema.validate(data), result)
            data = self.sample("mutation")
            data["result"] = result
            data["mutation"] = None
            self.assertTrue(report_schema.validate(data), result)

    def test_build_report_skipped(self):
        cfg = config.validate({"version": 2, "language": "go"})
        data = report.build_report("crap", cfg, go.LANGUAGE(), "main", "abc", True, skipped=True)
        self.assertEqual((data["result"], data["crap"], data["mutation"]), ("skipped", None, None))
        self.assertEqual(report_schema.validate(data), [])

    def test_nullable_fields_accept_null(self):
        data = self.sample("mutation")
        self.assertIsNone(data["mutation"]["mutants"][1]["column"])
        self.assertEqual(report_schema.validate(data), [])


class GateChecks(unittest.TestCase):
    def test_order_is_fixed_regardless_of_gates_order(self):
        self.assertEqual(cli.plan_gates(["mutation", "test"], [])[0], ["test", "mutation"])
        self.assertEqual(cli.plan_gates(["mutation", "crap", "test"], [])[0], ["test", "crap", "mutation"])

    def test_classification_run_skipped_disabled(self):
        self.assertEqual(cli.plan_gates(["test", "crap", "mutation"], ["mutation"]),
                         (["test", "crap"], ["mutation"], []))
        self.assertEqual(cli.plan_gates(["mutation", "test"], []), (["test", "mutation"], [], ["crap"]))
        # 沒啟用的關就算 --skip 也列在「還沒啟用」，不重複算進略過
        self.assertEqual(cli.plan_gates(["test"], ["crap"]), (["test"], [], ["crap", "mutation"]))
        self.assertEqual(cli.plan_gates(["test", "crap"], ["test", "crap"]), ([], ["test", "crap"], ["mutation"]))

    def test_unknown_skip_name_is_exit_2(self):
        with self.assertRaises(QualityError) as ctx:
            cli.plan_gates(["test"], ["foo"])
        self.assertEqual(ctx.exception.exit_code, 2)
        self.assertIn("foo", str(ctx.exception))

    def test_not_enabled_message_and_skipped_json(self):
        cfg = config.validate({"version": 2, "language": "go", "gates": ["test"]})
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "r.json")
            args = type("A", (), {"base": "main", "json": path})()
            with contextlib.redirect_stdout(out), mock.patch.object(cli, "_commit", lambda: "abc"):
                self.assertTrue(cli.not_enabled("crap", args, cfg, go.LANGUAGE()))
                self.assertFalse(cli.not_enabled("test", args, cfg, go.LANGUAGE()))
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        self.assertIn("第 2 關（crap）還沒啟用：.quality.json 的 gates 沒有 crap", out.getvalue())
        self.assertEqual(data["result"], "skipped")
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

def _mutant(file="a.go", line=5, status="LIVED", mutator="CONDITIONALS_BOUNDARY", text="if total >= 1000 {", **extra):
    return Mutant(file, line, status, mutator, line_text=text, **extra)


def _entry(**extra):
    e = {"file": "a.go", "mutator": "CONDITIONALS_BOUNDARY", "line_text": "if total >= 1000 {",
         "reason": "門檻剛好等於 1000 的那筆，改成 > 結果一樣", "approved_by": "reviewer"}
    e.update(extra)
    return e


class EquivalentChecks(unittest.TestCase):
    def load_text(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "eq.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return equivalents.load(path)

    def test_missing_file_is_empty_list(self):
        self.assertEqual(equivalents.load(os.path.join(tempfile.gettempdir(), "no-such-qe.json")), [])

    def test_valid_entries_load_as_is(self):
        entries = [_entry(), _entry(function="Fee", line_text="x")]
        self.assertEqual(self.load_text(json.dumps(entries)), entries)

    def test_invalid_entries_exit_2_and_name_the_item(self):
        no_reason = _entry()
        del no_reason["reason"]
        cases = [
            ("[1]", "第 1 項必須是物件"),
            (json.dumps([_entry(), no_reason]), "第 2 項缺少必填欄位 reason"),
            (json.dumps([_entry(approved_by="")]), "第 1 項的 approved_by"),
            (json.dumps([_entry(), _entry(extra=1)]), "第 2 項有不認得的鍵：extra"),
            ('{"file": "a.go"}', "最外層必須是陣列"),
            ("[{", "不是合法的 JSON"),
        ]
        for text, expect in cases:
            with self.assertRaises(QualityError) as cm:
                self.load_text(text)
            self.assertEqual(cm.exception.exit_code, 2, text)
            self.assertIn(expect, str(cm.exception), text)

    def test_match_by_file_mutator_and_trimmed_line_text(self):
        hit = _mutant(text="if total >= 1000 {")
        other_mutator = _mutant(mutator="CONDITIONALS_NEGATION")
        other_file = _mutant(file="b.go")
        other_text = _mutant(text="if total >= 999 {")
        moved = _mutant(line=50)  # 行號不同也對得上
        mutants = [hit, other_mutator, other_file, other_text, moved]
        unused = equivalents.apply(mutants, [_entry(line_text="  if total >= 1000 {\t")])
        self.assertEqual([m.status for m in mutants], ["EQUIVALENT", "LIVED", "LIVED", "LIVED", "EQUIVALENT"])
        self.assertEqual(unused, [])

    def test_file_path_is_normalized(self):
        for written in ("./a.go", "a.go", ".\\a.go"):
            m = _mutant()
            unused = equivalents.apply([m], [_entry(file=written)], scope={"a.go"})
            self.assertEqual((m.status, unused), ("EQUIVALENT", []), written)
        entry = _entry(file="./gone.go")
        self.assertEqual(equivalents.apply([_mutant()], [entry], scope={"gone.go"}), [entry])

    def test_unused_only_counts_files_in_scope(self):
        entries = [_entry(), _entry(file="gone.go"), _entry(file="other.go", line_text="x")]
        mutants = [_mutant(text="if total >= 999 {")]
        # 整個專案：兩個檔案的項目都沒用到
        self.assertEqual(len(equivalents.apply(mutants, entries)), 3)
        # --base：只有 a.go 在這次範圍內，gone.go 和 other.go 沒改到，不算
        self.assertEqual(equivalents.apply(mutants, entries, scope={"a.go"}), [entries[0]])

    def test_used_by_mutant_outside_changed_lines(self):
        # --base 時，那一行沒改到，改壞版本被過濾掉了，但清單項目還是對得上，不算沒用到
        universe = [_mutant(line=5), _mutant(line=9, text="y")]
        counted = [universe[1]]
        self.assertEqual(equivalents.apply(counted, [_entry()], universe, {"a.go"}), [])
        self.assertEqual(counted[0].status, "LIVED")

    def test_excluded_mutator_is_not_matched_again(self):
        m = _mutant(status="EXCLUDED_MUTATOR")
        unused = equivalents.apply([m], [_entry()])
        self.assertEqual(m.status, "EXCLUDED_MUTATOR")
        self.assertEqual(len(unused), 1)


class ExcludeMutatorChecks(unittest.TestCase):
    def test_by_name_any_status(self):
        ms = [_mutant(status="LIVED", mutator="A"), _mutant(status="KILLED", mutator="A"),
              _mutant(status="NOT_COVERED", mutator="B")]
        mutation.exclude_mutators(ms, ["A"])
        self.assertEqual([m.status for m in ms], ["EXCLUDED_MUTATOR", "EXCLUDED_MUTATOR", "NOT_COVERED"])

    def test_empty_list_changes_nothing(self):
        ms = [_mutant()]
        mutation.exclude_mutators(ms, [])
        self.assertEqual(ms[0].status, "LIVED")

    def test_excluded_not_counted_in_rates(self):
        ms = [_mutant(status="KILLED"), _mutant(status="LIVED", mutator="A")]
        mutation.exclude_mutators(ms, ["A"])
        c = mutation.count(ms)
        self.assertEqual(c["EXCLUDED_MUTATOR"], 1)
        self.assertEqual(mutation.kill_rate(c), 100.0)


class SettingsChecks(unittest.TestCase):
    def cfg(self, **mutation_settings):
        return config.validate({"version": 2, "language": "go", "mutation": mutation_settings})

    def test_every_language_defaults_keep_v1_behaviour(self):
        for module in (go, csharp, js, python):
            # Python 的逾時預設是 cosmic-ray 一直以來用的 30 秒（同 v1），報告寫的是實際生效的值
            want = {"timeout_seconds": 30 if module is python else None, "workers": None, "exclude_mutators": []}
            self.assertEqual(module.DEFAULTS, want)
            self.assertEqual(module.LANGUAGE().settings(self.cfg()), want)

    def test_settings_take_config_values(self):
        s = go.LANGUAGE().settings(self.cfg(timeout_seconds=90, workers=3, exclude_mutators=["INVERT_LOGICAL"]))
        self.assertEqual(s, {"timeout_seconds": 90, "workers": 3, "exclude_mutators": ["INVERT_LOGICAL"]})

    def test_go_args(self):
        null = go.LANGUAGE().settings(self.cfg())
        args = go.gremlins_args(null, "shipping", "out.json", ["sub.d"])
        self.assertEqual(args, ["unleash", "./shipping", "--timeout-coefficient", "30", "--invert-logical",
                                "-o", "out.json", "-E", "^sub[.]d[^a-zA-Z0-9_.-]"])
        self.assertNotIn("--workers", args)
        with_workers = go.gremlins_args(go.LANGUAGE().settings(self.cfg(workers=3)), "shipping", "out.json")
        self.assertEqual(with_workers[-2:], ["--workers", "3"])

    def test_go_warns_about_timeout_only(self):
        lang = go.LANGUAGE()
        self.assertEqual(lang.unsupported_warnings(lang.settings(self.cfg())), [])
        self.assertEqual(lang.unsupported_warnings(lang.settings(self.cfg(workers=2))), [])
        warnings = lang.unsupported_warnings(lang.settings(self.cfg(timeout_seconds=60)))
        self.assertEqual(len(warnings), 1)
        self.assertIn("timeout_seconds", warnings[0])

    def test_csharp_args_and_config(self):
        lang = csharp.LANGUAGE()
        null = lang.settings(self.cfg())
        base = ["--project", "Shop.csproj", "--reporter", "json", "--output", "/tmp/o", "--skip-version-check"]
        self.assertEqual(csharp.stryker_args(null, "Shop.csproj", "/tmp/o"), base)
        both = lang.settings(self.cfg(timeout_seconds=7.5, workers=2))
        self.assertEqual(csharp.stryker_args(both, "Shop.csproj", "/tmp/o", "/tmp/o/stryker-config.json"),
                         base + ["--config-file", "/tmp/o/stryker-config.json", "--concurrency", "2"])
        self.assertEqual(csharp.stryker_config(both), {"stryker-config": {"additional-timeout": 7500}})
        self.assertEqual(lang.unsupported_warnings(both), [])

    def test_js_options(self):
        lang = js.LANGUAGE()
        base = js.stryker_options("vitest", "r.json", ["a.ts"], lang.settings(self.cfg()))
        self.assertEqual(base, {"testRunner": "vitest", "reporters": ["json"], "jsonReporter": {"fileName": "r.json"},
                                "mutate": ["a.ts"], "coverageAnalysis": "perTest"})
        full = js.stryker_options("jest", "r.json", ["a.js"], lang.settings(
            self.cfg(timeout_seconds=20, workers=2, exclude_mutators=["EqualityOperator"])))
        self.assertEqual(full["timeoutMS"], 20000)
        self.assertEqual(full["concurrency"], 2)
        self.assertEqual(full["mutator"], {"excludedMutations": ["EqualityOperator"]})

    def test_python_config_timeout(self):
        lang = python.LANGUAGE()
        files = ["shop/a.py", "shop/b.py"]
        default = python.cosmic_ray_config(files, "py", lang.settings(self.cfg()))
        self.assertIn("timeout = 30.0", default.splitlines())
        self.assertIn("module-path = ['shop/a.py', 'shop/b.py']", default.splitlines())
        custom = python.cosmic_ray_config(files, "py", lang.settings(self.cfg(timeout_seconds=45)))
        self.assertIn("timeout = 45.0", custom.splitlines())
        self.assertEqual(custom.replace("45.0", "30.0"), default)
        with_workers = python.cosmic_ray_config(files, "py", lang.settings(self.cfg(workers=4)))
        self.assertEqual(with_workers, default)  # workers 不影響設定檔，只印警告
        self.assertEqual(len(lang.unsupported_warnings(lang.settings(self.cfg(workers=4)))), 1)

    def test_python_warns_about_workers_only(self):
        lang = python.LANGUAGE()
        self.assertEqual(lang.unsupported_warnings(lang.settings(self.cfg())), [])
        self.assertEqual(lang.unsupported_warnings(lang.settings(self.cfg(timeout_seconds=60))), [])
        warnings = lang.unsupported_warnings(lang.settings(self.cfg(workers=4)))
        self.assertEqual(len(warnings), 1)
        self.assertIn("workers", warnings[0])


class DescribeChecks(unittest.TestCase):
    def test_gremlins_tokens(self):
        cases = [
            ("CONDITIONALS_BOUNDARY", "\tif total >= 1000 {", 11, (">=", ">")),
            ("CONDITIONALS_BOUNDARY", "if kg > 20 {", 7, (">", ">=")),
            ("CONDITIONALS_NEGATION", "if region == \"x\" {", 11, ("==", "!=")),
            ("ARITHMETIC_BASE", "return a + b", 10, ("+", "-")),
            ("ARITHMETIC_BASE", "return a % b", 10, ("%", "*")),
            ("INVERT_LOGICAL", "if a && b {", 6, ("&&", "||")),
            ("INVERT_BITWISE", "x := a &^ b", 8, ("&^", "&")),
            ("INVERT_BITWISE", "x := a << 2", 8, ("<<", ">>")),
            ("INVERT_BWASSIGN", "x >>= 2", 3, (">>=", "<<=")),
            ("INVERT_ASSIGNMENTS", "x += 2", 3, ("+=", "-=")),
            ("INVERT_ASSIGNMENTS", "x %= 2", 3, ("%=", "%=")),  # gremlins 原始碼就是這樣對應
            ("REMOVE_SELF_ASSIGNMENTS", "x -= 2", 3, ("-=", "=")),
            ("INCREMENT_DECREMENT", "i++", 2, ("++", "--")),
            ("INVERT_LOOPCTRL", "\t\tbreak", 3, ("break", "continue")),
            ("INVERT_NEGATIVES", "y := -x", 6, ("-", "+")),
        ]
        for mutator, line, column, expect in cases:
            self.assertEqual(go.gremlins_describe(mutator, line, column), expect, (mutator, line))

    def test_gremlins_column_counts_bytes(self):
        line = "if s == \"離島\" || total >= 1 {"
        column = len("if s == \"離島\" ".encode("utf-8")) + 1
        self.assertEqual(go.gremlins_describe("INVERT_LOGICAL", line, column), ("||", "&&"))

    def test_gremlins_unknown_gives_none(self):
        self.assertEqual(go.gremlins_describe("NO_SUCH_TYPE", "a + b", 3), (None, None))
        self.assertEqual(go.gremlins_describe("ARITHMETIC_BASE", "a + b", None), (None, None))
        self.assertEqual(go.gremlins_describe("ARITHMETIC_BASE", "a == b", 3), (None, None))
        self.assertEqual(go.gremlins_describe("ARITHMETIC_BASE", "a", 99), (None, None))

    def test_cosmic_ray_operators(self):
        f = python.cosmic_ray_replacement
        self.assertEqual(f("ReplaceBinaryOperator_Add_Sub", 0, "+"), "-")
        self.assertEqual(f("ReplaceBinaryOperator_FloorDiv_Pow", 0, "//"), "**")
        self.assertEqual(f("ReplaceComparisonOperator_GtE_Gt", 0, ">="), ">")
        self.assertEqual(f("ReplaceComparisonOperator_Eq_IsNot", 0, "=="), "is not")
        self.assertEqual(f("ReplaceUnaryOperator_USub_UAdd", 0, "-"), "+")
        self.assertEqual(f("ReplaceUnaryOperator_Invert_Not", 0, "~"), "not")
        self.assertEqual(f("ReplaceUnaryOperator_Delete_Not", 0, "not"), "")
        self.assertEqual(f("ReplaceTrueWithFalse", 0, "True"), "False")
        self.assertEqual(f("ReplaceAndWithOr", 0, "and"), "or")
        self.assertEqual(f("ReplaceBreakWithContinue", 0, "break"), "continue")
        self.assertEqual(f("ExceptionReplacer", 0, "OSError"), "CosmicRayTestingException")
        self.assertEqual(f("ZeroIterationForLoop", 0, "range(3)"), "[]")
        self.assertEqual(f("RemoveDecorator", 0, "@cache"), "")
        self.assertEqual(f("AddNot", 0, "x > 1"), "not x > 1")

    def test_cosmic_ray_numbers(self):
        f = python.cosmic_ray_replacement
        self.assertEqual(f("NumberReplacer", 0, "1000"), "1001")
        self.assertEqual(f("NumberReplacer", 1, "1000"), "999")
        self.assertEqual(f("NumberReplacer", 0, "4.2"), "5.2")
        self.assertEqual(f("NumberReplacer", 1, "0x10"), "15")
        # occurrence 是整個模組一路數下去：a = 5 / b = 7 的第 2、3 個是 b 的 +1、-1
        self.assertEqual([f("NumberReplacer", i, "5") for i in (0, 1)], ["6", "4"])
        self.assertEqual(f("NumberReplacer", 2, "7"), "8")
        self.assertEqual(f("NumberReplacer", 3, "7"), "6")
        self.assertEqual(f("NumberReplacer", 0, "1j"), "(1+1j)")
        self.assertIsNone(f("NumberReplacer", -1, "1"))
        self.assertIsNone(f("NumberReplacer", 0, "not a number"))

    def test_cosmic_ray_unknown_gives_none(self):
        f = python.cosmic_ray_replacement
        for name in ("VariableReplacer", "VariableInserter", "NoOp", "ReplaceBinaryOperator_Add_Nope", "Whatever"):
            self.assertIsNone(f(name, 0, "x"), name)
        self.assertIsNone(f("AddNot", 0, None))
        self.assertIsNone(f("AddNot", 0, "foo(…"))

    def test_describe_text(self):
        self.assertEqual(mutation.describe(_mutant(original=">=", replacement=">")), "把 `>=` 改成 `>`")
        self.assertEqual(mutation.describe(_mutant(original="not", replacement="")), "把 `not` 刪掉")
        self.assertEqual(mutation.describe(_mutant()), "改法 CONDITIONALS_BOUNDARY")
        self.assertEqual(mutation.describe(_mutant(original=">=", replacement=None)), "改法 CONDITIONALS_BOUNDARY")
        self.assertEqual(mutation.describe(_mutant(original="{…", replacement="{}")), "把 `{…` 改成 `{}`")

    def test_mutation_text_lines(self):
        cfg = config.validate({"version": 2, "language": "go"})
        mutants = [_mutant(original=">=", replacement=">"), _mutant(line=9, status="NOT_COVERED", text="return 60"),
                   _mutant(line=12, status="KILLED")]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            report.print_mutation_result(mutants, mutation.count(mutants), cfg, go.LANGUAGE().settings(cfg))
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0], "沒抓到  a.go:5  把 `>=` 改成 `>`  ｜ if total >= 1000 {")
        self.assertEqual(lines[1], "測試沒跑到  a.go:9  改法 CONDITIONALS_BOUNDARY  ｜ return 60")
        self.assertIn("設定：逾時 工具預設、同時跑 工具預設、排除改法 無", lines)

    def test_excluded_and_unused_are_printed(self):
        cfg = config.validate({"version": 2, "language": "go"})
        mutants = [_mutant(status="EQUIVALENT"), _mutant(status="EXCLUDED_MUTATOR")]
        out = io.StringIO()
        settings = {"timeout_seconds": 60, "workers": 2, "exclude_mutators": ["A", "B"]}
        with contextlib.redirect_stdout(out):
            report.print_mutation_result(mutants, mutation.count(mutants), cfg, settings, [_entry()])
        text = out.getvalue()
        self.assertIn("已排除：改了也沒差 1", text)
        self.assertIn("已排除：設定排除的改法 1", text)
        self.assertIn("設定：逾時 60 秒、同時跑 2、排除改法 A、B", text)
        self.assertIn("排除清單有 1 項沒用到", text)

    def test_span_text_and_location_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.cs")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("﻿    if (total >= 1000)\n    {\n        return 0;\n    }\n")
            mutation._source_cache.clear()

            def loc(sl, sc, el, ec):
                return {"start": {"line": sl, "column": sc}, "end": {"line": el, "column": ec}}

            self.assertEqual(mutation.location_text(path, loc(1, 9, 1, 22)), "total >= 1000")  # 欄位從 1 起算，end 不含
            self.assertEqual(mutation.location_text(path, loc(2, 5, 4, 6)), "{…")  # 跨行：第一行加「…」
            self.assertEqual(mutation.span_text(path, (3, 8), (4, 0)), "return 0;")  # 結尾在下一行行首
            self.assertIsNone(mutation.location_text(path, loc(99, 1, 99, 2)))
            self.assertIsNone(mutation.location_text(path, {}))
            self.assertIsNone(mutation.location_text(os.path.join(tmp, "missing.cs"), loc(1, 1, 1, 2)))
            mutation._source_cache.clear()


if __name__ == "__main__":
    unittest.main()
