"""SQLite 집계 쿼리. pandas 없이 순수 SQL + 파이썬으로 계산.

trade_raw(flow, period, cty_code, cty_name, hs_code, hs_level, descr, value)
를 흐름(수입/수출)·국가·HS 레벨로 집계한다.

한국판과의 차이:
  - 수출/수입이 별도 flow('exp'/'imp') 행으로 저장되므로 CASE WHEN 으로 피벗
  - 국가 차원(cty_code)이 있어 선택적으로 필터 가능
  - HS 레벨은 수집 시점에 확정된 hs_level 로 구분(SUBSTR 집계 불필요)

지표 정의(한국판과 동일):
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
    """원본/관련기업/메타 테이블이 없으면 생성."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_raw (
            flow      TEXT NOT NULL,     -- 'imp' | 'exp'
            period    TEXT NOT NULL,     -- YYYY-MM
            cty_code  TEXT NOT NULL,     -- Census 국가코드 ('-' = 전체합계)
            cty_name  TEXT,
            hs_code   TEXT NOT NULL,     -- HS 2/4/6자리
            hs_level  INTEGER NOT NULL,  -- 2 | 4 | 6
            descr     TEXT,              -- 품목 간이설명(SDESC)
            value     INTEGER,           -- 금액(USD)
            PRIMARY KEY (flow, period, cty_code, hs_code)
        )
        """
    )
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
    conn.execute("CREATE TABLE IF NOT EXISTS collection_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_period ON trade_raw(period)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_hs ON trade_raw(hs_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_level ON trade_raw(hs_level)")
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


def _cty_clause(country: str | None):
    """국가 필터 SQL 조각과 파라미터.

    - 특정 국가 선택: 그 cty_code 행만.
    - 전체(None/''): Census 가 제공하는 전체합계 행('-')만 사용한다.
      (개별 국가 + 지역/경제권 집계가 함께 저장돼 있어, 단순 SUM 하면
       중복 합산되어 금액이 크게 부풀려지므로 '-' 행을 그대로 쓴다.)
    """
    if country:
        return "AND cty_code = ?", [country]
    return "AND cty_code = '-'", []


# Census 는 개별 국가 외에 지역/경제권 집계 코드도 반환한다.
#   '-'            : 전체합계(TOTAL FOR ALL COUNTRIES)
#   '0xxx'         : 경제권 집계 (EU, OECD, APEC, ASEAN, NAFTA ...)
#   'nXXX'(X 포함) : 대륙 집계 (1XXX 북미, 4XXX 유럽, 5XXX 아시아 ...)
# 아래 조건은 "개별 국가만" 남긴다 (4자리 숫자 & 0으로 시작하지 않음).
_INDIVIDUAL_CTY_SQL = (
    "cty_code <> '-' AND cty_code NOT LIKE '0%' AND cty_code NOT LIKE '%X%'"
)


def is_aggregate_cty(code: str) -> bool:
    """지역/경제권 등 집계 코드면 True (개별 국가가 아님)."""
    return (not code) or code == "-" or code.startswith("0") or "X" in code.upper()


# ----------------------------- 국가 목록 -----------------------------
def country_list(conn: sqlite3.Connection, level: int = 2) -> list[dict]:
    """데이터에 존재하는 개별 국가 목록(교역액 큰 순). 집계 코드는 제외."""
    sql = f"""
        SELECT cty_code, cty_name, SUM(value) AS vol
        FROM trade_raw
        WHERE hs_level = {level} AND {_INDIVIDUAL_CTY_SQL}
        GROUP BY cty_code
        ORDER BY vol DESC
    """
    return [
        {"code": r["cty_code"], "name": r["cty_name"], "vol": r["vol"] or 0}
        for r in conn.execute(sql)
    ]


# ----------------------------- 레벨 집계 -----------------------------
def level_summary(
    conn: sqlite3.Connection, prefix: str, level: int, period: str,
    country: str | None = None,
) -> list[dict[str, Any]]:
    """prefix 하위의 level 자리 그룹을 특정 월 기준 수출·수입 피벗 집계.

    수출/수입을 CASE WHEN 으로 한 행에 모아 반환(한국판 표와 동일 모양).
    """
    cty_sql, cty_params = _cty_clause(country)
    sql = f"""
        SELECT hs_code AS code,
               SUM(CASE WHEN flow='exp' THEN value ELSE 0 END) AS exp_dlr,
               SUM(CASE WHEN flow='imp' THEN value ELSE 0 END) AS imp_dlr,
               MAX(descr) AS descr
        FROM trade_raw
        WHERE period = ? AND hs_level = ? AND hs_code LIKE ? {cty_sql}
        GROUP BY code
        ORDER BY exp_dlr DESC
    """
    params = [period, level, prefix + "%"] + cty_params
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        exp, imp = r["exp_dlr"] or 0, r["imp_dlr"] or 0
        out.append({
            "code": r["code"], "name": r["descr"] or "",
            "exp_dlr": exp, "imp_dlr": imp, "bal": exp - imp,
        })
    return out


def name_for(conn: sqlite3.Connection, prefix: str) -> str:
    """단일 코드의 대표 품목명(SDESC)."""
    row = conn.execute(
        """
        SELECT descr FROM trade_raw
        WHERE hs_code = ? AND descr <> ''
        GROUP BY descr
        ORDER BY SUM(value) DESC
        LIMIT 1
        """,
        (prefix,),
    ).fetchone()
    if row and row["descr"]:
        return row["descr"]
    # prefix 하위 중 대표
    row = conn.execute(
        """
        SELECT descr FROM trade_raw
        WHERE hs_code LIKE ? AND descr <> ''
        GROUP BY descr
        ORDER BY SUM(value) DESC
        LIMIT 1
        """,
        (prefix + "%",),
    ).fetchone()
    return row["descr"] if row else ""


def monthly_series(
    conn: sqlite3.Connection, prefix: str, country: str | None = None,
) -> list[dict[str, Any]]:
    """prefix 의 월별 수출/수입 합계 시계열 (오름차순).

    해당 prefix 정확 레벨 행이 있으면 그걸로, 없으면(HS2 등 상위) 같은 레벨 집계.
    """
    cty_sql, cty_params = _cty_clause(country)
    sql = f"""
        SELECT period,
               SUM(CASE WHEN flow='exp' THEN value ELSE 0 END) AS exp_dlr,
               SUM(CASE WHEN flow='imp' THEN value ELSE 0 END) AS imp_dlr
        FROM trade_raw
        WHERE hs_code = ? AND hs_level = ? {cty_sql}
        GROUP BY period
        ORDER BY period
    """
    params = [prefix, len(prefix)] + cty_params
    rows = conn.execute(sql, params).fetchall()
    return [
        {"period": r["period"], "exp_dlr": r["exp_dlr"] or 0, "imp_dlr": r["imp_dlr"] or 0}
        for r in rows
    ]


def total_series(conn: sqlite3.Connection, country: str | None = None) -> list[dict]:
    """전체(HS2 모든 코드) 월별 수출/수입 합계 시계열."""
    cty_sql, cty_params = _cty_clause(country)
    sql = f"""
        SELECT period,
               SUM(CASE WHEN flow='exp' THEN value ELSE 0 END) AS exp_dlr,
               SUM(CASE WHEN flow='imp' THEN value ELSE 0 END) AS imp_dlr
        FROM trade_raw
        WHERE hs_level = 2 {cty_sql}
        GROUP BY period
        ORDER BY period
    """
    params = cty_params
    return [
        {"period": r["period"], "exp_dlr": r["exp_dlr"] or 0, "imp_dlr": r["imp_dlr"] or 0}
        for r in conn.execute(sql, params)
    ]


def all_series_by_hs2(conn: sqlite3.Connection, country: str | None = None) -> dict[str, list[dict]]:
    """HS2 각 코드의 월별 시계열. {code: [{period, exp_dlr, imp_dlr}, ...]}"""
    cty_sql, cty_params = _cty_clause(country)
    sql = f"""
        SELECT hs_code AS code, period,
               SUM(CASE WHEN flow='exp' THEN value ELSE 0 END) AS exp_dlr,
               SUM(CASE WHEN flow='imp' THEN value ELSE 0 END) AS imp_dlr
        FROM trade_raw
        WHERE hs_level = 2 {cty_sql}
        GROUP BY code, period
        ORDER BY code, period
    """
    out: dict[str, list[dict]] = {}
    for r in conn.execute(sql, cty_params):
        out.setdefault(r["code"], []).append(
            {"period": r["period"], "exp_dlr": r["exp_dlr"] or 0, "imp_dlr": r["imp_dlr"] or 0}
        )
    return out


def hs2_names(conn: sqlite3.Connection) -> dict[str, str]:
    """HS2 코드 → 대표 설명."""
    rows = conn.execute(
        """
        SELECT hs_code, descr FROM (
            SELECT hs_code, descr, SUM(value) AS v
            FROM trade_raw WHERE hs_level = 2 AND descr <> ''
            GROUP BY hs_code, descr
            ORDER BY v DESC
        ) GROUP BY hs_code
        """
    ).fetchall()
    return {r["hs_code"]: r["descr"] for r in rows}


def overview(conn: sqlite3.Connection, country: str | None = None) -> dict:
    """첫 화면용 종합 지표: 전체 시계열 + 전체 YoY/QoQ + HS2 순위(+YoY/QoQ)."""
    period = latest_month(conn)
    series = total_series(conn, country)
    exp_yoy = compute_yoy(series, "exp_dlr")
    imp_yoy = compute_yoy(series, "imp_dlr")
    q_exp = compute_quarterly(series, "exp_dlr")
    q_imp = compute_quarterly(series, "imp_dlr")

    names2 = hs2_names(conn)
    series2 = all_series_by_hs2(conn, country)
    rows = []
    for code, s in series2.items():
        cur = next((x for x in s if x["period"] == period),
                   (s[-1] if s else {"exp_dlr": 0, "imp_dlr": 0}))
        ey = compute_yoy(s, "exp_dlr")
        iy = compute_yoy(s, "imp_dlr")
        qe = compute_quarterly(s, "exp_dlr")
        rows.append({
            "code": code, "name": names2.get(code, ""),
            "exp_dlr": cur["exp_dlr"], "imp_dlr": cur["imp_dlr"],
            "bal": cur["exp_dlr"] - cur["imp_dlr"],
            "exp_yoy": ey[-1]["yoy"] if ey else None,
            "imp_yoy": iy[-1]["yoy"] if iy else None,
            "exp_qoq": qe[-1]["qoq"] if qe else None,
        })
    rows.sort(key=lambda r: r["exp_dlr"], reverse=True)

    last = series[-1] if series else {"exp_dlr": 0, "imp_dlr": 0}
    return {
        "period": period,
        "country": country or "",
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


def country_breakdown(
    conn: sqlite3.Connection, prefix: str, period: str, flow: str = "imp", top: int = 15,
) -> list[dict]:
    """특정 HS 코드의 국가별 교역액 순위(미국판 고유 기능)."""
    level = len(prefix)
    sql = f"""
        SELECT cty_code, cty_name, SUM(value) AS val
        FROM trade_raw
        WHERE period = ? AND flow = ? AND hs_level = ? AND hs_code = ?
              AND {_INDIVIDUAL_CTY_SQL}
        GROUP BY cty_code
        ORDER BY val DESC
        LIMIT ?
    """
    rows = conn.execute(sql, (period, flow, level, prefix, top)).fetchall()
    return [
        {"code": r["cty_code"], "name": r["cty_name"], "value": r["val"] or 0}
        for r in rows
    ]


def all_companies(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in conn.execute(
        "SELECT id, hs_code, symbol, country, name, market, created_at FROM related_stocks ORDER BY created_at"
    ):
        out.setdefault(r["hs_code"], []).append(
            {"id": r["id"], "symbol": r["symbol"], "country": r["country"],
             "name": r["name"], "market": r["market"], "created_at": r["created_at"]}
        )
    return out


# ----------------------------- 지표 계산 (한국판과 동일) -----------------------------
def compute_yoy(series: list[dict], field: str) -> list[dict]:
    """각 월에 대해 전년동월 대비 증감률(%)을 붙여 반환. period 는 'YYYY-MM'."""
    by_period = {row["period"]: row[field] for row in series}
    out = []
    for row in series:
        p = row["period"]
        y, m = int(p[:4]), int(p[5:])
        prev_key = f"{y-1:04d}-{m:02d}"
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
        y, m = int(p[:4]), int(p[5:])
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
    conn.execute(
        "INSERT OR IGNORE INTO related_stocks "
        "(hs_code, hs_level, symbol, country, name, market, created_at) VALUES (?,?,?,?,?,?,?)",
        (hs_code, hs_level, symbol, country, name, market, created_at),
    )
    conn.commit()


def delete_company(conn: sqlite3.Connection, cid: int) -> None:
    conn.execute("DELETE FROM related_stocks WHERE id = ?", (cid,))
    conn.commit()
