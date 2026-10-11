#!/usr/bin/env python3
"""주식 신고가 · 정배열 스크리너 진입점.

사용법:
    python3 run.py                 # 스캔 후 localhost 서버 실행 + 브라우저 자동 오픈
    python3 run.py --markets KOSPI # 특정 시장만
    python3 run.py --no-cache      # 캐시 무시하고 새로 받기
    python3 run.py --port 8080     # 서버 포트 지정
    python3 run.py --no-open       # 브라우저 자동 오픈 끄기
    python3 run.py --static        # 서버 없이 정적 HTML 파일만 생성(output/)
"""
from __future__ import annotations

import argparse
import os
import sys
import webbrowser

from screener.config import load_config
from screener.screen import run_screen
from screener.report import build_report
from screener.server import serve
from screener.sectors import load_sectors


def main() -> int:
    ap = argparse.ArgumentParser(description="신고가/정배열 스크리너")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "config.yaml"))
    ap.add_argument("--markets", nargs="*", help="config의 markets를 덮어씀")
    ap.add_argument("--include-mode", choices=["any_high", "any_signal", "require_both"],
                    help="리포트 포함 기준 덮어쓰기")
    ap.add_argument("--no-cache", action="store_true", help="캐시 무시")
    ap.add_argument("--port", type=int, help="서버 포트 (기본 config의 port)")
    ap.add_argument("--no-open", action="store_true", help="브라우저 자동 오픈 끄기")
    ap.add_argument("--static", action="store_true",
                    help="서버 없이 정적 HTML 파일만 생성 (섹터 저장 불가)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.markets:
        cfg.markets = args.markets
    if args.include_mode:
        cfg.include_mode = args.include_mode
    if args.no_cache:
        cfg.use_cache = False
    if args.port:
        cfg.port = args.port
    if args.no_open:
        cfg.auto_open = False

    print(f"[run] 시장: {cfg.markets} | 신고가 {cfg.high_periods_weeks}주 | "
          f"MA {cfg.ma_periods_weeks}주 | 모드 {cfg.include_mode}")

    df = run_screen(cfg)
    if df.empty:
        print("[run] 조건을 만족하는 종목이 없습니다. (또는 데이터 수집 실패)")

    print(f"   조건 충족 종목 수: {len(df)}")

    if args.static:
        # 서버 없이 정적 파일만 (섹터는 sectors.json 기준으로 반영만, 편집 저장 불가)
        sectors = load_sectors(cfg.base_dir)
        out = build_report(df, cfg, sectors)
        print(f"\n✅ 정적 리포트 생성: {out}")
        if cfg.auto_open:
            try:
                webbrowser.open("file://" + os.path.abspath(out))
            except Exception:  # noqa: BLE001
                pass
        return 0

    # 기본: localhost 서버 실행 (섹터 입력 즉시 저장)
    serve(df, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
