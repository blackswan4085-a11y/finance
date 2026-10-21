"""localhost 웹서버: 스크리너 리포트를 서빙하고 섹터 입력을 파일에 저장.

- GET  /            : 리포트 HTML (각 종목 섹터 입력칸 포함)
- POST /api/sector  : {symbol, sector} 를 받아 sectors.json 에 저장
표준 라이브러리(http.server)만 사용 — 추가 설치 불필요.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit, unquote

import pandas as pd

from .chart_service import ChartService
from .instruments import InstrumentStore
from .config import Config
from .report import build_records, render_html
from .sectors import load_sectors, set_sector
from .sector_classification import classification_rows
from .sector_etfs import load_sector_etfs, sector_etf_settings, save_sector_etfs, chart_defaults
from .recap import RecapConfig, DEFAULT_INDICES, load_recap, refresh_recap
from .recap_report import render_recap_html
from .screen import run_screen
from .weekly import previous_week_friday
from .industry import IndustryStore, ensure_dataset
from .earnings import EarningsService, EarningsConflict
from .screen_cache import read_screen_cache, publish_screen_cache
from .customs.service import CustomsService
from .customs.report import page_html as customs_page_html


class FinanceHTTPServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR permits two unrelated servers to bind the same port.
    # Exclusive binding prevents the browser from reaching an older instance.
    allow_reuse_address = False

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


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


def serve(df: pd.DataFrame | None, cfg: Config) -> None:
    base_dir = cfg.base_dir
    port = cfg.port
    # Claim the port before touching shared caches or recovering earnings jobs.
    # A duplicate startup must not change the active server's workspace.
    try:
        httpd = FinanceHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
    except OSError:
        print(f"\n서버 시작 실패: localhost:{port} 포트를 사용 중이거나 연결할 수 없습니다. "
              "이미 실행 중인 finance 서버가 있는지 확인해 주세요.")
        raise
    ensure_dataset(base_dir)
    rcfg = _build_recap_config(cfg)
    earnings = EarningsService(base_dir, cfg.earnings)
    customs = CustomsService(base_dir, cfg.customs)
    screen_cache_path = os.path.join(base_dir, "screen_cache.json")
    web_dir = os.path.join(base_dir, "web")
    chart_page_path = os.path.join(web_dir, "chart-view.html")
    chart_assets_dir = os.path.join(web_dir, "chart-assets")
    screen_df = df if df is not None else pd.DataFrame()
    screen_asof = ""
    screen_generated_at = ""
    screen_note = ""
    if df is None:
        try:
            cached = read_screen_cache(screen_cache_path)
            if cached:
                screen_df = pd.DataFrame(cached["rows"])
                screen_asof = cached["asof_date"]
                screen_generated_at = cached["generated_at"]
                screen_note = cached.get("recovery_note", "")
        except (OSError, ValueError, KeyError, TypeError):
            screen_df = pd.DataFrame()
    store = InstrumentStore(base_dir)
    store.register_cached_equities(cfg.cache_path)
    if not screen_df.empty:
        store.upsert(screen_df.to_dict("records"), "screen-cache")
        screen_df = store.equity_frame(screen_df)
    chart_service = ChartService(cfg, store)
    load_sector_etfs(base_dir)
    catalog_lock = threading.Lock()
    catalog_job = {"state": "idle", "counts": store.counts()}

    def refresh_catalog_in_background():
        try:
            result = store.refresh_etfs()
            with catalog_lock:
                catalog_job.update(result, state="done" if result["ok"] else "error",
                                   generated_at=datetime.now().isoformat(timespec="seconds"))
        except Exception as exc:
            with catalog_lock:
                catalog_job.update(state="error", error=str(exc), counts=store.counts())

    screen_state_lock = threading.Lock()
    screen_job = {"state": "idle"}

    def refresh_screen_in_background(asof_date) -> None:
        nonlocal screen_df, screen_asof, screen_generated_at, screen_note
        try:
            fresh_df = run_screen(cfg, asof_date=asof_date)
            cached = publish_screen_cache(screen_cache_path, fresh_df, asof_date)
            generated_at = cached["generated_at"]
            with screen_state_lock:
                screen_df, screen_asof, screen_generated_at = fresh_df, cached["asof_date"], generated_at
                screen_note = ""
                screen_job.update(state="done", count=len(fresh_df), generated_at=generated_at, scan=cached["scan"])
        except Exception as e:  # noqa: BLE001
            with screen_state_lock:
                screen_job.update(state="error", error=str(e) + " 저장된 결과는 변경하지 않았습니다.")

    def current_html() -> str:
        sectors = load_sectors(base_dir)
        with screen_state_lock:
            shown_df, shown_asof, shown_generated_at = screen_df, screen_asof, screen_generated_at
            shown_note = screen_note
        records = build_records(shown_df, cfg, sectors)
        return render_html(shown_df, cfg, records, server_mode=True,
                           result_asof=shown_asof, generated_at=shown_generated_at, result_note=shown_note)

    def current_recap_html() -> str:
        return render_recap_html(load_recap(rcfg), server_mode=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # 콘솔 소음 억제
            pass

        def _send(self, code, body, ctype="text/html; charset=utf-8"):
            data = body.encode("utf-8") if isinstance(body, str) else body
            try:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                pass  # 브라우저가 닫혀도 이미 완료된 작업은 유지

        def do_GET(self):
            parsed = urlsplit(self.path)
            route = parsed.path
            weekly_routes = {"/weekly/recap": "/recap", "/weekly/industries": "/industries",
                             "/weekly/sector-etfs": "/sector-etfs", "/weekly/sector-classifications": "/sector-classifications"}
            route = weekly_routes.get(route, route)
            if route in ("/customs", "/customs/"):
                try:
                    self._send(200, customs_page_html(customs.get("meta")))
                except (OSError, ValueError) as exc:
                    self._send(500, str(exc), "text/plain; charset=utf-8")
            elif route.startswith("/api/customs/"):
                self._customs_request("GET", parsed)
            elif route in ("/", "/index.html", "/earnings", "/earnings-view.js", "/earnings.css"):
                filename = "earnings-view.html" if route in ("/", "/index.html", "/earnings") else route.lstrip("/")
                ctype = "text/javascript; charset=utf-8" if filename.endswith(".js") else "text/css; charset=utf-8" if filename.endswith(".css") else "text/html; charset=utf-8"
                with open(os.path.join(web_dir, filename), "rb") as stream:
                    self._send(200, stream.read(), ctype)
            elif route in ("/weekly", "/weekly/"):
                self._send(200, current_html())
            elif route in ("/api/earnings", "/api/earnings/project"):
                try:
                    result = earnings.list() if route == "/api/earnings" else earnings.get(parse_qs(parsed.query).get("id", [""])[0])
                    self._send(200, json.dumps(result, ensure_ascii=False, allow_nan=False), "application/json; charset=utf-8")
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    self._send(400, json.dumps({"error": str(exc)}, ensure_ascii=False), "application/json; charset=utf-8")
            elif route.startswith("/earnings-files/"):
                try:
                    parts = [unquote(p) for p in route.removeprefix("/earnings-files/").split("/")]
                    if len(parts) != 3:
                        raise ValueError("파일을 찾을 수 없습니다.")
                    ident, version, filename = parts
                    artifact = earnings.artifact(ident, filename, version)
                    ctype = "image/png" if filename.endswith(".png") else "application/json; charset=utf-8" if filename.endswith(".json") else "text/html; charset=utf-8"
                    self._send(200, artifact.read_bytes(), ctype)
                except (OSError, ValueError, KeyError) as exc:
                    self._send(404, str(exc), "text/plain; charset=utf-8")
            elif route in ("/recap", "/recap.html"):
                self._send(200, current_recap_html())
            elif route in ("/sector-etfs", "/sector-etfs.js", "/sector-classifications", "/sector-classifications.js"):
                filename = route.strip("/") + ("" if route.endswith(".js") else ".html")
                ctype = "text/javascript; charset=utf-8" if route.endswith(".js") else "text/html; charset=utf-8"
                with open(os.path.join(web_dir, filename), "rb") as stream:
                    self._send(200, stream.read(), ctype)
            elif route in ("/ui.css", "/ui.js"):
                ctype = "text/css; charset=utf-8" if route.endswith(".css") else "text/javascript; charset=utf-8"
                with open(os.path.join(web_dir, route.lstrip("/")), "rb") as stream:
                    self._send(200, stream.read(), ctype)
            elif route in ("/industries", "/industry-view.js", "/industry-controls.js"):
                filename = "industry-view.html" if route == "/industries" else route.lstrip("/")
                ctype = "text/html; charset=utf-8" if route == "/industries" else "text/javascript; charset=utf-8"
                with open(os.path.join(web_dir, filename), "rb") as stream:
                    self._send(200, stream.read(), ctype)
            elif route == "/chart":
                with open(chart_page_path, "rb") as f:
                    self._send(200, f.read())
            elif route.startswith("/chart-assets/"):
                asset = route.removeprefix("/chart-assets/")
                types = {"chart.js": "text/javascript; charset=utf-8",
                         "indicators.js": "text/javascript; charset=utf-8",
                         "styles.css": "text/css; charset=utf-8"}
                if asset not in types:
                    self._send(404, "Not Found", "text/plain; charset=utf-8")
                    return
                with open(os.path.join(chart_assets_dir, asset), "rb") as f:
                    self._send(200, f.read(), types[asset])
            elif route == "/chart-view.js":
                with open(os.path.join(web_dir, "chart-view.js"), "rb") as f:
                    self._send(200, f.read(), "text/javascript; charset=utf-8")
            elif route == "/api/instruments":
                query = parse_qs(parsed.query).get("q", [""])[0]
                kind = parse_qs(parsed.query).get("asset_type", [""])[0]
                self._send(200, json.dumps({"items": store.search(query, asset_type=kind), "counts": store.counts()}, ensure_ascii=False),
                           "application/json; charset=utf-8")
            elif route == "/api/instruments/status":
                with catalog_lock:
                    status = dict(catalog_job)
                self._send(200, json.dumps(status, ensure_ascii=False), "application/json; charset=utf-8")
            elif route == "/api/chart":
                symbols = parse_qs(parsed.query).get("symbol", [])
                requested = symbols[0].strip() if len(symbols) == 1 else ""
                with screen_state_lock:
                    asof = screen_asof
                try:
                    result = chart_service.payload(requested, asof)
                except (OSError, ValueError, KeyError) as exc:
                    self._send(404, json.dumps({"error": str(exc)}, ensure_ascii=False),
                               "application/json; charset=utf-8")
                    return
                self._send(200, json.dumps(result, ensure_ascii=False, allow_nan=False),
                           "application/json; charset=utf-8")
            elif route in ("/api/sector-etfs", "/api/chart-defaults"):
                symbol = parse_qs(parsed.query).get("symbol", [""])[0]
                try:
                    result = (chart_defaults(base_dir, store, symbol) if route == "/api/chart-defaults"
                              else sector_etf_settings(base_dir, store, symbol))
                    industry = IndustryStore(base_dir).classify(store.resolve(symbol)["country"], store.resolve(symbol)["symbol"]) if symbol else None
                    if route == "/api/chart-defaults":
                        result["industry"] = industry
                    elif result.get("instrument"):
                        result["instrument"]["industry"] = industry
                    self._send(200, json.dumps(result, ensure_ascii=False), "application/json; charset=utf-8")
                except (OSError, ValueError) as exc:
                    self._send(400, json.dumps({"error": str(exc)}, ensure_ascii=False), "application/json; charset=utf-8")
            elif route in ("/api/industry-taxonomy", "/api/industries", "/api/industry"):
                query = parse_qs(parsed.query)
                try:
                    industries = IndustryStore(base_dir)
                    if route == "/api/industry-taxonomy":
                        result = industries.catalogue()
                    elif route == "/api/industry":
                        symbol = query.get("symbol", [""])[0]
                        country = query.get("country", [""])[0]
                        if not country:
                            country = store.resolve(symbol)["country"]
                        if country not in {"KR", "US"} or not symbol:
                            raise ValueError("국가·종목코드를 확인해 주세요.")
                        industry = industries.classify(country, symbol)
                        if not industry["in_source"]:
                            instrument = store.resolve(("KRX:" if country == "KR" else "US:") + symbol)
                            industry["name"] = instrument["name"]
                        result = {"industry": industry}
                    else:
                        options = {key: query.get(key, [""])[0] for key in ("country", "status", "major", "middle", "minor")}
                        result = industries.list_rows(store, query.get("q", [""])[0],
                            offset=int(query.get("offset", ["0"])[0]), limit=int(query.get("limit", ["100"])[0]), **options)
                    self._send(200, json.dumps(result, ensure_ascii=False), "application/json; charset=utf-8")
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    self._send(400, json.dumps({"error": str(exc)}, ensure_ascii=False), "application/json; charset=utf-8")
            elif route == '/api/sector-classifications':
                query = parse_qs(parsed.query)
                try:
                    offset = max(0, int(query.get('offset', ['0'])[0]))
                    result = classification_rows(base_dir, store, query.get('q', [''])[0],
                                                 query.get('status', [''])[0], offset)
                    self._send(200, json.dumps(result, ensure_ascii=False), 'application/json; charset=utf-8')
                except (OSError, ValueError) as exc:
                    self._send(400, json.dumps({'error':str(exc)}, ensure_ascii=False), 'application/json; charset=utf-8')
            elif route == "/api/sectors":
                self._send(200, json.dumps(load_sectors(base_dir), ensure_ascii=False),
                           "application/json; charset=utf-8")
            elif route == "/api/screen/status":
                with screen_state_lock:
                    status = dict(screen_job)
                self._send(200, json.dumps(status, ensure_ascii=False),
                           "application/json; charset=utf-8")
            else:
                self._send(404, "Not Found", "text/plain; charset=utf-8")

        def do_POST(self):
            parsed = urlsplit(self.path)
            if parsed.path.startswith("/api/customs/"):
                self._customs_request("POST", parsed)
                return
            if self.path.startswith("/api/earnings/"):
                try:
                    # Same-origin JSON writes protect local source material from other websites.
                    origin = self.headers.get("Origin")
                    if origin and origin != "http://" + self.headers.get("Host", ""):
                        self._send(403, '{"error":"허용되지 않은 요청입니다."}', "application/json; charset=utf-8")
                        return
                    if self.headers.get_content_type() != "application/json":
                        raise ValueError("JSON 형식으로 요청해 주세요.")
                    length = int(self.headers.get("Content-Length", 0))
                    if not 0 < length <= 12_000_000:
                        raise ValueError("입력 자료 크기를 확인해 주세요.")
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError("입력 형식을 확인해 주세요.")
                    action = self.path.removeprefix("/api/earnings/")
                    if action == "create":
                        result = earnings.create(payload)
                    elif action == "save":
                        result = earnings.save(payload.get("id", ""), payload)
                    elif action in ("fetch", "generate"):
                        result = earnings.start(payload.get("id", ""), action, payload)
                    else:
                        self._send(404, '{"error":"알 수 없는 작업입니다."}', "application/json; charset=utf-8")
                        return
                    self._send(202 if action in ("fetch", "generate") else 200,
                               json.dumps(result, ensure_ascii=False, allow_nan=False), "application/json; charset=utf-8")
                except EarningsConflict as exc:
                    self._send(409, json.dumps({"error": str(exc)}, ensure_ascii=False), "application/json; charset=utf-8")
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    self._send(400, json.dumps({"error": str(exc)}, ensure_ascii=False), "application/json; charset=utf-8")
                return
            if self.path == "/api/industry":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    if length < 1 or length > 16384:
                        raise ValueError("분류 데이터 크기를 확인해 주세요.")
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError("분류 데이터를 확인해 주세요.")
                    if not isinstance(payload.get("reset", False), bool):
                        raise ValueError("복원 요청 형식을 확인해 주세요.")
                    result = IndustryStore(base_dir).save(payload.get("country", ""), payload.get("symbol", ""),
                        payload.get("node_ids", []), payload.get("note", ""), payload.get("reset", False), store, review_required=payload.get("review_required", False))
                    self._send(200, json.dumps({"ok": True, "industry": result}, ensure_ascii=False), "application/json; charset=utf-8")
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    self._send(400, json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), "application/json; charset=utf-8")
                return
            if self.path == "/api/sector-etfs":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    if length < 1 or length > 262144:
                        raise ValueError("설정 데이터 크기를 확인해 주세요.")
                    payload = json.loads(self.rfile.read(length))
                    result = save_sector_etfs(base_dir, store, payload)
                    self._send(200, json.dumps({"ok": True, **result}, ensure_ascii=False), "application/json; charset=utf-8")
                except (OSError, ValueError, TypeError) as exc:
                    self._send(400, json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), "application/json; charset=utf-8")
                return
            if self.path == "/api/instruments/refresh":
                with catalog_lock:
                    if catalog_job["state"] != "running":
                        catalog_job.clear()
                        catalog_job.update(state="running", counts=store.counts())
                        threading.Thread(target=refresh_catalog_in_background, daemon=True).start()
                    status = dict(catalog_job)
                self._send(202, json.dumps(status, ensure_ascii=False), "application/json; charset=utf-8")
                return
            if self.path == "/api/screen/refresh":
                with screen_state_lock:
                    if screen_job["state"] == "running":
                        status = dict(screen_job)
                    else:
                        asof_date = previous_week_friday()
                        screen_job.clear()
                        screen_job.update(state="running", asof_date=asof_date.isoformat(),
                                          started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                        status = dict(screen_job)
                        threading.Thread(target=refresh_screen_in_background,
                                         args=(asof_date,), daemon=True).start()
                self._send(202, json.dumps(status, ensure_ascii=False),
                           "application/json; charset=utf-8")
                return
            if self.path == "/api/recap/refresh":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    payload = json.loads(self.rfile.read(length) or b"{}") if length else {}
                    with_comm = bool(payload.get("commentary", True))
                    result = refresh_recap(rcfg, with_commentary=with_comm,
                                           asof_date=previous_week_friday())
                    self._send(200, json.dumps({"ok": True,
                               "generated_at": result["generated_at"],
                               "commentary_ok": all(
                                   result[key].get("ok", False)
                                   for key in ("commentary_index", "commentary_commodity", "commentary_ratefx", "commentary_overview")
                               )},
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

        def _customs_request(self, method, parsed):
            try:
                action = parsed.path.removeprefix("/api/customs/")
                if method == "GET":
                    result = customs.get(action, parse_qs(parsed.query))
                else:
                    origin = self.headers.get("Origin")
                    if origin and origin != "http://" + self.headers.get("Host", ""):
                        self._send(403, '{"error":"허용되지 않은 요청입니다."}', "application/json; charset=utf-8")
                        return
                    if self.headers.get_content_type() != "application/json":
                        raise ValueError("JSON 형식으로 요청해 주세요.")
                    length = int(self.headers.get("Content-Length", 0))
                    if not 0 < length <= 16384:
                        raise ValueError("입력 자료 크기를 확인해 주세요.")
                    result = customs.post(action, json.loads(self.rfile.read(length)))
                self._send(202 if method == "POST" and action == "collect" else 200,
                           json.dumps(result, ensure_ascii=False, allow_nan=False), "application/json; charset=utf-8")
            except KeyError as exc:
                self._send(404, json.dumps({"error": str(exc)}, ensure_ascii=False), "application/json; charset=utf-8")
            except (ValueError, TypeError) as exc:
                self._send(400, json.dumps({"error": str(exc)}, ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as exc:
                self._send(500, json.dumps({"error": str(exc)}, ensure_ascii=False), "application/json; charset=utf-8")

    httpd.RequestHandlerClass = Handler
    url = f"http://localhost:{port}"
    print(f"\n리포트 서버 실행 중: {url}")
    print(f"   실적 리포트: {url}/  (실적 표 · 컨콜 직접 입력)")
    print(f"   위클리 스크리너: {url}/weekly  (페이지에서 [업데이트] 클릭 시 전주 금요일 기준 스캔)")
    print(f"   주간 시장 Recap: {url}/recap  (페이지에서 [업데이트] 클릭 시 생성)")
    print(f"   섹터 ETF 설정: {url}/sector-etfs")
    print(f"   수출입 통계: {url}/customs  (HS 품목 탐색 · 수집 데이터 업데이트 · 관련 기업)")
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
