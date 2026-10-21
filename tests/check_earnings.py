"""Regression checks for source preservation, collection jobs and real rendering.

Run from finance: python tests/check_earnings.py
Uses synthetic data in an isolated workspace; never calls the live AI CLI.
"""
from pathlib import Path
import copy
import hashlib
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from screener.earnings import EarningsService, EarningsConflict, _read, _write
from screener.earnings_financials import manual_financials, number


class EarningsChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="earnings-check-")
        self.market_patch = patch("screener.earnings.market_snapshot", return_value={
            "sourceId": "market_snapshot", "symbol": "TEST", "currency": "USD",
            "price": None, "marketCap": None, "asOf": None,
            "collectedAt": "2026-10-17T00:00:00", "history": [], "historySource": "test fixture",
            "splitSinceReport": False, "notes": ["테스트 전용 가상 시장 자료"]
        })
        self.market_patch.start()
        self.addCleanup(self.market_patch.stop)
        self.directory = Path(self.temp.name)
        self.root = self.directory / "earnings"
        self.ident = "TEST_FY2026Q3"
        shutil.copytree(BASE / "earnings" / "earnings-template", self.root / "earnings-template",
                        ignore=shutil.ignore_patterns(".runtime", "__pycache__"))
        report = self.root / "결과" / self.ident
        report.mkdir(parents=True)
        shutil.copyfile(BASE / "tests" / "fixtures" / "earnings.json", report / "input.snapshot.json")
        # Exercise production validation with synthetic values only inside this temporary workspace.
        snapshot = _read(report / "input.snapshot.json")
        snapshot["company"]["isSample"] = False
        _write(report / "input.snapshot.json", snapshot)
        from PIL import Image
        Image.new("RGB", (1, 1), "white").save(report / "report-01.png")
        (report / "report.html").write_text("<!doctype html><title>Test fixture</title>", encoding="utf-8")
        _write(report / "render-manifest.json", {"files": [{"file": "report-01.png"}]})
        raw = self.root / "자료" / self.ident
        raw.mkdir(parents=True)
        (raw / "컨콜.txt").write_text("기존 컨콜 원문", encoding="utf-8")
        (raw / "컨센서스.txt").write_text("기존 컨센서스 원문", encoding="utf-8")
        self.service = EarningsService(self.directory / "finance", {"source_dir": str(self.root)})
        self.snapshot = _read(self.root / "결과" / self.ident / "input.snapshot.json")
        self.financials = {key: copy.deepcopy(self.snapshot[key]) for key in
                           ("schemaVersion", "company", "sources", "quarters", "annuals", "reportPeriod")}
        self.financials.update(consensus=None, conferenceCall=None, callMetrics=[], guidance=[])

    def tearDown(self):
        self.temp.cleanup()

    def empty_inputs(self):
        return {"transcript": "", "consensus": "", "notes": "", "consensus_basis": "미확인", "consensus_asof": ""}

    def wait_job(self):
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            project = self.service.get(self.ident)
            if project["job"]["state"] != "running":
                return project
            time.sleep(.05)
        self.fail("Background job timed out")

    def test_import_save_preserves_sources_and_detects_conflicts(self):
        before = self.service.get(self.ident)
        self.assertTrue(before["has_report"])
        self.assertFalse(before["report_stale"])
        self.assertEqual(before["inputs"]["transcript"], "기존 컨콜 원문")
        inputs = self.empty_inputs()
        inputs["transcript"] = "대시보드에서 새로 입력한 컨콜"
        saved = self.service.save(self.ident, {"revision": 0, "inputs": inputs})
        self.assertTrue(saved["report_stale"])
        self.assertEqual(saved["revision"], 1)
        self.assertEqual((self.root / "자료" / self.ident / "컨콜.txt").read_text(encoding="utf-8"), "기존 컨콜 원문")
        self.assertEqual((self.root / saved["source_revision"] / "컨콜.txt").read_text(encoding="utf-8"), inputs["transcript"])
        with self.assertRaises(EarningsConflict):
            self.service.save(self.ident, {"revision": 0, "inputs": self.empty_inputs()})
        restarted = EarningsService(self.directory / "finance", {"source_dir": str(self.root)})
        self.assertEqual(restarted.get(self.ident)["inputs"],
                         {key: inputs[key] for key in ("transcript", "notes")})

    def test_generation_locks_edits_and_failure_preserves_previous_result(self):
        entered, release = threading.Event(), threading.Event()
        def extract(*args):
            entered.set()
            release.wait(5)
            return {"error": "Test extraction failure"}
        with patch.object(self.service, "_cli", side_effect=extract):
            result = self.service.start(self.ident, "generate", {"revision": 0})
            self.assertEqual(result["job"]["state"], "running")
            self.assertTrue(entered.wait(5))
            with self.assertRaises(EarningsConflict):
                self.service.save(self.ident, {"revision": 0, "inputs": self.empty_inputs()})
            release.set()
            failed = self.wait_job()
        self.assertEqual(failed["job"]["state"], "error")
        self.assertTrue(failed["has_report"])
        self.assertEqual(failed["report_version"], "")

    def test_cleared_manual_inputs_render_without_reusing_old_call_or_consensus(self):
        original_image = self.root / "결과" / self.ident / "report-01.png"
        before = hashlib.sha256(original_image.read_bytes()).hexdigest()
        self.service.save(self.ident, {"revision": 0, "inputs": self.empty_inputs()})
        with patch.object(self.service, "_cli", side_effect=AssertionError("No CLI needed for financials-only reports")):
            self.service.start(self.ident, "generate", {"revision": 1})
            result = self.wait_job()
        self.assertEqual(result["job"]["state"], "done", result["job"])
        self.assertTrue(result["has_report"])
        self.assertFalse(result["report_stale"])
        generated = _read(self.service.artifact(self.ident, "input.snapshot.json"))
        self.assertEqual(generated["quarters"], self.financials["quarters"])
        self.assertIsNone(generated["consensus"])
        self.assertIsNone(generated["conferenceCall"])
        self.assertEqual(generated["callMetrics"], [])
        self.assertEqual(generated["guidance"], [])
        self.assertEqual(hashlib.sha256(original_image.read_bytes()).hexdigest(), before)
        self.assertEqual(self.service.artifact(self.ident, "report-01.png", "original"), original_image)
        from PIL import Image
        with Image.open(self.service.artifact(self.ident, result["files"][0])) as image:
            self.assertEqual(image.size, (2880, 3880))

    def test_web_collection_is_disabled_without_starting_ai(self):
        with patch.object(self.service, "_cli") as cli:
            with self.assertRaisesRegex(ValueError, "실적 표"):
                self.service.start(self.ident, "fetch", {"revision": 0})
        cli.assert_not_called()
        result = self.service.get(self.ident)
        self.assertEqual(result["job"]["state"], "idle")
        self.assertTrue(result["has_report"])

    def test_wrong_company_period_and_paths_are_rejected(self):
        run = self.directory / "validation"
        run.mkdir()
        project = self.service.get(self.ident)
        wrong = copy.deepcopy(self.financials)
        wrong["company"]["ticker"] = "UNH"
        with self.assertRaisesRegex(ValueError, "티커"):
            self.service._check(wrong, project, run)
        wrong = copy.deepcopy(self.financials)
        wrong["quarters"].append(dict(wrong["quarters"][-1], year=2027))
        with self.assertRaisesRegex(ValueError, "회계분기"):
            self.service._check(wrong, project, run)
        for ident, filename, version in [("..", "report.html", ""), (self.ident, "../AGENTS.md", ""), (self.ident, "report.html", "../")]:
            with self.assertRaises(ValueError):
                self.service.artifact(ident, filename, version)
        with self.assertRaises(ValueError):
            self.service.create({"ticker": "A&B", "year": 2026, "quarter": 3})

    def test_manual_extraction_cannot_change_collected_financials(self):
        project = self.service.get(self.ident)
        altered = copy.deepcopy(self.snapshot)
        altered["quarters"][0]["revenue"] += 1
        with patch.object(self.service, "_cli", return_value=altered) as cli:
            self.service.start(self.ident, "generate", {"revision": 0})
            result = self.wait_job()
        self.assertEqual(result["job"]["state"], "error")
        self.assertIn("저장된 실적이 변경", result["job"]["message"])
        self.assertTrue(result["has_report"])
        self.assertEqual(result["report_version"], project["report_version"])
        self.assertIn("기존 컨콜 원문", cli.call_args.args[0])

    def test_cli_arguments_and_unicode_prompt_do_not_use_shell_interpolation(self):
        output = self.directory / "response.json"
        _write(output, {"ok": True})
        with patch("screener.earnings.subprocess.Popen") as popen:
            popen.return_value.communicate.return_value = (None, "")
            popen.return_value.returncode = 0
            result = self.service._cli("한글 원문\n$() & `arbitrary`", output)
        self.assertTrue(result["ok"])
        args = popen.call_args.args[0]
        self.assertNotIn("--search", args)
        self.assertIn('web_search="disabled"', args)
        self.assertIn("--output-last-message", args)
        self.assertEqual(args[-1], "-")
        self.assertNotIn("shell", popen.call_args.kwargs)
        self.assertEqual(popen.return_value.communicate.call_args.args[0], "한글 원문\n$() & `arbitrary`")

    def test_interrupted_jobs_can_be_retried_after_restart(self):
        project = self.service.get(self.ident)
        project["job"] = {"state": "running", "action": "fetch"}
        project.pop("financials", None)
        _write(self.service._path(self.ident), project)
        restarted = EarningsService(self.directory / "finance", {"source_dir": str(self.root)})
        result = restarted.get(self.ident)
        self.assertEqual(result["job"]["state"], "error")
        self.assertIn("재시작", result["job"]["message"])

    def manual_table(self):
        return {"company": copy.deepcopy(self.financials["company"]),
                "reportPeriod": copy.deepcopy(self.financials["reportPeriod"]),
                "quarters": copy.deepcopy(self.financials["quarters"]),
                "annuals": copy.deepcopy(self.financials["annuals"])}

    def test_manual_table_save_never_calls_ai_and_preserves_values_on_restart(self):
        table = self.manual_table()
        table["quarters"][-1].update(revenue="0", operatingIncome="(1,234.50)", eps="")
        with patch.object(self.service, "_cli", side_effect=AssertionError("Saving numbers must not use AI")) as cli:
            saved = self.service.save(self.ident, {"revision": 0, "inputs": self.empty_inputs(), "financials": table})
        cli.assert_not_called()
        latest = saved["financials"]["quarters"][-1]
        self.assertEqual(latest["revenue"], 0)
        self.assertEqual(latest["operatingIncome"], -1234.5)
        self.assertIsNone(latest["eps"])
        self.assertTrue(saved["financials_editable"])
        self.assertTrue(saved["report_stale"])
        archive = self.root / saved["source_revision"] / "실적입력.json"
        self.assertTrue(archive.is_file())
        restarted = EarningsService(self.directory / "finance", {"source_dir": str(self.root)})
        self.assertEqual(restarted.get(self.ident)["financials"], saved["financials"])
        again = restarted.save(self.ident, {"revision": 1, "inputs": self.empty_inputs(), "financials": table})
        self.assertEqual(again["revision"], 1, "Re-saving identical cells must not create a new revision")

    def test_financials_only_manual_table_renders_without_ai(self):
        table = self.manual_table()
        table["quarters"][-1]["revenue"] = "12,345"
        table["quarters"][-1]["eps"] = "0"
        with patch.object(self.service, "_cli", side_effect=AssertionError("Manual financials require no AI")):
            saved = self.service.save(self.ident, {"revision": 0, "inputs": self.empty_inputs(), "financials": table})
            self.service.start(self.ident, "generate", {"revision": saved["revision"]})
            result = self.wait_job()
        self.assertEqual(result["job"]["state"], "done", result["job"])
        generated = _read(self.service.artifact(self.ident, "input.snapshot.json"))
        self.assertEqual(generated["quarters"][-1]["revenue"], 12345)
        self.assertEqual(generated["quarters"][-1]["eps"], 0)
        self.assertEqual(generated["quarters"][-1]["sourceId"], "dashboard_financials")

    def test_incomplete_tables_are_saved_as_drafts_without_inventing_dates(self):
        table = self.manual_table()
        table["reportPeriod"] = {"start": "", "end": ""}
        table["quarters"] = [{"year": 2026, "quarter": 3, "revenue": "", "operatingIncome": "", "eps": ""}]
        saved = self.service.save(self.ident, {"revision": 0, "inputs": self.empty_inputs(), "financials": table})
        self.assertFalse(saved["financials_available"])
        self.assertEqual(saved["financials"]["quarters"], [])
        self.assertEqual(saved["financials"]["reportPeriod"]["start"], "")
        with self.assertRaisesRegex(ValueError, "보고 기간"):
            self.service.start(self.ident, "generate", {"revision": 1})

    def test_bad_manual_cells_do_not_overwrite_saved_material(self):
        project = self.service.get(self.ident)
        bad_tables = []
        table = self.manual_table(); table["quarters"][-1]["revenue"] = "1.2.3"; bad_tables.append(table)
        table = self.manual_table(); table["quarters"].append(copy.deepcopy(table["quarters"][-1])); bad_tables.append(table)
        table = self.manual_table(); table["quarters"][-1]["quarter"] = 4; bad_tables.append(table)
        table = self.manual_table(); table["annuals"][-1]["year"] = 2026; bad_tables.append(table)
        table = self.manual_table(); table["reportPeriod"]["start"] = "2026-02-30"; bad_tables.append(table)
        table = self.manual_table(); table["reportPeriod"]["start"] = "2026-12-31"; bad_tables.append(table)
        for table in bad_tables:
            with self.assertRaises(ValueError):
                self.service.save(self.ident, {"revision": 0, "inputs": self.empty_inputs(), "financials": table})
            self.assertEqual(self.service.get(self.ident)["revision"], project["revision"])
            self.assertEqual(self.service.get(self.ident)["inputs"], project["inputs"])

    def test_numeric_cells_distinguish_missing_zero_and_invalid_values(self):
        for raw, expected in [("", None), ("—", None), ("N/A", None), ("0", 0), ("1,234.50", 1234.5), ("(2.5)", -2.5), ("−2", -2), ("1e3", 1000)]:
            self.assertEqual(number(raw, "test"), expected)
        for raw in ["=1+2", "1.2.3", "12,34", "1e999", float("nan"), float("inf"), True]:
            with self.assertRaises(ValueError):
                number(raw, "test")


if __name__ == "__main__":
    unittest.main(verbosity=2)
