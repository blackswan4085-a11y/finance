"""Trade display regression checks using isolated data and no external APIs."""
from contextlib import closing
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from screener.customs import db as kr_db, report as kr_report
from screener.customs.names import code_name
from screener.customs.service import CustomsService
from screener.us_customs import db as us_db, report as us_report
from screener.us_customs.service import UsCustomsService
from screener.jp_customs import db as jp_db, report as jp_report
from screener.jp_customs.service import JpCustomsService


class TradeDisplayChecks(unittest.TestCase):
    def test_same_hs_labels_across_all_three_sources(self):
        for module in (kr_db, us_db, jp_db):
            with closing(module.connect(":memory:")) as conn:
                module.ensure_schema(conn)
                for code, expected in (("85", "전기제품"), ("8542", "전자집적회로"),
                                       ("854232", "메모리"), ("2709", "석유 및 역청유(원유에 한한다)")):
                    with self.subTest(source=module.__name__, code=code):
                        self.assertEqual(module.name_for(conn, code), expected)

    def test_unsplit_headings_keep_their_own_names(self):
        names = json.loads((BASE / "data/customs_hs_names.json").read_text(encoding="utf-8"))["names"]
        for code, label in names.items():
            if len(code) == 6 and code.endswith("00") and code[:4] not in names:
                with self.subTest(code=code):
                    self.assertEqual(code_name(code[:4]), label)
        for code, product in (("2703", "토탄"), ("2704", "코크스"),
                              ("2706", "석탄ㆍ갈탄ㆍ토탄"), ("2709", "석유 및 역청유(원유"),
                              ("2715", "역청질혼합물")):
            self.assertTrue(code_name(code).startswith(product))
            self.assertNotIn("상위 품목", code_name(code))

    def test_japan_country_names_override_cached_japanese_labels(self):
        with closing(jp_db.connect(":memory:")) as conn:
            jp_db.ensure_schema(conn)
            conn.execute("INSERT INTO trade_country VALUES (?,?,?,?,?,?)",
                         ("imp", "2026-08", "854232", "50103", "大韓民国", 100))
            self.assertEqual(jp_db.country_breakdown(conn, "854232")[0]["name"], "South Korea")
        self.assertIn("재수출", code_name("00"))

    def test_amount_and_unit_price_formatting(self):
        for module in (kr_report, us_report, jp_report):
            js = module.PAGE_JS
            syntax = subprocess.run(["node", "--check"], input=js, encoding="utf-8", capture_output=True)
            self.assertEqual(syntax.returncode, 0, syntax.stderr)
            prefix = js[:js.index("function cls")]
            if module is jp_report:
                checks = [("fmtYen", 1000, "¥1.00M"), ("fmtYen", 1000000, "¥1.00B"),
                          ("fmtYen", -1000000, "-¥1.00B"), ("fmtUnit", 375, "¥375.00K"),
                          ("fmtUnit", .375, "¥375.00"), ("fmtUnit", .00001, "¥0.0100")]
            else:
                checks = [("fmtUSD", 1000000, "$1.00M"), ("fmtUSD", 1000000000, "$1.00B"),
                          ("fmtUSD", -1000000000, "-$1.00B"), ("fmtUnit", 1000000000, "$1.00B"),
                          ("fmtUnit", 187, "$187.00"), ("fmtUnit", .0001, "$0.0001")]
            checks += [("fmtUnit", None, "-")]
            assertions = "\n".join(f"assert.strictEqual({fn}({json.dumps(value)}), {json.dumps(expected)});"
                                   for fn, value, expected in checks)
            result = subprocess.run(["node", "-e", "const assert=require('node:assert/strict');\n" + prefix + assertions],
                                    encoding="utf-8", capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_new_unit_price_data_survives_display_changes(self):
        with tempfile.TemporaryDirectory(prefix="finance-trade-display-") as directory:
            for service_type, module in ((CustomsService, kr_db), (UsCustomsService, us_db),
                                         (JpCustomsService, jp_db)):
                service = service_type(Path(directory) / service_type.__name__)
                service.ensure_ready()
                with closing(module.connect(str(service.path))) as conn:
                    if module is kr_db:
                        conn.execute("INSERT INTO trade_raw VALUES (?,?,?,?,?,?,?,?)",
                                     ("202608", "8542320000", "원본 명칭", 1000, 600, 2, 3, 400))
                    else:
                        conn.execute("INSERT INTO unit_price (flow,period,hs_code,value,qty,unit) VALUES (?,?,?,?,?,?)",
                                     ("exp", "2026-08", "854232", 1000, 2, "KG"))
                    conn.commit()
                with patch.object(service, "api_key", return_value=None):
                    detail = service.get("detail", {"code": ["854232"]})
                self.assertEqual(detail["name"], "메모리")
                self.assertIsNotNone(detail["unitPrice"])
                if module is kr_db:
                    self.assertEqual(detail["series"][0]["exp_wgt"], 2)
                else:
                    self.assertEqual(detail["unitPrice"]["series"][0]["exp_unit"], 500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
