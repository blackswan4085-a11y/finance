"""localhost 웹서버: 스크리너 리포트를 서빙하고 섹터 입력을 파일에 저장.

- GET  /            : 리포트 HTML (각 종목 섹터 입력칸 포함)
- POST /api/sector  : {symbol, sector} 를 받아 sectors.json 에 저장
표준 라이브러리(http.server)만 사용 — 추가 설치 불필요.
"""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pandas as pd

from .config import Config
from .report import build_records, render_html
from .sectors import load_sectors, set_sector
from .recap import RecapConfig, DEFAULT_INDICES, load_recap, refresh_recap
from .recap_report import render_recap_html


def _build_recap_config(cfg: Config) -> RecapConfig:
    """메인 Config(config.yaml)의 recap 섹션을 RecapConfig로 변환."""
    raw = getattr(cfg, "recap", None) or {}
    rcfg = RecapConfig(base_dir=cfg.base_dir)
    if isinstance(raw, dict):
        if raw.get("indices"):
            rcfg.indices = raw["indices"]
        if raw.get("commodities"):
            rcfg.commodities = raw["commodities"]
        if raw.get("rates"):
            rcfg.rates = raw["rates"]
        if raw.get("fx"):
            rcfg.fx = raw["fx"]
        if raw.get("lookback_days"):
            rcfg.lookback_days = int(raw["lookback_days"])
        if raw.get("commentary_cmd"):
            rcfg.commentary_cmd = str(raw["commentary_cmd"])
        if raw.get("commentary_timeout"):
            rcfg.commentary_timeout = int(raw["commentary_timeout"])
        if "commentary_enabled" in raw:
            rcfg.commentary_enabled = bool(raw["commentary_enabled"])
    return rcfg


def serve(df: pd.DataFrame, cfg: Config) -> None:
    base_dir = cfg.base_dir
    port = cfg.port
    rcfg = _build_recap_config(cfg)

    def current_html() -> str:
        sectors = load_sectors(base_dir)
        records = build_records(df, cfg, sectors)
        return render_html(df, cfg, records, server_mode=True)

    def current_recap_html() -> str:
        return render_recap_html(load_recap(rcfg), server_mode=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # 콘솔 소음 억제
            pass

        def _send(self, code, body, ctype="text/html; charset=utf-8"):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, current_html())
            elif self.path in ("/recap", "/recap.html"):
                self._send(200, current_recap_html())
            elif self.path == "/api/sectors":
                self._send(200, json.dumps(load_sectors(base_dir), ensure_ascii=False),
                           "application/json; charset=utf-8")
            else:
                self._send(404, "Not Found", "text/plain; charset=utf-8")

        def do_POST(self):
            if self.path == "/api/recap/refresh":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    payload = json.loads(self.rfile.read(length) or b"{}") if length else {}
                    with_comm = bool(payload.get("commentary", True))
                    result = refresh_recap(rcfg, with_commentary=with_comm)
                    self._send(200, json.dumps({"ok": True,
                               "generated_at": result["generated_at"],
                               "commentary_ok": result["commentary"].get("ok", False)},
                               ensure_ascii=False),
                               "application/json; charset=utf-8")
                except Exception as e:  # noqa: BLE001
                    self._send(500, json.dumps({"ok": False, "error": str(e)}),
                               "application/json; charset=utf-8")
                return
            if self.path != "/api/sector":
                self._send(404, "Not Found", "text/plain; charset=utf-8")
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                symbol = str(payload.get("symbol", "")).strip()
                sector = str(payload.get("sector", "")).strip()
                if not symbol:
                    self._send(400, json.dumps({"ok": False, "error": "symbol 필요"}),
                               "application/json; charset=utf-8")
                    return
                set_sector(base_dir, symbol, sector)
                self._send(200, json.dumps({"ok": True}), "application/json; charset=utf-8")
            except Exception as e:  # noqa: BLE001
                self._send(500, json.dumps({"ok": False, "error": str(e)}),
                           "application/json; charset=utf-8")

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://localhost:{port}"
    print(f"\n🌐 리포트 서버 실행 중: {url}")
    print(f"   📈 주간 시장 Recap: {url}/recap  (페이지에서 [업데이트] 클릭 시 생성)")
    print("   섹터는 입력 즉시 sectors.json 에 저장됩니다 (브라우저 캐시와 무관).")
    print("   종료하려면 Ctrl+C 를 누르세요.\n")

    if cfg.auto_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
    finally:
        httpd.shutdown()
