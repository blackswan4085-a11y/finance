"""Rebuild saved reports with one-page layout and fresh market data, without AI."""
from pathlib import Path
import argparse
import sys

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from screener.config import load_config
from screener.earnings import EarningsService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ids', nargs='*')
    parser.add_argument('--keep-market', action='store_true', help='Keep the saved market snapshot')
    args = parser.parse_args()
    config = load_config(str(BASE / "config.yaml"))
    service = EarningsService(BASE, config.earnings)
    names = args.ids or [item["id"] for item in service.list()["items"] if item["has_report"]]
    failures = []
    for ident in names:
        print("Rebuilding " + ident, flush=True)
        try:
            path = service.rerender_saved(ident, refresh_market=not args.keep_market)
            print("Saved " + str(path), flush=True)
        except Exception as exc:
            failures.append(ident)
            print("Failed " + ident + ": " + str(exc), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
