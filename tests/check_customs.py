"""Isolated integration checks. Never calls the live Customs API.

Run: python tests/check_customs.py
"""
from contextlib import closing, ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from screener.customs import db, collector
from screener.customs.report import build_static, page_html
from screener.customs.service import CustomsService


def row(period, code="8542320000", exp=100):
    return dict(period=period, hs_code=code, item_name="반도체", exp_dlr=exp,
                imp_dlr=80, exp_wgt=1, imp_wgt=1, bal_pay=exp - 80)


class CustomsChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="finance-customs-")
        self.root = Path(self.temp.name)
        self.source = self.root / "old"
        self.source_db = self.source / "data/trade.db"
        self.source_db.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.source_db)) as conn:
            db.ensure_schema(conn)
            collector.save_rows(conn, [row("202501"), row("202601", exp=150),
                                      row("202601", "8703230000", exp=20),
                                      row("202602", exp=200), row("202603", exp=250)])
            db.add_company(conn, "85", 2, "기존 기업", "기존 메모", "2026-01-01")
            conn.execute("INSERT INTO collection_meta VALUES ('latest_month','202603')")
            conn.commit()
        self.base = self.root / "finance"
        self.base.mkdir()
        self.settings = {"source_dir": str(self.source), "months": 3, "api_key": "test-secret-key"}
        self.service = CustomsService(self.base, self.settings)

    def tearDown(self):
        self.temp.cleanup()

    def test_local_workspace_needs_no_legacy_source(self):
        (self.base / ".env").write_text("CUSTOMS_API_KEY=local-test-key\n", encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            service = CustomsService(self.base)
            self.assertIsNone(service.source)
            self.assertEqual(service.api_key(), "local-test-key")
            self.assertEqual(service.get("meta")["latest_month"], "")
        self.assertTrue((self.base / "customs_workspace/trade.db").is_file())

    def digest(self):
        return hashlib.sha256(self.source_db.read_bytes()).hexdigest()

    def wait_job(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = self.service.get("collect/status")
            if not status["running"]:
                return status
            time.sleep(.01)
        self.fail("Collection job did not finish")

    def test_import_preserves_source_and_never_overwrites_finance(self):
        before = self.digest()
        self.assertEqual(self.service.get("meta")["latest_month"], "202603")
        self.assertEqual(self.service.get("detail", {"code": ["85"]})["companies"][0]["company"], "기존 기업")
        self.service.post("company/add", {"hs_code": "85", "hs_level": 2, "company": "추가 기업"})
        reopened = CustomsService(self.base, self.settings)
        self.assertEqual(len(reopened.get("detail", {"code": ["85"]})["companies"]), 2)
        self.assertEqual(self.digest(), before)
        # Copied code and database continue to work without the original project.
        self.source_db.rename(self.source_db.with_suffix(".backup"))
        self.assertEqual(reopened.get("overview")["totals"]["exp_dlr"], 250)

    def test_empty_install_and_hs_drilldown(self):
        empty = CustomsService(self.root / "empty", {"source_dir": str(self.root / "absent")})
        self.assertEqual(empty.get("overview")["series"], [])
        self.assertEqual(empty.get("names", {"level": ["6"]}), {})
        for level, code, expected in [(2, "", "85"), (4, "85", "8542"), (6, "8542", "854232")]:
            result = self.service.get("level", {"code": [code], "level": [str(level)]})
            self.assertEqual(result[0]["code"], expected)
            self.assertEqual(result[0]["exp_dlr"], 250)
        detail = self.service.get("detail", {"code": ["854232"]})
        self.assertAlmostEqual(detail["expYoy"][1]["yoy"], 50)

    def test_validation_and_related_company_roundtrip(self):
        for query in ({"level": ["3"]}, {"level": ["2);DROP TABLE trade_raw;--"]},
                      {"code": ["85%"], "level": ["4"]}, {"code": ["85"], "level": ["6"]}):
            with self.assertRaises(ValueError):
                self.service.get("level", query)
        with self.assertRaises(ValueError):
            self.service.post("company/add", {"hs_code": "85", "hs_level": 4, "company": "기업"})
        self.service.post("company/add", {"hs_code": "8542", "hs_level": 4, "company": " <기업> ", "note": "메모"})
        saved = self.service.get("detail", {"code": ["8542"]})["companies"]
        self.assertEqual(saved[0]["company"], "<기업>")
        self.service.post("company/delete", {"id": saved[0]["id"]})
        self.assertEqual(self.service.get("detail", {"code": ["8542"]})["companies"], [])

    def test_credentials_fallback_without_copying_secrets(self):
        settings = {"source_dir": str(self.source)}
        (self.source / ".env").write_text("CUSTOMS_API_KEY='legacy-secret'", encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            service = CustomsService(self.base, settings)
            self.assertEqual(service.api_key(), "legacy-secret")
            (self.base / ".env").write_text('CUSTOMS_API_KEY="local-secret"', encoding="utf-8")
            self.assertEqual(service.api_key(), "local-secret")
            with patch.dict(os.environ, {"CUSTOMS_API_KEY": "environment-secret"}):
                self.assertEqual(service.api_key(), "environment-secret")
            (self.base / ".env").unlink()
            (self.source / ".env").unlink()
            with self.assertRaisesRegex(ValueError, "CUSTOMS_API_KEY"):
                service.start_collection()
        self.assertFalse((self.base / "customs_workspace/.env").exists())

    def test_incremental_collection_respects_months_and_replaces_revised_month(self):
        self.service.ensure_ready()
        with closing(sqlite3.connect(self.service.path)) as conn:
            conn.execute("DELETE FROM trade_raw WHERE period='202602'")
            collector.save_rows(conn, [row("202603", "9999999999", exp=1000)])
        fetched = []
        def fetch(key, period):
            self.assertEqual(key, "explicit-key")
            fetched.append(period)
            return "00", [row(period, exp=300)]
        with patch.object(collector, "detect_latest_month", return_value="202603"), \
             patch.object(collector, "fetch_month", side_effect=fetch), \
             patch.object(collector.time, "sleep"):
            result = collector.run_collection(db_path=str(self.service.path), api_key="explicit-key", months=3)
        self.assertEqual(fetched, ["202602", "202603"])
        self.assertEqual(result["months_fetched"], 2)
        self.assertEqual(self.service.get("overview")["totals"]["exp_dlr"], 300)

    def test_failed_collection_preserves_existing_latest_month(self):
        self.service.ensure_ready()
        with patch.object(collector, "detect_latest_month", return_value="202603"), \
             patch.object(collector, "fetch_month", return_value=("00", [])):
            with self.assertRaises(RuntimeError):
                collector.run_collection(db_path=str(self.service.path), api_key="test", months=1)
        self.assertEqual(self.service.get("overview")["totals"]["exp_dlr"], 250)

    def test_background_deduplication_persistence_and_error_redaction(self):
        entered, release = threading.Event(), threading.Event()
        def collect(**kwargs):
            self.assertEqual(kwargs["months"], 3)
            self.assertEqual(kwargs["api_key"], "test-secret-key")
            entered.set()
            release.wait(3)
            return {"latest_month": "202603", "months_fetched": 1, "total_rows": 5}
        with patch.object(collector, "run_collection", side_effect=collect) as run:
            self.service.start_collection()
            self.assertTrue(entered.wait(2))
            self.service.start_collection()
            self.assertEqual(run.call_count, 1)
            release.set()
            self.assertEqual(self.wait_job()["phase"], "done")
        reopened = CustomsService(self.base, self.settings)
        self.assertEqual(reopened.get("collect/status")["phase"], "done")
        with patch.object(collector, "run_collection", side_effect=RuntimeError("serviceKey=test-secret-key&fail")):
            self.service.start_collection()
            self.assertEqual(self.wait_job()["phase"], "error")
        self.assertNotIn("test-secret-key", self.service.state_path.read_text(encoding="utf-8"))

    def test_interrupted_job_is_retryable(self):
        self.service.workspace.mkdir(parents=True)
        self.service.state_path.write_text('{"running":true,"phase":"month"}', encoding="utf-8")
        service = CustomsService(self.base, self.settings)
        self.assertFalse(service.get("collect/status")["running"])
        self.assertEqual(service.get("collect/status")["phase"], "error")

    def test_offline_export_escapes_script_payloads(self):
        self.service.ensure_ready()
        with closing(db.connect(str(self.service.path))) as conn:
            conn.execute("UPDATE trade_raw SET item_name=?", ('</script><script>alert(1)</script>',))
            conn.commit()
            html = build_static(conn, self.service.get("meta"))
        self.assertIn("const STATIC = true", html)
        self.assertIn("finance-theme", html)
        self.assertNotIn("</script><script>alert(1)", html)
        self.assertIn("수출입 통계", page_html({}))

    def test_finance_http_routes_and_json_errors(self):
        from screener.config import Config
        from screener import server
        shutil.copytree(BASE / "web", self.base / "web")
        ready = threading.Event()
        servers = []
        original_server = server.FinanceHTTPServer
        class TestServer(original_server):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                servers.append(self)
            def serve_forever(self, *args, **kwargs):
                ready.set()
                return super().serve_forever(*args, **kwargs)
        cfg = Config(base_dir=str(self.base), port=0, auto_open=False, customs=self.settings)
        with ExitStack() as stack:
            stack.enter_context(patch.object(server, "FinanceHTTPServer", TestServer))
            stack.enter_context(patch.object(server, "ensure_dataset"))
            industry = stack.enter_context(patch("screener.report.IndustryStore"))
            industry.return_value.catalogue.return_value = {}
            instrument = stack.enter_context(patch.object(server, "InstrumentStore"))
            instrument.return_value.counts.return_value = {}
            worker = threading.Thread(target=server.serve, args=(None, cfg), daemon=True)
            worker.start()
            self.assertTrue(ready.wait(5))
            origin = f"http://127.0.0.1:{servers[0].server_port}"
            def request(path, payload=None, headers=None):
                data = json.dumps(payload).encode() if payload is not None else None
                req = Request(origin + path, data=data, headers=headers or ({"Content-Type": "application/json"} if data else {}))
                try:
                    with urlopen(req, timeout=10) as response:
                        return response.status, response.read().decode()
                except HTTPError as exc:
                    return exc.code, exc.read().decode()
            try:
                for path in ("/", "/weekly", "/customs", "/customs/", "/ui.js", "/api/customs/overview", "/api/customs/collect/status"):
                    self.assertEqual(request(path)[0], 200, path)
                self.assertEqual(request("/api/customs/names?level=3")[0], 400)
                self.assertEqual(request("/api/customs/unknown")[0], 404)
                self.assertEqual(request("/api/customs/company/add", [1, 2])[0], 400)
                payload = {"hs_code": "85", "hs_level": 2, "company": "HTTP 기업"}
                self.assertEqual(request("/api/customs/company/add", payload, {"Content-Type": "application/json", "Origin": "https://other.example"})[0], 403)
                self.assertEqual(request("/api/customs/company/add", payload)[0], 200)
                self.assertIn("HTTP 기업", request("/api/customs/detail?code=85")[1])
            finally:
                servers[0].shutdown()
                worker.join(5)
                servers[0].server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
