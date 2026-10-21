"""미국 Census International Trade API 수집기 (Finance 통합).

U.S. Census Bureau 의 월별 수출입 통계를 전체 합산(CTY_CODE='-') 기준으로
HS2/HS4/HS6 전량 수집한다. 레벨당 수입/수출 1회씩, 총 6회 호출.

- API(수입): https://api.census.gov/data/timeseries/intltrade/imports/hs
- API(수출): https://api.census.gov/data/timeseries/intltrade/exports/hs
- 응답: JSON 2차원 배열(첫 행 헤더). time 범위 필터로 60개월을 한 번에 수신.

국가별 순위는 HS 상세 진입 시 collect_country_breakdown 으로 온디맨드 수집.
"""
import datetime as dt
import os
import sqlite3
import time

import requests

from . import db

IMPORTS_URL = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
EXPORTS_URL = "https://api.census.gov/data/timeseries/intltrade/exports/hs"

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(HERE, "us_customs_workspace", "ustrade.db")
MONTHS = 60
MAX_RETRIES = 3
RETRY_WAIT = 3
REQUEST_WAIT = 0.2

FLOW = {
    "imp": {"url": IMPORTS_URL, "commodity": "I_COMMODITY", "sdesc": "I_COMMODITY_SDESC",
            "value": "GEN_VAL_MO", "qty": "GEN_QY1_MO", "unit": "UNIT_QY1"},
    "exp": {"url": EXPORTS_URL, "commodity": "E_COMMODITY", "sdesc": "E_COMMODITY_SDESC",
            "value": "ALL_VAL_MO", "qty": "QTY_1_MO", "unit": "UNIT_QY1"},
}


def load_api_key():
    key = os.environ.get("CENSUS_API_KEY")
    if key:
        return key
    env_path = os.path.join(HERE, ".env")
    if os.path.isfile(env_path):
        with open(env_path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line.startswith("CENSUS_API_KEY="):
                    return line.split("=", 1)[1]
    raise ValueError("CENSUS_API_KEY를 설정해 주세요.")


def to_int(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return 0


def _get(key, url, params):
    """Census API 호출 → 레코드(dict) 리스트. 재시도 포함."""
    params = dict(params)
    params["key"] = key
    last_err = None
    for _ in range(MAX_RETRIES):
        try:
            r = requests.get(url, params=params, timeout=120)
            if r.status_code == 204 or not r.text.strip():
                return []
            if r.text.lstrip().startswith("error"):
                last_err = r.text.strip()[:200]
                time.sleep(RETRY_WAIT)
                continue
            data = r.json()
            if not data or len(data) < 2:
                return []
            header = data[0]
            return [dict(zip(header, row)) for row in data[1:]]
        except (requests.RequestException, ValueError) as e:
            last_err = type(e).__name__
            time.sleep(RETRY_WAIT)
    raise RuntimeError(f"Census API 호출 실패: {last_err}")


def add_months(year: int, month: int, delta: int):
    idx = (year * 12 + (month - 1)) + delta
    return idx // 12, idx % 12 + 1


def time_range(start: str, end: str) -> str:
    return f"from {start} to {end}"


def detect_latest_month(key) -> str:
    today = dt.date.today()
    y, m = today.year, today.month
    for _ in range(24):
        yymm = f"{y:04d}-{m:02d}"
        rows = _get(key, IMPORTS_URL, {
            "get": FLOW["imp"]["value"], "COMM_LVL": "HS2",
            "I_COMMODITY": "85", "CTY_CODE": "-", "time": yymm,
        })
        if rows:
            return yymm
        y, m = add_months(y, m, -1)
    raise RuntimeError("최근 24개월 내 가용 데이터를 찾지 못했습니다.")


def _rows_from(resp, flow, level):
    f = FLOW[flow]
    out = []
    for r in resp:
        code = (r.get(f["commodity"]) or "").strip()
        cty = (r.get("CTY_CODE") or "").strip()
        if not code or not cty:
            continue
        out.append({
            "flow": flow, "period": (r.get("time") or "").strip(),
            "cty_code": cty, "cty_name": (r.get("CTY_NAME") or "").strip(),
            "hs_code": code, "hs_level": level,
            "descr": (r.get(f["sdesc"]) or "").strip(), "value": to_int(r.get(f["value"])),
        })
    return out


def fetch_level(key, flow, hs_code, level, start, end, country=None):
    f = FLOW[flow]
    params = {"get": f"{f['commodity']},{f['sdesc']},{f['value']},CTY_CODE,CTY_NAME",
              "COMM_LVL": f"HS{level}", "time": time_range(start, end)}
    if hs_code:
        params[f["commodity"]] = hs_code
    if country:
        params["CTY_CODE"] = country
    return _rows_from(_get(key, f["url"], params), flow, level)


def fetch_all_level(key, flow, level, start, end):
    """특정 HS 레벨(2/4/6) 전체 × 전체합산('-') × 기간범위를 한 번에 받는다."""
    f = FLOW[flow]
    params = {"get": f"{f['commodity']},{f['sdesc']},{f['value']},CTY_CODE,CTY_NAME",
              "COMM_LVL": f"HS{level}", "CTY_CODE": "-", "time": time_range(start, end)}
    rows = _rows_from(_get(key, f["url"], params), flow, level)
    return [r for r in rows if len(r["hs_code"]) == level]


def fetch_sublevel_month(key, flow, hs_prefix, level, period):
    f = FLOW[flow]
    params = {"get": f"{f['commodity']},{f['sdesc']},{f['value']},CTY_CODE,CTY_NAME",
              "COMM_LVL": f"HS{level}", "CTY_CODE": "-", "time": period}
    rows = _rows_from(_get(key, f["url"], params), flow, level)
    return [r for r in rows if r["hs_code"].startswith(hs_prefix)]


def fetch_code_series(key, flow, hs_code, level, start, end):
    f = FLOW[flow]
    params = {"get": f"{f['commodity']},{f['sdesc']},{f['value']},CTY_CODE,CTY_NAME",
              "COMM_LVL": f"HS{level}", f["commodity"]: hs_code,
              "CTY_CODE": "-", "time": time_range(start, end)}
    return _rows_from(_get(key, f["url"], params), flow, level)


def save_rows(conn, rows):
    if not rows:
        return
    conn.executemany(
        """
        INSERT OR REPLACE INTO trade_raw
            (flow, period, cty_code, cty_name, hs_code, hs_level, descr, value)
        VALUES (:flow, :period, :cty_code, :cty_name, :hs_code, :hs_level, :descr, :value)
        """,
        rows,
    )
    conn.commit()


def latest_in_db(conn):
    try:
        row = conn.execute("SELECT MAX(period) AS p FROM trade_raw").fetchone()
        return row[0] if row and row[0] else None
    except sqlite3.OperationalError:
        return None


def have_sublevel(conn, flow, hs_prefix, sublevel) -> bool:
    row = conn.execute(
        "SELECT 1 FROM trade_raw WHERE flow=? AND hs_level=? AND cty_code='-' AND hs_code LIKE ? LIMIT 1",
        (flow, sublevel, hs_prefix + "%"),
    ).fetchone()
    return row is not None


def have_series(conn, flow, hs_code, level) -> bool:
    n = conn.execute(
        "SELECT COUNT(DISTINCT period) FROM trade_raw WHERE flow=? AND hs_level=? AND cty_code='-' AND hs_code=?",
        (flow, level, hs_code),
    ).fetchone()[0]
    return n > 1


def collect_detail(conn, key, hs_prefix, sublevel, months=MONTHS, force=False):
    """드릴다운 온디맨드 수집(전체합계 '-' 기준, 양방향)."""
    latest = latest_in_db(conn) or detect_latest_month(key)
    y, m = int(latest[:4]), int(latest[5:])
    sy, sm = add_months(y, m, -(months - 1))
    start = f"{sy:04d}-{sm:02d}"
    plevel = len(hs_prefix)
    total = 0
    for flow in ("imp", "exp"):
        if force or not have_series(conn, flow, hs_prefix, plevel):
            rows = [r for r in fetch_code_series(key, flow, hs_prefix, plevel, start, latest)
                    if r["hs_code"] == hs_prefix]
            save_rows(conn, rows)
            total += len(rows)
            time.sleep(REQUEST_WAIT)
        if sublevel and sublevel <= 6 and (force or not have_sublevel(conn, flow, hs_prefix, sublevel)):
            rows = fetch_sublevel_month(key, flow, hs_prefix, sublevel, latest)
            save_rows(conn, rows)
            total += len(rows)
            time.sleep(REQUEST_WAIT)
    return total


def have_country_breakdown(conn, flow, hs_code, period) -> bool:
    row = conn.execute(
        "SELECT 1 FROM trade_raw WHERE flow=? AND hs_code=? AND period=? "
        "AND cty_code<>'-' AND cty_code NOT LIKE '0%' AND cty_code NOT LIKE '%X%' LIMIT 1",
        (flow, hs_code, period),
    ).fetchone()
    return row is not None


def collect_country_breakdown(conn, key, hs_code, period=None, force=False):
    """온디맨드: 특정 HS 코드의 '국가별' 데이터를 최근월 1개월만 수집(양방향)."""
    period = period or latest_in_db(conn) or detect_latest_month(key)
    level = len(hs_code)
    total = 0
    for flow in ("imp", "exp"):
        if not force and have_country_breakdown(conn, flow, hs_code, period):
            continue
        rows = [r for r in fetch_level(key, flow, hs_code, level, period, period)
                if r["hs_code"] == hs_code]
        save_rows(conn, rows)
        total += len(rows)
        time.sleep(REQUEST_WAIT)
    return total


def _fetch_hs10_qty(key, flow, hs6, start, end):
    """HS6 하위 HS10 의 금액·수량·단위를 기간범위로 조회(전체합산 '-').

    Census 는 HS6 집계 레벨에선 수량을 0 으로 주므로, HS10(최하위)에서 받아
    단위가 동일한 것만 HS6·월별로 합산한다. 반환: {period: (value, qty, unit)}.
    단위가 섞이면 unit='MIXED', qty 합산 생략(None).
    """
    f = FLOW[flow]
    params = {"get": f"{f['commodity']},{f['value']},{f['qty']},{f['unit']}",
              "COMM_LVL": "HS10", f["commodity"]: hs6 + "*",
              "CTY_CODE": "-", "time": time_range(start, end)}
    resp = _get(key, f["url"], params)
    # period -> {"value": v, "qty": q, "units": set()}
    acc = {}
    for r in resp:
        code = (r.get(f["commodity"]) or "").strip()
        if not code.startswith(hs6):
            continue
        period = (r.get("time") or "").strip()
        unit = (r.get(f["unit"]) or "").strip()
        val = to_int(r.get(f["value"]))
        qty = to_int(r.get(f["qty"]))
        a = acc.setdefault(period, {"value": 0, "qty": 0, "units": set()})
        a["value"] += val
        if unit and unit != "-" and qty > 0:
            a["qty"] += qty
            a["units"].add(unit)
    out = {}
    for period, a in acc.items():
        if len(a["units"]) == 1 and a["qty"] > 0:
            out[period] = (a["value"], a["qty"], next(iter(a["units"])))
        else:
            out[period] = (a["value"], None, "MIXED" if len(a["units"]) > 1 else "")
    return out


def have_unit_price(conn, flow, hs6) -> bool:
    row = conn.execute(
        "SELECT 1 FROM unit_price WHERE flow=? AND hs_code=? LIMIT 1", (flow, hs6)
    ).fetchone()
    return row is not None


def collect_unit_price(conn, key, hs6, months=MONTHS, force=False):
    """온디맨드: HS6 의 월별 단가(금액/수량)를 HS10 에서 집계해 unit_price 에 저장."""
    if len(hs6) != 6:
        return 0
    latest = latest_in_db(conn) or detect_latest_month(key)
    y, m = int(latest[:4]), int(latest[5:])
    sy, sm = add_months(y, m, -(months - 1))
    start = f"{sy:04d}-{sm:02d}"
    total = 0
    for flow in ("imp", "exp"):
        if not force and have_unit_price(conn, flow, hs6):
            continue
        series = _fetch_hs10_qty(key, flow, hs6, start, latest)
        rows = [{"flow": flow, "period": p, "hs_code": hs6,
                 "value": v, "qty": q, "unit": u}
                for p, (v, q, u) in series.items()]
        if rows:
            conn.executemany(
                "INSERT OR REPLACE INTO unit_price (flow, period, hs_code, value, qty, unit) "
                "VALUES (:flow, :period, :hs_code, :value, :qty, :unit)", rows)
            conn.commit()
            total += len(rows)
        time.sleep(REQUEST_WAIT)
    return total


def run_collection(progress=None, incremental=True, db_path=None, api_key=None, months=MONTHS):
    """HS2/HS4/HS6 전량 수집(전체 합산, 수입·수출 6회 호출)."""
    def emit(**kw):
        if progress:
            progress(kw)

    key = api_key or load_api_key()
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        db.ensure_schema(conn)

        emit(phase="detect", message="최신 가용 월 탐지 중...")
        latest = detect_latest_month(key)
        emit(phase="detected", latest=latest, message=f"최신 가용 월: {latest}")

        y, m = int(latest[:4]), int(latest[5:])
        sy, sm = add_months(y, m, -(months - 1))
        start = f"{sy:04d}-{sm:02d}"

        levels = (2, 4, 6)
        total_steps = len(levels) * 2
        emit(phase="start", total=total_steps, first=start, last=latest,
             message=f"HS2/4/6 전량 수집 ({start}~{latest}) · 총 {total_steps}회 호출")

        total = 0
        step = 0
        for level in levels:
            for flow in ("imp", "exp"):
                step += 1
                label = "수입" if flow == "imp" else "수출"
                emit(phase="month", index=step, total=total_steps,
                     message=f"[{step}/{total_steps}] HS{level} {label} 수집 중...")
                rows = fetch_all_level(key, flow, level, start, latest)
                save_rows(conn, rows)
                total += len(rows)
                emit(phase="month", index=step, total=total_steps, rows=len(rows), cumulative=total,
                     message=f"[{step}/{total_steps}] HS{level} {label}: {len(rows)} rows")

        for k, v in (
            ("latest_month", latest),
            ("collected_at", dt.datetime.now().isoformat(timespec="seconds")),
            ("range", f"{start}~{latest}"),
        ):
            conn.execute("INSERT OR REPLACE INTO collection_meta(key, value) VALUES (?, ?)", (k, v))
        conn.commit()

        cnt = conn.execute("SELECT COUNT(*) FROM trade_raw WHERE cty_code='-'").fetchone()[0]
        mn = conn.execute("SELECT MIN(period), MAX(period) FROM trade_raw").fetchone()
        summary = {"latest_month": latest, "files": total_steps, "rows_added": total,
                   "total_rows": cnt, "range": f"{mn[0]}~{mn[1]}"}
        emit(phase="done", **summary, message=f"완료. 총 {cnt} 행, 기간 {mn[0]}~{mn[1]}")
        return summary
    finally:
        conn.close()


def main():
    run_collection(progress=lambda e: print("  " + e.get("message", "")), incremental=False)


if __name__ == "__main__":
    main()
