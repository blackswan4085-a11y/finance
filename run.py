#!/usr/bin/env python3
"""주식 신고가 · 정배열 스크리너 진입점.

사용법:
    python3 run.py                 # config.yaml 기준으로 전체 스캔 -> HTML 리포트
    python3 run.py --markets KOSPI # 특정 시장만
    python3 run.py --no-cache      # 캐시 무시하고 새로 받기
    python3 run.py --open          # 생성된 리포트 경로 출력
"""
from __future__ import annotations

import argparse
import os
import sys
import webbrowser

from screener.config import load_config
from screener.screen import run_screen
from screener.report import build_report


def main() -> int:
    ap = argparse.ArgumentParser(description="신고가/정배열 스크리너")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "config.yaml"))
    ap.add_argument("--markets", nargs="*", help="config의 markets를 덮어씀")
    ap.add_argument("--include-mode", choices=["any_high", "any_signal", "require_both"],
                    help="리포트 포함 기준 덮어쓰기")
    ap.add_argument("--no-cache", action="store_true", help="캐시 무시")
    ap.add_argument("--open", action="store_true", help="리포트를 브라우저로 열기")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.markets:
        cfg.markets = args.markets
    if args.include_mode:
        cfg.include_mode = args.include_mode
    if args.no_cache:
        cfg.use_cache = False

    print(f"[run] 시장: {cfg.markets} | 신고가 {cfg.high_periods_weeks}주 | "
          f"MA {cfg.ma_periods_weeks}주 | 모드 {cfg.include_mode}")

    df = run_screen(cfg)
    if df.empty:
        print("[run] 조건을 만족하는 종목이 없습니다. (또는 데이터 수집 실패)")
        # 빈 리포트라도 생성
    out = build_report(df, cfg)
    print(f"\n✅ 리포트 생성 완료: {out}")
    print(f"   조건 충족 종목 수: {len(df)}")

    if args.open:
        try:
            webbrowser.open("file://" + os.path.abspath(out))
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
