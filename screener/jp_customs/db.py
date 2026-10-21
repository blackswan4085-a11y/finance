"""SQLite 집계 쿼리. pandas 없이 순수 SQL + 파이썬으로 계산.

trade_hs(flow, period, hs_code, hs_level, value)  — 세계 합계(천엔), 레벨별 사전 집계됨
trade_country(flow, period, hs_code, cty_code, cty_name, value) — 국가별(온디맨드)

미국판과의 차이:
  - trade_hs 는 이미 레벨(2/4/6)별로 집계되어 있어 SUBSTR 집계가 불필요.
  - 금액 단위는 '천 엔'. 프런트에서 '엔' 혹은 '억엔' 으로 표기.
  - 전 세계 합계가 CSV 에 이미 계산돼 있어 국가 합산이 필요 없음.
  - 국가별은 trade_country(온디맨드)에서 순위만 제공.

지표 정의(미국판과 동일):
  YoY = (당월 - 전년동월) / 전년동월 * 100
  QoQ = 월→분기 합산 후 (당분기 - 전분기) / 전분기 * 100
"""
from __future__ import annotations

import sqlite3
from typing import Any


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_hs (
            flow      TEXT NOT NULL,     -- 'imp' | 'exp'
            period    TEXT NOT NULL,     -- YYYY-MM
            hs_code   TEXT NOT NULL,     -- HS 2/4/6자리
            hs_level  INTEGER NOT NULL,  -- 2 | 4 | 6
            value     INTEGER,           -- 금액(천 엔) — 세계 합계
            PRIMARY KEY (flow, period, hs_code)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS related_stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hs_code TEXT NOT NULL, hs_level INTEGER NOT NULL,
            symbol TEXT NOT NULL, country TEXT NOT NULL, name TEXT, market TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (hs_code, symbol, country)
        )
        """
    )
    conn.execute("CREATE TABLE IF NOT EXISTS collection_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_country (
            flow TEXT NOT NULL, period TEXT NOT NULL, hs_code TEXT NOT NULL,
            cty_code TEXT NOT NULL, cty_name TEXT, value INTEGER,
            PRIMARY KEY (flow, period, hs_code, cty_code)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jphs_period ON trade_hs(period)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jphs_code ON trade_hs(hs_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jphs_level ON trade_hs(hs_level)")
    conn.commit()


def get_meta(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM collection_meta")}
    except sqlite3.OperationalError:
        return {}


def latest_month(conn: sqlite3.Connection) -> str | None:
    meta = get_meta(conn)
    if meta.get("latest_month"):
        return meta["latest_month"]
    row = conn.execute("SELECT MAX(period) AS p FROM trade_hs").fetchone()
    return row["p"] if row and row["p"] else None


# ----------------------------- 레벨 집계 -----------------------------
def level_summary(conn: sqlite3.Connection, prefix: str, level: int, period: str) -> list[dict[str, Any]]:
    """prefix 하위 level 자리 그룹을 특정 월 기준 수출·수입 피벗."""
    sql = """
        SELECT hs_code AS code,
               SUM(CASE WHEN flow='exp' THEN value ELSE 0 END) AS exp_v,
               SUM(CASE WHEN flow='imp' THEN value ELSE 0 END) AS imp_v
        FROM trade_hs
        WHERE period = ? AND hs_level = ? AND hs_code LIKE ?
        GROUP BY code
        ORDER BY exp_v DESC
    """
    rows = conn.execute(sql, (period, level, prefix + "%")).fetchall()
    out = []
    for r in rows:
        exp, imp = r["exp_v"] or 0, r["imp_v"] or 0
        out.append({"code": r["code"], "name": "", "exp_dlr": exp, "imp_dlr": imp, "bal": exp - imp})
    return out


def monthly_series(conn: sqlite3.Connection, prefix: str) -> list[dict[str, Any]]:
    """prefix(정확 레벨) 의 월별 수출/수입 시계열."""
    sql = """
        SELECT period,
               SUM(CASE WHEN flow='exp' THEN value ELSE 0 END) AS exp_v,
               SUM(CASE WHEN flow='imp' THEN value ELSE 0 END) AS imp_v
        FROM trade_hs
        WHERE hs_code = ? AND hs_level = ?
        GROUP BY period ORDER BY period
    """
    rows = conn.execute(sql, (prefix, len(prefix))).fetchall()
    return [{"period": r["period"], "exp_dlr": r["exp_v"] or 0, "imp_dlr": r["imp_v"] or 0} for r in rows]


def total_series(conn: sqlite3.Connection) -> list[dict]:
    """전체(HS2 모든 코드) 월별 수출/수입 시계열."""
    sql = """
        SELECT period,
               SUM(CASE WHEN flow='exp' THEN value ELSE 0 END) AS exp_v,
               SUM(CASE WHEN flow='imp' THEN value ELSE 0 END) AS imp_v
        FROM trade_hs WHERE hs_level = 2 GROUP BY period ORDER BY period
    """
    return [{"period": r["period"], "exp_dlr": r["exp_v"] or 0, "imp_dlr": r["imp_v"] or 0} for r in conn.execute(sql)]


def all_series_by_hs2(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    sql = """
        SELECT hs_code AS code, period,
               SUM(CASE WHEN flow='exp' THEN value ELSE 0 END) AS exp_v,
               SUM(CASE WHEN flow='imp' THEN value ELSE 0 END) AS imp_v
        FROM trade_hs WHERE hs_level = 2 GROUP BY code, period ORDER BY code, period
    """
    out: dict[str, list[dict]] = {}
    for r in conn.execute(sql):
        out.setdefault(r["code"], []).append(
            {"period": r["period"], "exp_dlr": r["exp_v"] or 0, "imp_dlr": r["imp_v"] or 0}
        )
    return out


def name_for(conn: sqlite3.Connection, prefix: str) -> str:
    """HS 품목명. e-Stat 품별표에는 라벨이 없어 내장 HS 사전에서 조회."""
    from .hsnames import hs_name
    return hs_name(prefix)


def overview(conn: sqlite3.Connection) -> dict:
    period = latest_month(conn)
    series = total_series(conn)
    exp_yoy = compute_yoy(series, "exp_dlr")
    imp_yoy = compute_yoy(series, "imp_dlr")
    q_exp = compute_quarterly(series, "exp_dlr")
    q_imp = compute_quarterly(series, "imp_dlr")

    from .hsnames import hs_name
    series2 = all_series_by_hs2(conn)
    rows = []
    for code, s in series2.items():
        cur = next((x for x in s if x["period"] == period), (s[-1] if s else {"exp_dlr": 0, "imp_dlr": 0}))
        ey = compute_yoy(s, "exp_dlr")
        iy = compute_yoy(s, "imp_dlr")
        qe = compute_quarterly(s, "exp_dlr")
        rows.append({
            "code": code, "name": hs_name(code),
            "exp_dlr": cur["exp_dlr"], "imp_dlr": cur["imp_dlr"],
            "bal": cur["exp_dlr"] - cur["imp_dlr"],
            "exp_yoy": ey[-1]["yoy"] if ey else None,
            "imp_yoy": iy[-1]["yoy"] if iy else None,
            "exp_qoq": qe[-1]["qoq"] if qe else None,
        })
    rows.sort(key=lambda r: r["exp_dlr"], reverse=True)

    last = series[-1] if series else {"exp_dlr": 0, "imp_dlr": 0}
    return {
        "period": period, "series": series,
        "expYoy": exp_yoy, "impYoy": imp_yoy, "qExp": q_exp, "qImp": q_imp,
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


# ----------------------------- 국가별 (trade_country) -----------------------------
def country_breakdown(conn: sqlite3.Connection, hs6: str, flow: str = "imp", top: int = 15) -> list[dict]:
    """특정 HS6 의 국가별 금액 순위(trade_country 에 수집돼 있을 때)."""
    from .areanames import area_name
    rows = conn.execute(
        """
        SELECT cty_code, cty_name, SUM(value) AS v
        FROM trade_country WHERE hs_code = ? AND flow = ?
        GROUP BY cty_code ORDER BY v DESC LIMIT ?
        """,
        (hs6, flow, top),
    ).fetchall()
    return [{"code": r["cty_code"], "name": r["cty_name"] or area_name(r["cty_code"]), "value": r["v"] or 0} for r in rows]


def has_country(conn: sqlite3.Connection, hs6: str) -> bool:
    return conn.execute("SELECT 1 FROM trade_country WHERE hs_code=? LIMIT 1", (hs6,)).fetchone() is not None


# ----------------------------- 지표 계산 -----------------------------
def compute_yoy(series: list[dict], field: str) -> list[dict]:
    by_period = {row["period"]: row[field] for row in series}
    out = []
    for row in series:
        p = row["period"]
        y, m = int(p[:4]), int(p[5:])
        prev = by_period.get(f"{y-1:04d}-{m:02d}")
        cur = row[field]
        yoy = (cur - prev) / prev * 100 if prev not in (None, 0) else None
        out.append({"period": p, "value": cur, "yoy": yoy})
    return out


def compute_quarterly(series: list[dict], field: str) -> list[dict]:
    buckets: dict[tuple[int, int], int] = {}
    for row in series:
        p = row["period"]
        y, m = int(p[:4]), int(p[5:])
        q = (m - 1) // 3 + 1
        buckets[(y, q)] = buckets.get((y, q), 0) + row[field]
    out = []
    prev_val = None
    for (y, q) in sorted(buckets.keys()):
        val = buckets[(y, q)]
        qoq = (val - prev_val) / prev_val * 100 if prev_val not in (None, 0) else None
        out.append({"label": f"{y} Q{q}", "value": val, "qoq": qoq})
        prev_val = val
    return out


# ----------------------------- 관련 종목 -----------------------------
def list_companies(conn: sqlite3.Connection, hs_code: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, symbol, country, name, market, created_at FROM related_stocks "
        "WHERE hs_code = ? ORDER BY created_at",
        (hs_code,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_company(conn, hs_code, hs_level, symbol, country, name, market, created_at) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO related_stocks "
        "(hs_code, hs_level, symbol, country, name, market, created_at) VALUES (?,?,?,?,?,?,?)",
        (hs_code, hs_level, symbol, country, name, market, created_at),
    )
    conn.commit()


def delete_company(conn, cid) -> None:
    conn.execute("DELETE FROM related_stocks WHERE id = ?", (cid,))
    conn.commit()
