"""Import the user's KUIM reference while keeping manual assignments separate."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from screener.industry import import_workbook, workbook_rows


def main():
    parser = argparse.ArgumentParser(description='KUIM 산업 분류 가져오기')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--inspect', action='store_true', help='원본 시트·행 수 읽기')
    mode.add_argument('--import', dest='apply', action='store_true', help='분류 마스터·기업 배정 갱신')
    parser.add_argument('--source', type=Path, default=ROOT / 'KUIM_전체결과표.xlsx')
    args = parser.parse_args()
    if args.inspect:
        sheets = workbook_rows(args.source)
        print(json.dumps({name: len([row for row in rows if row['source_row'] >= 7])
                          for name, rows in sheets.items()}))
    else:
        print(json.dumps(import_workbook(ROOT, args.source)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
