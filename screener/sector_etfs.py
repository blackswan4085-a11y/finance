"""User-editable sector ETF mappings and the stock chart opening layout."""
from __future__ import annotations

import json
import os
import threading
from collections import Counter
from urllib.parse import quote

from .sectors import load_sectors, load_manual_sectors, set_sector, reset_sector
from .sector_classification import classification_context

_LOCK = threading.RLock()
DEFAULT_MAPPING = {
    "반도체": "NASDAQ:SMH",
    "결제": "ARCA:IPAY",
    "정보기술": "ARCA:XLK",
    "커뮤니케이션": "ARCA:XLC",
    "경기소비재": "ARCA:XLY",
    "필수소비재": "ARCA:XLP",
    "금융": "ARCA:XLF",
    "헬스케어": "ARCA:XLV",
    "산업재": "ARCA:XLI",
    "소재": "ARCA:XLB",
    "에너지": "ARCA:XLE",
    "유틸리티": "ARCA:XLU",
    "부동산": "ARCA:XLRE",
}

def _path(base_dir):
    return os.path.join(base_dir, "sector_etfs.json")

def _write(base_dir, settings):
    path = _path(base_dir)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as stream:
        json.dump(settings, stream, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(temp, path)

def load_sector_etfs(base_dir):
    with _LOCK:
        path = _path(base_dir)
        if not os.path.exists(path):
            settings = {"version": 1, "benchmark": "ARCA:SPY", "mapping": dict(DEFAULT_MAPPING)}
            _write(base_dir, settings)
            return settings
        try:
            with open(path, encoding="utf-8") as stream:
                settings = json.load(stream)
            if not isinstance(settings, dict) or not isinstance(settings.get("mapping"), dict):
                raise ValueError("잘못된 설정 형식")
            if not all(isinstance(k, str) and isinstance(v, str) for k, v in settings["mapping"].items()):
                raise ValueError("섹터와 ETF 코드는 문자열이어야 합니다")
            if not isinstance(settings.get("benchmark"), str) or not settings["benchmark"].strip():
                raise ValueError("시장 기준 ETF가 없습니다")
            return settings
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError("섹터 ETF 설정을 읽지 못했습니다. sector_etfs.json을 확인해 주세요.") from exc

def _etf_code(store, value):
    instrument = store.resolve(value)
    if instrument["asset_type"] != "ETF":
        raise ValueError("ETF를 선택해 주세요: " + str(value))
    return instrument["market"] + ":" + instrument["symbol"]

def save_sector_etfs(base_dir, store, payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("mapping"), dict):
        raise ValueError("섹터 ETF 연결 목록을 확인해 주세요.")
    if len(payload["mapping"]) > 500:
        raise ValueError("섹터는 최대 500개까지 연결할 수 있습니다.")
    benchmark = _etf_code(store, payload.get("benchmark", ""))
    mapping = {}
    folded = set()
    for raw_label, raw_etf in payload["mapping"].items():
        label = str(raw_label).strip()
        value = str(raw_etf or "").strip()
        if not label or len(label) > 80 or label.casefold() in folded:
            raise ValueError("섹터 이름이 비어 있거나 중복되었습니다.")
        folded.add(label.casefold())
        mapping[label] = _etf_code(store, value) if value else ""
    association = None
    if payload.get("symbol") and payload.get("assign_sector", True):
        instrument = store.resolve(payload["symbol"])
        sector = str(payload.get("sector") or "").strip()
        if len(sector) > 80:
            raise ValueError("섹터 이름은 80자 이내로 입력해 주세요.")
        association = (instrument["symbol"], sector, bool(payload.get("reset_sector")))
    settings = {"version": 1, "benchmark": benchmark, "mapping": mapping}
    with _LOCK:
        _write(base_dir, settings)
        if association:
            if association[2]:
                reset_sector(base_dir, association[0])
            else:
                set_sector(base_dir, *association[:2])
    return sector_etf_settings(base_dir, store, payload.get("symbol", ""))

def sector_etf_settings(base_dir, store, symbol=""):
    settings = load_sector_etfs(base_dir)
    assignments = load_sectors(base_dir)
    counts = Counter(value.strip() for value in assignments.values() if value.strip())
    labels = sorted(set(settings["mapping"]) | set(counts))
    context = None
    if symbol:
        instrument = store.resolve(symbol)
        context = {"symbol": instrument["symbol"], "code": store.public(dict(instrument))["code"],
                   "name": instrument["name"], "sector": assignments.get(instrument["symbol"], ""),
                   "manual_override": instrument["symbol"] in load_manual_sectors(base_dir),
                   "classification": classification_context(base_dir, store, instrument["symbol"]) if instrument["country"] == "US" else None}
    return {**settings, "sectors": [{"sector": label, "etf": settings["mapping"].get(label, ""),
                                    "count": counts[label]} for label in labels],
            "instrument": context}

def chart_defaults(base_dir, store, symbol):
    instrument = store.resolve(symbol)
    code = store.public(dict(instrument))["code"]
    sector = load_sectors(base_dir).get(instrument["symbol"], "").strip()
    settings = load_sector_etfs(base_dir)
    sector_etf = next((value for label, value in settings["mapping"].items()
                       if label.strip().casefold() == sector.casefold()), "") if sector else ""
    benchmark = settings["benchmark"]
    error = ("종목의 섹터를 입력해 주세요." if not sector else
             sector + " 섹터에 ETF를 연결해 주세요.") if not sector_etf else ""
    plans = [
        {"expression": code, "interval": "daily", "axis": "price", "mode": "candles", "comparisons": []},
        {"expression": code + " / " + sector_etf if sector_etf else "", "interval": "daily",
         "axis": "index100", "mode": "line", "comparisons": [], "error": error},
        {"expression": sector_etf + " / " + benchmark if sector_etf else "", "interval": "daily",
         "axis": "index100", "mode": "line", "comparisons": [], "error": error},
        {"expression": code, "interval": "daily", "axis": "index100", "mode": "line",
         "comparisons": [sector_etf, benchmark] if sector_etf else [], "error": error},
    ]
    return {"symbol": code, "name": instrument["name"], "sector": sector,
            "sector_etf": sector_etf, "benchmark": benchmark, "months": 6,
            "panes": plans, "warning": error,
            "settings_url": "/sector-etfs?symbol=" + quote(instrument["symbol"])}
