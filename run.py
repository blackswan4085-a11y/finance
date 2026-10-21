#!/usr/bin/env python3
"""주식 신고가 · 정배열 스크리너 진입점.

사용법:
    python3 run.py                 # 수집 없이 서버 실행 + 브라우저 자동 오픈
    python3 run.py --markets KOSPI # 특정 시장만
    python3 run.py --no-cache      # 캐시 무시하고 새로 받기
    python3 run.py --port 8080     # 서버 포트 지정
    python3 run.py --no-open       # 브라우저 자동 오픈 끄기
    python3 run.py --static        # 전주 금요일 기준 스캔 후 정적 HTML 생성(output/)
"""
from __future__ import annotations

import argparse
import os
import sys
import webbrowser

from screener.config import load_config
from screener.instruments import InstrumentStore
from screener.screen import run_screen
from screener.report import build_report
from screener.server import serve
from screener.sectors import load_sectors
from screener.weekly import previous_week_friday


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
    ap.add_argument("--sync-etfs", action="store_true",
                    help="차트 검색용 ETF 목록만 DB에 갱신 (신고가 스캔 안 함)")
    ap.add_argument('--classify-us', action='store_true', help='미국 DB 주식만 업종 근거로 섹터에 연결 (신고가 스캔 없음)')
    ap.add_argument('--classification-manifest', default=None, help='분류 원본·출처 manifest.json 경로')
    customs_cli = ap.add_mutually_exclusive_group()
    customs_cli.add_argument('--collect-customs', action='store_true', help='수출입 통계 증분 수집 후 종료')
    customs_cli.add_argument('--customs-static', action='store_true', help='수출입 통계 정적 HTML 생성 (output/customs.html)')
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.collect_customs or args.customs_static:
        from pathlib import Path
        from contextlib import closing
        from screener.customs.service import CustomsService
        from screener.customs import db
        from screener.customs.report import build_static
        customs = CustomsService(cfg.base_dir, cfg.customs)
        if args.collect_customs:
            import time
            try:
                customs.start_collection()
                last_message = None
                while True:
                    status = customs.get('collect/status')
                    if status['message'] != last_message:
                        print(status['message'])
                        last_message = status['message']
                    if not status['running']:
                        return 0 if status['phase'] == 'done' else 1
                    time.sleep(.25)
            except (OSError, ValueError) as exc:
                print(str(exc))
                return 1
        customs.ensure_ready()
        with closing(db.connect(str(customs.path))) as conn:
            if not db.latest_month(conn):
                print('저장된 수출입 자료가 없습니다. --collect-customs로 먼저 수집해 주세요.')
                return 1
            html = build_static(conn, customs.get('meta'))
        target = Path(cfg.output_path) / 'customs.html'
        target.write_text(html, encoding='utf-8')
        print(f'수출입 정적 리포트: {target}')
        if cfg.auto_open and not args.no_open:
            webbrowser.open(target.resolve().as_uri())
        return 0
    if args.classify_us:
        import json
        from screener.sector_classification import classify_us
        manifest = args.classification_manifest or os.path.join(cfg.base_dir, 'classification_sources', 'manifest.json')
        result = classify_us(cfg.base_dir, InstrumentStore(cfg.base_dir), manifest)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.sync_etfs:
        result = InstrumentStore(cfg.base_dir).refresh_etfs()
        for source in result["sources"]:
            print(f"[ETF] {source['source']}: " +
                  (f"{source['count']}개 저장" if source["ok"] else source["error"]))
        print(f"[ETF] DB: {result['counts']}")
        return 0 if result["ok"] else 1
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

    if args.static:
        df = run_screen(cfg, asof_date=previous_week_friday())
        if df.empty:
            print("[run] 조건을 만족하는 종목이 없습니다. (또는 데이터 수집 실패)")
        print(f"   조건 충족 종목 수: {len(df)}")
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

    # 기본: 수집 없이 서버 실행. 스크리닝은 화면의 업데이트 버튼에서만 수행.
    serve(None, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
