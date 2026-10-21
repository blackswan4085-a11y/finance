"""미국 Census 수출입 통계: 로컬 DB·백그라운드 수집 (Finance 통합).

CustomsService(관세청판) 패턴을 따르되, 데이터 소스가 Census API 이며
국가별 순위를 HS 상세 진입 시 온디맨드로 수집한다.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import re
import threading

from . import db


def _key_from_env(path: Path) -> str | None:
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            name, _, value = line.strip().removeprefix("export ").partition("=")
            if name.strip() == "CENSUS_API_KEY":
                return value.strip().strip("\"'") or None
    return None


class UsCustomsService:
    def __init__(self, base_dir, settings=None, store=None):
        self.base = Path(base_dir).resolve()
        self.store = store  # InstrumentStore — 관련 종목 검증용(선택)
        self.settings = settings or {}
        if not isinstance(self.settings, dict):
            raise ValueError("us_customs 설정은 매핑이어야 합니다.")
        self.path = self._path(self.settings.get("db_path", "us_customs_workspace/ustrade.db"))
        self.months = int(self.settings.get("months", 60))
        if not 1 <= self.months <= 240:
            raise ValueError("수출입 수집 기간은 1~240개월로 지정해 주세요.")
        self.workspace = self.base / "us_customs_workspace"
        self.state_path = self.workspace / "collection.json"
        self._init_lock = threading.Lock()
        self._lock = threading.Lock()
        self._ready = False
        self._state = {"running": False, "phase": "idle", "message": "", "index": 0,
                       "total": 0, "latest": None, "error": None, "summary": None}
        if self.state_path.is_file():
            try:
                saved = json.loads(self.state_path.read_text(encoding="utf-8"))
                self._state.update({key: saved[key] for key in self._state if key in saved})
            except (OSError, ValueError, TypeError):
                pass
        if self._state["running"]:
            self._state.update(running=False, phase="error", error="서버 재시작으로 수집이 중단되었습니다.",
                               message="서버 재시작으로 수집이 중단되었습니다. 업데이트를 다시 실행해 주세요.")

    def _path(self, value) -> Path:
        path = Path(value)
        return (path if path.is_absolute() else self.base / path).resolve()

    def api_key(self):
        return (self.settings.get("api_key") or os.environ.get("CENSUS_API_KEY")
                or _key_from_env(self.base / ".env"))

    def ensure_ready(self):
        with self._init_lock:
            if self._ready:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(db.connect(str(self.path))) as conn:
                db.ensure_schema(conn)
            self._ready = True

    @staticmethod
    def _code(value, allow_empty=False):
        if not isinstance(value, str) or not (re.fullmatch(r"(?:[0-9]{2}|[0-9]{4}|[0-9]{6})", value)
                                               or (allow_empty and value == "")):
            raise ValueError("HS 코드는 2·4·6자리 숫자로 입력해 주세요.")
        return value

    def get(self, action, query=None):
        query = query or {}
        if action == "collect/status":
            with self._lock:
                return dict(self._state)
        if action not in {"meta", "level", "detail", "overview"}:
            raise KeyError("알 수 없는 수출입 통계 API입니다.")
        code = self._code(query.get("code", [""])[0], allow_empty=action != "detail")
        level = int(query.get("level", ["2"])[0])
        if level not in (2, 4, 6):
            raise ValueError("HS 레벨은 2·4·6 중 하나여야 합니다.")
        if action == "level" and len(code) != level - 2:
            raise ValueError("상위 HS 코드와 조회 레벨을 확인해 주세요.")
        self.ensure_ready()
        with closing(db.connect(str(self.path))) as conn:
            if action == "meta":
                result = db.get_meta(conn)
                result.setdefault("latest_month", db.latest_month(conn) or "")
                return result
            if action == "level":
                self._ensure_level(conn, code, level)
                return db.level_summary(conn, code, level, db.latest_month(conn))
            if action == "overview":
                return db.overview(conn)
            return self._detail(conn, code)

    def _ensure_level(self, conn, code, level):
        """HS4/HS6 목록이 없으면 온디맨드 수집."""
        if level <= 2:
            return
        if db.level_summary(conn, code, level, db.latest_month(conn)):
            return
        key = self.api_key()
        if not key:
            return
        from .collector import collect_detail
        collect_detail(conn, key, code, level, months=self.months)

    def _detail(self, conn, code):
        level = len(code)
        key = self.api_key()
        if level > 2 and len(db.monthly_series(conn, code)) < 2 and key:
            from .collector import collect_detail
            collect_detail(conn, key, code, min(level + 2, 6), months=self.months)
        period = db.latest_month(conn)
        imp_ctry, exp_ctry = [], []
        if not db.country_breakdown(conn, code, period, "imp") and key:
            from .collector import collect_country_breakdown
            collect_country_breakdown(conn, key, code, period)
        imp_ctry = db.country_breakdown(conn, code, period, "imp")
        exp_ctry = db.country_breakdown(conn, code, period, "exp")
        series = db.monthly_series(conn, code)
        return {"prefix": code, "level": level, "name": db.name_for(conn, code),
                "series": series, "expYoy": db.compute_yoy(series, "exp_dlr"),
                "impYoy": db.compute_yoy(series, "imp_dlr"),
                "qExp": db.compute_quarterly(series, "exp_dlr"),
                "impCountries": imp_ctry, "expCountries": exp_ctry,
                "companies": db.list_companies(conn, code)}

    def post(self, action, payload):
        if not isinstance(payload, dict):
            raise ValueError("JSON 객체로 요청해 주세요.")
        if action == "collect":
            return self.start_collection()
        if action not in {"company/add", "company/delete"}:
            raise KeyError("알 수 없는 수출입 통계 API입니다.")
        if action == "company/add":
            code = self._code(payload.get("hs_code"))
            if int(payload.get("hs_level", 0)) != len(code):
                raise ValueError("HS 코드와 레벨이 일치하지 않습니다.")
            if self.store is None:
                raise ValueError("종목 조회를 사용할 수 없습니다.")
            row = self.store.resolve(str(payload.get("symbol", "")))
            stock = {"symbol": str(row["symbol"]), "country": str(row["country"]),
                     "name": str(row.get("name") or row["symbol"]), "market": str(row.get("market") or "")}
        else:
            cid = payload.get("id")
            if isinstance(cid, bool) or not isinstance(cid, int) or cid <= 0:
                raise ValueError("관련 종목 ID를 확인해 주세요.")
        self.ensure_ready()
        with closing(db.connect(str(self.path))) as conn:
            if action == "company/add":
                db.add_company(conn, code, len(code), stock["symbol"], stock["country"],
                               stock["name"], stock["market"],
                               datetime.now().isoformat(timespec="seconds"))
            else:
                db.delete_company(conn, cid)
        return {"ok": True}

    def _save_state(self):
        self.workspace.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(self._state, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, self.state_path)

    def start_collection(self):
        with self._lock:
            if self._state["running"]:
                return {"ok": True, **self._state}
            key = self.api_key()
            if not key:
                raise ValueError("CENSUS_API_KEY를 환경변수 또는 finance/.env에 설정해 주세요.")
            self.ensure_ready()
            self._state.update(running=True, phase="start", message="수집 시작...", index=0,
                               total=0, error=None, summary=None)
            self._save_state()
            status = {"ok": True, **self._state}
            threading.Thread(target=self._collect, args=(key,), daemon=True).start()
            return status

    def _collect(self, key):
        def progress(event):
            with self._lock:
                self._state.update({k: v for k, v in event.items() if k in self._state})
                self._save_state()

        try:
            from .collector import run_collection
            summary = run_collection(progress=progress, incremental=True,
                                     db_path=str(self.path), api_key=key, months=self.months)
            with self._lock:
                self._state.update(running=False, phase="done", summary=summary)
                self._save_state()
        except Exception as exc:
            message = str(exc).replace(str(key), "[API 키]")
            message = re.sub(r"(?i)(key=)[^&\s]+", r"\1[API 키]", message)
            with self._lock:
                self._state.update(running=False, phase="error", error=message, message=message)
                self._save_state()
