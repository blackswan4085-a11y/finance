"""Check shared KUIM data without personal DBs, caches or review files."""
from pathlib import Path
import json
import shutil
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener.config import Config
from screener.industry import IndustryStore, ensure_dataset
from screener.instruments import InstrumentStore
from screener.report import build_records, render_html


def main():
    with tempfile.TemporaryDirectory(prefix="industry-check-") as directory:
        base = Path(directory)
        (base / "data").mkdir()
        for name in ("industry_taxonomy.json", "industry_assignments.json"):
            shutil.copyfile(ROOT / "data" / name, base / "data" / name)
        shutil.copytree(ROOT / "web", base / "web")
        # Test the persisted policy without reading personal exclusions.
        (base / "instrument_exclusions.json").write_text(json.dumps({
            "version": 1, "instruments": {"US:FINS": {"reason": "CLOSED_END_FUND"}}
        }), encoding="utf-8")
        metadata = ensure_dataset(base)
        assert metadata["counts"] == {"major": 14, "middle": 54, "minor": 198}
        assert metadata["company_rows"] == 8298
        industries = IndustryStore(base)
        assert industries.classify("US", "NVDA")["node_ids"] == ["S01"]
        assert len(industries.classify("KR", "005930")["minor_ids"]) == 2
        assert len(industries.classify("US", "AMZN")["major_ids"]) == 4
        assert industries.classify("US", "RUSHB")["in_source"] is False
        assert industries.classify("US", "FINS")["status"] == "excluded"

        catalogue = InstrumentStore(str(base))
        rows = [
            {"symbol": "005930", "name": "삼성전자", "market": "KRX", "country": "KR", "currency": "KRW"},
            {"symbol": "AMZN", "name": "Amazon", "market": "NASDAQ", "country": "US", "currency": "USD"},
            {"symbol": "NVDA", "name": "NVIDIA", "market": "NASDAQ", "country": "US", "currency": "USD"},
        ]
        catalogue.upsert(rows, "test-fixture")
        samsung = industries.list_rows(catalogue, "005930", country="KR")["items"]
        assert next(r for r in samsung if r["symbol"] == "005930")["market"] == "KOSPI"
        positive = industries.list_rows(catalogue, "AMZN", country="US", major="S02", middle="G008", minor="I0030")
        assert any(row["symbol"] == "AMZN" for row in positive["items"])
        negative = industries.list_rows(catalogue, "AMZN", country="US", major="S02", middle="G028")
        assert not any(row["symbol"] == "AMZN" for row in negative["items"])
        last_page = industries.list_rows(catalogue, "AMZN", offset=999999)
        assert last_page["items"] and last_page["offset"] < last_page["filtered"]

        path = base / "data/industry_assignments.json"
        fixture = json.loads(path.read_text(encoding="utf-8"))
        fixture["companies"]["US:000660"] = {
            **fixture["companies"]["KR:000660"], "country": "US", "symbol": "000660"
        }
        path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
        trial = IndustryStore(base)
        saved = trial.save("US", "000660", ["I0001"], note="Isolated country-key check")
        assert saved["status"] == "manual"
        assert IndustryStore(base).classify("KR", "000660")["minor_ids"] == ["I0005", "I0006"]
        restored = IndustryStore(base).save("US", "000660", [], reset=True)
        assert restored["minor_ids"] == ["I0005", "I0006"] and not restored["manual_override"]
        cleared = IndustryStore(base).save("US", "000660", [])
        assert not cleared["paths"] and cleared["manual_override"]
        for ids in (["not-a-node"], ["S01", 1]):
            try:
                IndustryStore(base).save("US", "NVDA", ids)
            except ValueError:
                pass
            else:
                raise AssertionError("Reject invalid node IDs")
        try:
            IndustryStore(base).save("US", "FINS", ["S04"])
        except ValueError:
            pass
        else:
            raise AssertionError("Excluded securities cannot be reassigned as companies")

        cfg = Config(base_dir=str(base), auto_open=False)
        frame = pd.DataFrame([{**row, "asset_type": "STOCK", "last_date": "2026-10-16",
                               "close": 100.0, "aligned": True, "high_count": 1,
                               "marketcap": 1e9, "avg_dollar_volume": 1e6, "high_4w": True}
                              for row in rows])
        records = build_records(frame, cfg)
        assert len(records) == len(rows)
        assert all(record["industry"]["in_source"] for record in records)
        page = render_html(frame, cfg, records, server_mode=True,
                           result_asof="2026-10-16", generated_at="2026-10-17T00:00:00")
        assert "industryMajor" in page and "industryMinor" in page and "sectorInput" not in page
    print("KUIM checks passed: shared data, partial/multiple paths, isolated DB, overrides and screen preservation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
