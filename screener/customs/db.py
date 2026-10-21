"""SQLite 집계 쿼리. pandas 없이 순수 SQL + 파이썬으로 계산.

trade_raw(period, hs_code, item_name, exp_dlr, imp_dlr, exp_wgt, imp_wgt, bal_pay)
를 SUBSTR + SUM 으로 HS 2/4/6 자리로 집계한다.

지표 정의:
  YoY = (당월 - 전년동월) / 전년동월 * 100
  QoQ = 월→분기 합산 후 (당분기 - 전분기) / 전분기 * 100
"""
from __future__ import annotations

import sqlite3
from typing import Any

from .names import code_name


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create all tables, including on a fresh Finance installation."""
    conn.execute("""CREATE TABLE IF NOT EXISTS trade_raw (
        period TEXT NOT NULL, hs_code TEXT NOT NULL, item_name TEXT,
        exp_dlr INTEGER, imp_dlr INTEGER, exp_wgt INTEGER, imp_wgt INTEGER,
        bal_pay INTEGER, PRIMARY KEY (period, hs_code))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_period ON trade_raw(period)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_hs ON trade_raw(hs_code)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS related_stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hs_code TEXT NOT NULL,
            hs_level INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            country TEXT NOT NULL,
            name TEXT,
            market TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (hs_code, symbol, country)
        )
        """
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS collection_meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = conn.execute("SELECT key, value FROM collection_meta").fetchall()
        return {r["key"]: r["value"] for r in rows}
    except sqlite3.OperationalError:
        return {}


def latest_month(conn: sqlite3.Connection) -> str | None:
    meta = get_meta(conn)
    if meta.get("latest_month"):
        return meta["latest_month"]
    row = conn.execute("SELECT MAX(period) AS p FROM trade_raw").fetchone()
    return row["p"] if row and row["p"] else None


def level_summary(
    conn: sqlite3.Connection, prefix: str, level: int, period: str
) -> list[dict[str, Any]]:
    """Child HS rows with the same export/import YoY and QoQ columns as HS2."""
    out = []
    for code, series in all_series_by_level(conn, level, prefix).items():
        metrics = period_metrics(series, period)
        if metrics is not None:
            out.append({"code": code, **metrics})
    return sorted(out, key=lambda row: row["exp_dlr"], reverse=True)


def period_metrics(series: list[dict], period: str | None) -> dict | None:
    """Rates anchored to the displayed month and its exact preceding quarter."""
    if not period:
        return None
    by_month = {row["period"]: row for row in series}
    current = by_month.get(period)
    if current is None:
        return None
    year, month = int(period[:4]), int(period[4:])
    prior_month = by_month.get(f"{year - 1:04d}{month:02d}")
    quarter_start = (month - 1) // 3 * 3 + 1
    previous_year, previous_start = (year - 1, 10) if quarter_start == 1 else (year, quarter_start - 3)

    def quarter_total(y, start, end, field):
        values = [by_month[f"{y:04d}{m:02d}"][field]
                  for m in range(start, end + 1) if f"{y:04d}{m:02d}" in by_month]
        return sum(values) if values else None

    def change(value, previous):
        return (value - previous) / previous * 100 if previous not in (None, 0) else None

    result = {"exp_dlr": current["exp_dlr"], "imp_dlr": current["imp_dlr"],
              "bal": current["exp_dlr"] - current["imp_dlr"]}
    for direction in ("exp", "imp"):
        field = direction + "_dlr"
        result[direction + "_yoy"] = change(current[field], prior_month[field] if prior_month else None)
        result[direction + "_qoq"] = change(
            quarter_total(year, quarter_start, month, field),
            quarter_total(previous_year, previous_start, previous_start + 2, field))
    return result


def representative_names(conn: sqlite3.Connection, level: int) -> dict[str, str]:
    """Use workbook descriptions; fall back to the largest traded item's label."""
    sql = f"""
        WITH agg AS (
            SELECT SUBSTR(hs_code,1,{level}) AS code, item_name,
                   SUM(exp_dlr + imp_dlr) AS vol
            FROM trade_raw
            GROUP BY code, item_name
        ),
        ranked AS (
            SELECT code, item_name,
                   ROW_NUMBER() OVER (PARTITION BY code ORDER BY vol DESC) AS rn
            FROM agg
        )
        SELECT code, item_name FROM ranked WHERE rn = 1
    """
    rows = conn.execute(sql).fetchall()
    return {r["code"]: code_name(r["code"], r["item_name"]) for r in rows}


def name_for(conn: sqlite3.Connection, prefix: str) -> str:
    """Exact workbook description, with the existing API label as fallback."""
    supplied = code_name(prefix)
    if supplied:
        return supplied
    row = conn.execute(
        """
        SELECT item_name FROM trade_raw
        WHERE hs_code LIKE ?
        GROUP BY item_name
        ORDER BY SUM(exp_dlr + imp_dlr) DESC
        LIMIT 1
        """,
        (prefix + "%",),
    ).fetchone()
    return row["item_name"] if row else ""


def monthly_series(conn: sqlite3.Connection, prefix: str) -> list[dict[str, Any]]:
    """prefix 의 월별 수출/수입 합계 시계열 (오름차순)."""
    sql = """
        SELECT period,
               SUM(exp_dlr) AS exp_dlr,
               SUM(imp_dlr) AS imp_dlr
        FROM trade_raw
        WHERE hs_code LIKE ?
        GROUP BY period
        ORDER BY period
    """
    rows = conn.execute(sql, (prefix + "%",)).fetchall()
    return [
        {
            "period": r["period"],
            "exp_dlr": r["exp_dlr"] or 0,
            "imp_dlr": r["imp_dlr"] or 0,
        }
        for r in rows
    ]


def total_series(conn: sqlite3.Connection) -> list[dict]:
    """전체(모든 HS) 월별 수출/수입 합계 시계열."""
    sql = """
        SELECT period, SUM(exp_dlr) AS exp_dlr, SUM(imp_dlr) AS imp_dlr
        FROM trade_raw GROUP BY period ORDER BY period
    """
    return [
        {"period": r["period"], "exp_dlr": r["exp_dlr"] or 0, "imp_dlr": r["imp_dlr"] or 0}
        for r in conn.execute(sql)
    ]


def overview(conn: sqlite3.Connection) -> dict:
    """첫 화면용 종합 지표: 전체 시계열 + 전체 YoY/QoQ + HS2 순위(+YoY/QoQ)."""
    period = latest_month(conn)
    series = total_series(conn)
    exp_yoy = compute_yoy(series, "exp_dlr")
    imp_yoy = compute_yoy(series, "imp_dlr")
    q_exp = compute_quarterly(series, "exp_dlr")
    q_imp = compute_quarterly(series, "imp_dlr")

    # HS2 코드별: 최신월 값 + 각 코드의 YoY/QoQ
    names2 = representative_names(conn, 2)
    series2 = all_series_by_level(conn, 2)
    rows = []
    for code, s in series2.items():
        metrics = period_metrics(s, period)
        if metrics is not None:
            rows.append({"code": code, "name": names2.get(code, ""), **metrics})
    rows.sort(key=lambda r: r["exp_dlr"], reverse=True)

    last = series[-1] if series else {"exp_dlr": 0, "imp_dlr": 0}
    return {
        "period": period,
        "series": series,
        "expYoy": exp_yoy,
        "impYoy": imp_yoy,
        "qExp": q_exp,
        "qImp": q_imp,
        "totals": {
            "exp_dlr": last["exp_dlr"], "imp_dlr": last["imp_dlr"],
            "bal": last["exp_dlr"] - last["imp_dlr"],
            "exp_yoy": exp_yoy[-1]["yoy"] if exp_yoy else None,
            "imp_yoy": imp_yoy[-1]["yoy"] if imp_yoy else None,
            "exp_qoq": q_exp[-1]["qoq"] if q_exp else None,
            "imp_qoq": q_imp[-1]["qoq"] if q_imp else None,
            "hs2_count": len(rows),
        },
        "hs2": rows,
    }


def all_series_by_level(conn: sqlite3.Connection, level: int, prefix: str = "") -> dict[str, list[dict]]:
    """레벨의 모든 코드에 대한 월별 시계열을 단일 쿼리로 계산.

    반환: {code: [{period, exp_dlr, imp_dlr}, ...(오름차순)]}
    """
    sql = f"""
        SELECT SUBSTR(hs_code,1,{level}) AS code, period,
               SUM(exp_dlr) AS exp_dlr, SUM(imp_dlr) AS imp_dlr
        FROM trade_raw
        WHERE hs_code LIKE ?
        GROUP BY code, period
        ORDER BY code, period
    """
    out: dict[str, list[dict]] = {}
    for r in conn.execute(sql, (prefix + "%",)):
        out.setdefault(r["code"], []).append(
            {"period": r["period"], "exp_dlr": r["exp_dlr"] or 0, "imp_dlr": r["imp_dlr"] or 0}
        )
    return out


def all_companies(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """hs_code 별 관련 종목 매핑."""
    out: dict[str, list[dict]] = {}
    for r in conn.execute(
        "SELECT id, hs_code, symbol, country, name, market, created_at FROM related_stocks ORDER BY created_at"
    ):
        out.setdefault(r["hs_code"], []).append(
            {"id": r["id"], "symbol": r["symbol"], "country": r["country"],
             "name": r["name"], "market": r["market"], "created_at": r["created_at"]}
        )
    return out


# ----------------------------- 지표 계산 -----------------------------
def compute_yoy(series: list[dict], field: str) -> list[dict]:
    """각 월에 대해 전년동월 대비 증감률(%)을 붙여 반환."""
    by_period = {row["period"]: row[field] for row in series}
    out = []
    for row in series:
        p = row["period"]
        y, m = int(p[:4]), int(p[4:])
        prev_key = f"{y-1:04d}{m:02d}"
        prev = by_period.get(prev_key)
        cur = row[field]
        yoy = None
        if prev not in (None, 0):
            yoy = (cur - prev) / prev * 100
        out.append({"period": p, "value": cur, "yoy": yoy})
    return out


def compute_quarterly(series: list[dict], field: str) -> list[dict]:
    """월 시계열을 분기 합산으로 변환하고 QoQ(%)를 계산."""
    buckets: dict[tuple[int, int], int] = {}
    for row in series:
        p = row["period"]
        y, m = int(p[:4]), int(p[4:])
        q = (m - 1) // 3 + 1
        buckets[(y, q)] = buckets.get((y, q), 0) + row[field]
    keys = sorted(buckets.keys())
    out = []
    prev_val = None
    for (y, q) in keys:
        val = buckets[(y, q)]
        qoq = None
        if prev_val not in (None, 0):
            qoq = (val - prev_val) / prev_val * 100
        out.append({"label": f"{y} Q{q}", "value": val, "qoq": qoq})
        prev_val = val
    return out


# ----------------------------- 관련 종목 -----------------------------
def list_companies(conn: sqlite3.Connection, hs_code: str) -> list[dict]:
    """HS 코드에 연결된 관련 종목 목록."""
    rows = conn.execute(
        "SELECT id, symbol, country, name, market, created_at FROM related_stocks "
        "WHERE hs_code = ? ORDER BY created_at",
        (hs_code,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_company(
    conn: sqlite3.Connection, hs_code: str, hs_level: int,
    symbol: str, country: str, name: str, market: str, created_at: str
) -> None:
    """HS 코드에 종목을 연결(중복 무시)."""
    conn.execute(
        "INSERT OR IGNORE INTO related_stocks "
        "(hs_code, hs_level, symbol, country, name, market, created_at) VALUES (?,?,?,?,?,?,?)",
        (hs_code, hs_level, symbol, country, name, market, created_at),
    )
    conn.commit()


def delete_company(conn: sqlite3.Connection, cid: int) -> None:
    conn.execute("DELETE FROM related_stocks WHERE id = ?", (cid,))
    conn.commit()
