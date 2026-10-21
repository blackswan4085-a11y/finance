"""Import the user's HS code catalogue without changing the source workbook.

Run: python scripts/import_customs_names.py [workbook.xlsx]
"""
from collections import Counter
import json
from pathlib import Path
import sys

import openpyxl

BASE = Path(__file__).resolve().parent.parent


def main():
    source = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else BASE.parent / "통합 문서1.xlsx"
    workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
    names = {}
    source_sheets = []
    try:
        for sheet in workbook:
            source_sheets.append(sheet.title)
            for code_value, name_value in sheet.iter_rows(min_col=1, max_col=2, values_only=True):
                if code_value is None or name_value is None:
                    continue
                code = str(code_value).strip()
                if not code.isascii() or not code.isdigit() or len(code) not in (2, 4, 6, 10):
                    continue
                name = str(name_value).strip()
                if not name:
                    continue
                if code in names and names[code] != name:
                    raise ValueError(f"HS {code}에 서로 다른 품목명이 있습니다.")
                names[code] = name
    finally:
        workbook.close()
    if not names:
        raise ValueError("HS 코드와 품목명 자료가 없습니다.")
    payload = {"source_file": source.name, "source_sheets": source_sheets,
               "counts_by_level": dict(sorted(Counter(map(len, names)).items())),
               "names": dict(sorted(names.items()))}
    target = BASE / "data" / "customs_hs_names.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(names)} HS names into {target.name}")
    print(json.dumps(payload["counts_by_level"]))


if __name__ == "__main__":
    main()
