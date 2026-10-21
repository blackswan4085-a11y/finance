"""미국 실적 발표 캘린더 — 나스닥 공개 API 수집 + 로컬 캐시.

- 소스: https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD
  (이 프로젝트가 시가총액 조회에 이미 사용하는 나스닥 API)
- 기간(기본 7일)의 각 날짜를 호출해 종목·발표시점·EPS 전망을 모아
  earnings_calendar_cache.json 에 저장한다. 화면은 캐시를 읽어 표시하며,
  [업데이트] 시에만 네트워크를 호출한다(recap/customs 수집 패턴과 동일).
- 관심종목(watchlist) 필터는 프런트에서 적용한다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import threading

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
           "Accept": "application/json", "Accept-Language": "en-US"}
BASE = "https://api.nasdaq.com/api/calendar/earnings"
MAX_DAYS = 31
REQUEST_TIMEOUT = 20

_lock = threading.Lock()


def _cache_path(base_dir: str) -> Path:
    return Path(base_dir) / "earnings_calendar_cache.json"


def load(base_dir: str) -> dict:
    """캐시 로드. 없으면 빈 구조."""
    path = _cache_path(base_dir)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("rows"), list):
                return data
        except (OSError, ValueError):
            pass
    return {"from": "", "to": "", "collected_at": "", "rows": []}


def _save(base_dir: str, data: dict) -> None:
    path = _cache_path(base_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _time_label(raw: str) -> str:
    mapping = {"time-pre-market": "장전", "time-after-hours": "장후",
               "time-not-supplied": "", "": ""}
    return mapping.get(raw, raw)


def _fetch_day(day: str) -> list[dict]:
    """하루치 실적 종목 리스트. 주말/휴장은 빈 리스트."""
    resp = requests.get(BASE, params={"date": day}, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json().get("data") or {}
    rows = payload.get("rows") or []
    out = []
    for r in rows:
        symbol = str(r.get("symbol") or "").strip()
        if not symbol:
            continue
        out.append({
            "date": day,
            "symbol": symbol,
            "name": str(r.get("name") or "").strip(),
            "time": _time_label(str(r.get("time") or "")),
            "epsForecast": str(r.get("epsForecast") or "").strip(),
            "lastYearEPS": str(r.get("lastYearEPS") or "").strip(),
            "marketCap": str(r.get("marketCap") or "").strip(),
            "fiscalQuarterEnding": str(r.get("fiscalQuarterEnding") or "").strip(),
        })
    return out


def _date_range(start: date, days: int) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range(days)]


def refresh(base_dir: str, start: str = "", days: int = 7) -> dict:
    """나스닥에서 기간 실적 캘린더를 수집해 캐시에 저장하고 반환.

    start: 'YYYY-MM-DD' (기본: 오늘), days: 1~31.
    """
    try:
        start_date = date.fromisoformat(start) if start else date.today()
    except ValueError:
        raise ValueError("시작 날짜 형식을 확인해 주세요 (YYYY-MM-DD).")
    days = max(1, min(int(days), MAX_DAYS))
    rows: list[dict] = []
    with _lock:
        for day in _date_range(start_date, days):
            try:
                rows.extend(_fetch_day(day))
            except (requests.RequestException, ValueError, KeyError, TypeError):
                # 하루 실패는 건너뛰고 나머지를 계속 수집(부분 성공 허용).
                continue
        rows.sort(key=lambda r: (r["date"], r["symbol"]))
        data = {"from": start_date.isoformat(),
                "to": _date_range(start_date, days)[-1],
                "collected_at": datetime.now().isoformat(timespec="seconds"),
                "rows": rows}
        _save(base_dir, data)
    return data
