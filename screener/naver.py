"""네이버 금융 공개 API 커넥터: 국채 금리 / 환율 (일별, 무료, 키 불필요).

- 현재값 + 일별 히스토리를 한 엔드포인트(prices)로 수집
    GET https://m.stock.naver.com/front-api/marketIndex/prices
        ?category={bond|exchange}&reutersCode={code}&page={n}&pageSize=60
  → result: [{localTradedAt, closePrice, openPrice, highPrice, lowPrice,
              fluctuations, fluctuationsRatio, fluctuationsType{...}}, ...]
    (최신순. closePrice 등은 쉼표 포함 문자열일 수 있음)

- 국채 금리: 등락을 bp(베이시스포인트)로 계산 (금리는 %p 변화가 관례)
- 환율:     등락을 % 변화로 계산

주의: 비공식 API. 구조 변경/차단 시 깨질 수 있어 재시도 + graceful 처리.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests

_BASE = "https://m.stock.naver.com/front-api/marketIndex/prices"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://m.stock.naver.com/",
    "Accept": "application/json",
}


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _fetch_history(category: str, code: str, pages: int = 3,
                   size: int = 60) -> List[Dict]:
    """최신순 일별 히스토리. [{date: datetime, close: float}, ...] (오래된→최신 정렬)."""
    rows: List[Dict] = []
    for page in range(1, pages + 1):
        for attempt in range(3):
            try:
                r = requests.get(
                    _BASE,
                    params={"category": category, "reutersCode": code,
                            "page": page, "pageSize": size},
                    headers=_HEADERS, timeout=12,
                )
                data = r.json().get("result", [])
                break
            except Exception:  # noqa: BLE001
                data = []
        page_rows = [x for x in data if isinstance(x, dict)]
        for x in page_rows:
            dt = str(x.get("localTradedAt", ""))[:10]
            close = _to_float(x.get("closePrice"))
            if dt and close is not None:
                rows.append({"date": dt, "close": close})
        if len(page_rows) < size:
            break
    # 중복 제거 + 오래된→최신 정렬
    seen = {}
    for r in rows:
        seen[r["date"]] = r["close"]
    out = [{"date": datetime.strptime(d, "%Y-%m-%d"), "close": c}
           for d, c in seen.items()]
    out.sort(key=lambda r: r["date"])
    return out


def _value_on_or_before(series: List[Dict], target: datetime) -> Optional[float]:
    prev = None
    for r in series:
        if r["date"] <= target:
            prev = r["close"]
        else:
            break
    return prev


def _sparkline_svg(closes: List[float], up: bool, width: int = 120, height: int = 36) -> str:
    if not closes or len(closes) < 2:
        return ""
    lo, hi = min(closes), max(closes)
    rng = (hi - lo) or 1.0
    n = len(closes)
    pts = []
    for i, c in enumerate(closes):
        x = i / (n - 1) * (width - 4) + 2
        y = height - 2 - (c - lo) / rng * (height - 4)
        pts.append(f"{x:.1f},{y:.1f}")
    color = "#e5484d" if up else "#3b82f6"
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none" class="spark">'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.5" '
        f'stroke-linejoin="round" stroke-linecap="round" points="{" ".join(pts)}"/>'
        f'</svg>'
    )


def _compute_row(meta: Dict, series: List[Dict], mode: str) -> Dict:
    """mode='rate' → 등락 bp, 'fx' → 등락 %."""
    last = series[-1]
    cur = last["close"]
    last_date = last["date"]

    w1 = _value_on_or_before(series, last_date - timedelta(days=7))
    m1 = _value_on_or_before(series, last_date - timedelta(days=30))
    m3 = _value_on_or_before(series, last_date - timedelta(days=91))

    def delta(past):
        if past is None:
            return None
        if mode == "rate":
            return (cur - past) * 100.0          # %p → bp
        return (cur / past - 1.0) * 100.0 if past else None  # %

    chg_1w = delta(w1)
    spark_src = [r["close"] for r in series[-60:]]
    spark = _sparkline_svg(spark_src, up=(chg_1w or 0) >= 0)

    return {
        "group": meta["group"],
        "name": meta["name"],
        "symbol": meta["code"],
        "date": last_date.strftime("%m-%d"),
        "price": cur,
        "chg_1w": chg_1w,
        "chg_1m": delta(m1),
        "chg_3m": delta(m3),
        "chg_ytd": None,   # 금리/환율은 YTD 대신 비워둠(표에서 미표시)
        "from_52w_high": None,
        "spark": spark,
        "unit": "bp" if mode == "rate" else "%",
    }


def collect_rates(items: List[Dict]) -> List[Dict]:
    """국채 금리. items=[{group,name,code}]. 등락 bp."""
    out = []
    for meta in items:
        series = _fetch_history("bond", meta["code"])
        if not series:
            out.append(_error_row(meta))
            continue
        out.append(_compute_row(meta, series, mode="rate"))
    return out


def collect_fx(items: List[Dict]) -> List[Dict]:
    """환율. items=[{group,name,code}]. 등락 %."""
    out = []
    for meta in items:
        series = _fetch_history("exchange", meta["code"])
        if not series:
            out.append(_error_row(meta))
            continue
        out.append(_compute_row(meta, series, mode="fx"))
    return out


def _error_row(meta: Dict) -> Dict:
    return {
        "group": meta["group"], "name": meta["name"], "symbol": meta["code"],
        "date": "-", "price": None, "chg_1w": None, "chg_1m": None,
        "chg_3m": None, "chg_ytd": None, "from_52w_high": None, "spark": "",
        "unit": "", "error": True,
    }
