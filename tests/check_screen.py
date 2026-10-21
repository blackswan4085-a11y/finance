"""Regression checks for failed collection, genuine zero matches and port reuse.

python tests/check_screen.py — isolated data; no external network requests.
"""
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from screener.config import Config
from screener.screen import run_screen
from screener.screen_cache import publish_screen_cache, read_screen_cache
from screener.server import FinanceHTTPServer, serve
from screener.universe import build_universe


class ScreenChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="screen-check-")
        self.folder = Path(self.temp.name)
        self.cfg = Config(base_dir=str(self.folder), markets=["NYSE"])
        self.asof = date(2026, 10, 16)
        self.universe = pd.DataFrame([{"symbol": "TEST", "name": "Test company", "market": "NYSE", "country": "US",
                                       "currency": "USD", "asset_type": "STOCK", "sector": "", "marketcap": 1e9}])
        index = pd.bdate_range("2024-01-01", self.asof)
        close = pd.Series(range(1, len(index) + 1), index=index, dtype=float)
        self.prices = pd.DataFrame({"Open": close, "High": close + .5, "Low": close - .5, "Close": close, "Volume": 1000})

    def tearDown(self):
        self.temp.cleanup()

    def screen(self, data, universe=None):
        with patch("screener.screen.build_universe", return_value=self.universe if universe is None else universe), \
             patch("screener.screen.download_all", return_value=data):
            return run_screen(self.cfg, self.asof)

    def test_failed_and_empty_market_listing_is_an_error(self):
        with patch("screener.universe.fdr.StockListing", side_effect=ConnectionError("blocked")):
            with self.assertRaisesRegex(RuntimeError, "NYSE"):
                build_universe(["NYSE"])
        with patch("screener.universe.fdr.StockListing", return_value=pd.DataFrame()):
            with self.assertRaisesRegex(RuntimeError, "NYSE"):
                build_universe(["NYSE"])

    def test_partial_market_failure_is_not_a_complete_scan(self):
        raw = pd.DataFrame([{"Symbol": "TEST", "Name": "Test"}])
        with patch("screener.universe.fdr.StockListing", side_effect=[raw, ConnectionError("NYSE failed")]), \
             patch("screener.universe._load_us_marketcap", return_value={}):
            with self.assertRaisesRegex(RuntimeError, "NYSE"):
                build_universe(["NASDAQ", "NYSE"])

    def test_no_universe_or_prices_cannot_mean_zero_matches(self):
        with self.assertRaisesRegex(RuntimeError, "종목 목록"):
            self.screen({}, pd.DataFrame(columns=self.universe.columns))
        with self.assertRaisesRegex(RuntimeError, "주가 데이터"):
            self.screen({})

    def test_stale_cache_is_not_published_as_current_week(self):
        stale = self.prices.loc[:"2026-10-09"]
        with self.assertRaisesRegex(RuntimeError, "이전 주 캐시"):
            self.screen({"TEST": stale})

    def test_missing_market_prices_fail_even_if_another_market_worked(self):
        extra = dict(self.universe.iloc[0], symbol="005930", market="KOSPI", country="KR", currency="KRW")
        universe = pd.concat([self.universe, pd.DataFrame([extra])], ignore_index=True)
        with self.assertRaisesRegex(RuntimeError, "KOSPI"):
            self.screen({"TEST": self.prices}, universe)

    def test_valid_scan_publishes_with_evaluation_counts(self):
        result = self.screen({"TEST": self.prices})
        self.assertEqual(len(result), 1)
        saved = publish_screen_cache(self.folder / "screen_cache.json", result, self.asof)
        self.assertEqual(saved["scan"]["evaluated_count"], 1)
        self.assertEqual(saved["rows"][0]["symbol"], "TEST")

    def test_true_zero_matches_and_liquidity_filter_are_valid(self):
        declining = self.prices.iloc[::-1].copy()
        declining.index = self.prices.index
        result = self.screen({"TEST": declining})
        self.assertTrue(result.empty)
        self.assertEqual(result.attrs["scan"]["evaluated_count"], 1)
        saved = publish_screen_cache(self.folder / "screen_cache.json", result, self.asof)
        self.assertEqual(saved["rows"], [])
        self.assertEqual(read_screen_cache(self.folder / "screen_cache.json"), saved)
        self.cfg.min_avg_dollar_volume = 1e30
        self.assertTrue(self.screen({"TEST": self.prices}).empty)

    def test_failed_publish_preserves_cache_and_success_keeps_backup(self):
        path = self.folder / "screen_cache.json"
        previous = {"asof_date": "2026-10-09", "generated_at": "before", "rows": [{"symbol": "OLD"}]}
        path.write_text(json.dumps(previous), encoding="utf-8")
        before = path.read_bytes()
        with self.assertRaises(RuntimeError):
            publish_screen_cache(path, pd.DataFrame(), self.asof)
        self.assertEqual(path.read_bytes(), before)
        publish_screen_cache(path, self.screen({"TEST": self.prices}), self.asof)
        self.assertEqual(json.loads((self.folder / "screen_cache.previous.json").read_text(encoding="utf-8")), previous)
        path.write_text('{"asof_date":"2026-10-16","rows":[]}', encoding="utf-8")
        self.assertEqual(read_screen_cache(path), previous)

    def test_exclusive_binding_prevents_two_finance_servers(self):
        server = FinanceHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        try:
            with self.assertRaises(OSError):
                another = ThreadingHTTPServer(server.server_address, BaseHTTPRequestHandler)
                another.server_close()
        finally:
            server.server_close()

    def test_new_server_detects_a_legacy_server_using_the_port(self):
        legacy = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        try:
            with self.assertRaises(OSError):
                another = FinanceHTTPServer(legacy.server_address, BaseHTTPRequestHandler)
                another.server_close()
        finally:
            legacy.server_close()

    def test_duplicate_start_does_not_touch_the_active_workspace(self):
        legacy = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        self.cfg.port = legacy.server_address[1]
        try:
            with patch("screener.server.ensure_dataset") as dataset, patch("screener.server.EarningsService") as earnings:
                with self.assertRaises(OSError):
                    serve(None, self.cfg)
                dataset.assert_not_called()
                earnings.assert_not_called()
        finally:
            legacy.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
