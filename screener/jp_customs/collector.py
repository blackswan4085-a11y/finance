"""일본 재무성 무역통계(e-Stat) 수집기.

두 가지 소스를 사용한다.

1) 統計品別表(세계 합계) — 기본 수집 (collector 의 run_collection)
   - 국가 구분이 없는 'HS 품목별 전 세계 수출입 합계' 표. e-Stat 에서 CSV 파일로 제공된다.
   - getDataCatalog API 로 연도별 CSV 다운로드 URL 을 얻어 내려받고,
     HS 9자리를 HS6 로 집계하여 SQLite(trade_hs) 에 저장한다.
   - CSV 컬럼: Exp or Imp, Year, HS, Unit1/2, Quantity*-Year, Value-Year,
     Quantity*-Jan..Dec, Value-Jan..Dec  (금액 단위: 천 엔)

2) 品別国別表(국가별) — 국가별 순위용 온디맨드 (collect_country_breakdown)
   - getStatsData API(DB 제공)로 특정 HS6 의 국가별 금액을 조회.

부호화: CSV 는 헤더/데이터 모두 ASCII(숫자·영문)라 인코딩 변환 불필요.
금액 단위는 천 엔이며, 저장 시 '엔' 으로 환산(×1000)하지 않고 천엔 원값을 보관한다.
"""
import csv
import datetime as dt
import io
import os
import sqlite3
import time

import requests

from . import db

BASE = "https://api.e-stat.go.jp/rest/3.0/app/json"
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(HERE, "jp_customs_workspace", "jptrade.db")
STATS_CODE = "00350300"  # 普通貿易統計
YEARS = 5
MAX_RETRIES = 3
RETRY_WAIT = 3
REQUEST_WAIT = 0.2

# 統計品別表(세계합계) getStatsData 가 아닌 파일(CSV) 제공 → getDataCatalog 로 URL 획득.
# 品別国別表(국가별) 는 getStatsData 로 조회 (국가별 순위 온디맨드).
# 국가별 품별국별표 statsDataId (연도 묶음) — 국가별 순위 온디맨드에 사용.
KOKUBETSU = {
    "exp": {"recent": "0004049306", "range": "0003425293"},  # 2026 / 2021~2025
    "imp": {"recent": "0004049326", "range": "0003425294"},
}
FLOW_LABEL = {"exp": "輸出", "imp": "輸入"}
# CSV 'Exp or Imp' 값: 1=輸出, 2=輸入
FLOW_CSV_CODE = {"1": "exp", "2": "imp"}

MONTH_COLS = [
    "Value-Jan", "Value-Feb", "Value-Mar", "Value-Apr", "Value-May", "Value-Jun",
    "Value-Jul", "Value-Aug", "Value-Sep", "Value-Oct", "Value-Nov", "Value-Dec",
]
# 단가용 수량1(Unit1 기준) 월별 컬럼. Value 컬럼과 같은 순서(1~12월).
QTY_COLS = [
    "Quantity1-Jan", "Quantity1-Feb", "Quantity1-Mar", "Quantity1-Apr", "Quantity1-May", "Quantity1-Jun",
    "Quantity1-Jul", "Quantity1-Aug", "Quantity1-Sep", "Quantity1-Oct", "Quantity1-Nov", "Quantity1-Dec",
]


def load_app_id():
    v = os.environ.get("ESTAT_APP_ID")
    if v:
        return v
    env_path = os.path.join(HERE, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ESTAT_APP_ID="):
                    return line.split("=", 1)[1]
    raise RuntimeError("ESTAT_APP_ID not found in environment or .env")


def init_db(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_hs (
            flow      TEXT NOT NULL,     -- 'imp' | 'exp'
            period    TEXT NOT NULL,     -- YYYY-MM
            hs_code   TEXT NOT NULL,     -- HS 코드 (2/4/6자리)
            hs_level  INTEGER NOT NULL,  -- 2 | 4 | 6
            value     INTEGER,           -- 금액(천 엔) — 세계 합계
            PRIMARY KEY (flow, period, hs_code)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_country (
            flow      TEXT NOT NULL,
            period    TEXT NOT NULL,     -- YYYY-MM (국가별은 최근월만 저장)
            hs_code   TEXT NOT NULL,     -- HS6
            cty_code  TEXT NOT NULL,     -- e-Stat area 코드
            cty_name  TEXT,
            value     INTEGER,           -- 금액(천 엔)
            PRIMARY KEY (flow, period, hs_code, cty_code)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS related_companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hs_code TEXT NOT NULL,
            hs_level INTEGER NOT NULL,
            company TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE TABLE IF NOT EXISTS collection_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hs_period ON trade_hs(period)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hs_code ON trade_hs(hs_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hs_level ON trade_hs(hs_level)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ctry_code ON trade_country(hs_code)")
    conn.commit()


def to_int(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return 0


def _get_json(params):
    """e-Stat JSON API 호출 (getDataCatalog/getStatsData 등). 재시도 포함."""
    last_err = None
    for _ in range(MAX_RETRIES):
        try:
            r = requests.get(params["_url"], params={k: v for k, v in params.items() if k != "_url"}, timeout=120)
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last_err = str(e)
            time.sleep(RETRY_WAIT)
    raise RuntimeError(f"e-Stat API 실패: {last_err}")


# ----------------------------- 統計品別表 CSV (세계 합계) -----------------------------
def catalog_csv_urls(app_id):
    """統計品別表(세계합계) 수출/수입의 연도별 CSV 다운로드 URL 목록.

    반환: {flow: {year(int): url}}  (연간완결분=12월, 진행중 연도는 최신월)
    """
    out = {"exp": {}, "imp": {}}
    # updatedDate 는 '데이터 갱신일' 범위이며 미래 날짜는 102 에러가 난다.
    # 과거 CSV 도 매년 재게시되므로 넓은 과거~오늘 범위로 조회하면 과거 연도분까지 나온다.
    today = dt.date.today().strftime("%Y%m%d")
    for flow in ("exp", "imp"):
        kw = f"統計品別表 {FLOW_LABEL[flow]}"
        data = _get_json({
            "_url": f"{BASE}/getDataCatalog",
            "appId": app_id,
            "statsCode": STATS_CODE,
            "searchWord": kw,
            "limit": 100,
            "updatedDate": f"20150101-{today}",
        })
        items = data["GET_DATA_CATALOG"]["DATA_CATALOG_LIST_INF"]["DATA_CATALOG_INF"]
        if isinstance(items, dict):
            items = [items]
        # 연도별 최적 파일 선택: 같은 연도에 여러 월이 있으면 가장 큰 월(=최신 누적)
        best = {}  # year -> (survey_date_int, url)
        for it in items:
            t = it["DATASET"]["TITLE"]
            if t.get("TABULATION_SUB_CATEGORY1") != "統計品別表":
                continue
            if t.get("TABULATION_SUB_CATEGORY2") != FLOW_LABEL[flow]:
                continue
            sd = str(t.get("SURVEY_DATE") or "")
            if len(sd) != 6:
                continue
            year = int(sd[:4])
            res = it["RESOURCES"]["RESOURCE"]
            if isinstance(res, dict):
                res = [res]
            csv_res = [r for r in res if r.get("FORMAT") == "CSV"]
            if not csv_res:
                continue
            sd_int = int(sd)
            if year not in best or sd_int > best[year][0]:
                best[year] = (sd_int, csv_res[0]["URL"])
        out[flow] = {y: v[1] for y, v in best.items()}
    return out


def download_csv(url, app_id):
    """CSV 다운로드 → 텍스트. file-download URL 에 appId 를 붙인다."""
    sep = "&" if "?" in url else "?"
    full = f"{url}{sep}appId={app_id}"
    last_err = None
    for _ in range(MAX_RETRIES):
        try:
            r = requests.get(full, timeout=180)
            r.encoding = "utf-8"
            text = r.text
            if "Exp or Imp" in text[:200] or "Value-" in text[:2000]:
                return text
            last_err = f"unexpected CSV head: {text[:120]!r}"
            time.sleep(RETRY_WAIT)
        except requests.RequestException as e:
            last_err = str(e)
            time.sleep(RETRY_WAIT)
    raise RuntimeError(f"CSV 다운로드 실패({url}): {last_err}")


def clean_hs(raw):
    """CSV HS 값 정리: 선행 작은따옴표 제거, 공백 제거."""
    return (raw or "").strip().lstrip("'").strip()


def parse_hs_csv(text, year):
    """統計品別表 CSV 텍스트를 파싱해 HS6 집계 월별 레코드 생성.

    HS 9자리 → 앞 6자리로 집계(합산). 월별 금액(Value-Jan..Dec)을
    period='YYYY-MM' 레코드로 전개한다. 값이 0인 월은 건너뛰지 않고 0으로 저장하되,
    HS6 집계 후 해당 월 합이 0이면 생략한다.

    반환: (agg_value, agg_qty)
      agg_value: {flow: {(hs6,'YYYY-MM'): value}}  — 금액(천엔)
      agg_qty:   {flow: {(hs6,'YYYY-MM'): {"qty": q, "value": v, "units": set()}}} — 단가용
    단가 집계는 Unit1(수량1) 기준이며, 같은 HS6 아래 9자리 단위가 섞이면 units 가 2개 이상이 된다.
    """
    agg = {"exp": {}, "imp": {}}
    qagg = {"exp": {}, "imp": {}}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        flow = FLOW_CSV_CODE.get((row.get("Exp or Imp") or "").strip())
        if not flow:
            continue
        hs = clean_hs(row.get("HS"))
        if len(hs) < 6 or not hs[:6].isdigit():
            continue
        hs6 = hs[:6]
        unit = (row.get("Unit1") or "").strip()
        for mi, (vcol, qcol) in enumerate(zip(MONTH_COLS, QTY_COLS), start=1):
            v = to_int(row.get(vcol))
            period = f"{year:04d}-{mi:02d}"
            key = (hs6, period)
            if v != 0:
                agg[flow][key] = agg[flow].get(key, 0) + v
            q = to_int(row.get(qcol))
            # 단가용: 금액+수량을 HS6·월별로 누적(단위 동일시만 의미). 수량/단위 없으면 units 미포함.
            qa = qagg[flow].setdefault(key, {"qty": 0, "value": 0, "units": set()})
            qa["value"] += v
            if unit and q > 0:
                qa["qty"] += q
                qa["units"].add(unit)
    return agg, qagg


def _unit_price_rows(flow, qagg_flow):
    """qagg[flow] → unit_price 저장용 행. 단위 혼합이면 qty=None, unit='MIXED'."""
    rows = []
    for (hs6, period), a in qagg_flow.items():
        if a["value"] == 0 and a["qty"] == 0:
            continue
        if len(a["units"]) == 1 and a["qty"] > 0:
            rows.append({"flow": flow, "period": period, "hs_code": hs6,
                         "value": a["value"], "qty": a["qty"], "unit": next(iter(a["units"]))})
        else:
            rows.append({"flow": flow, "period": period, "hs_code": hs6,
                         "value": a["value"], "qty": None,
                         "unit": "MIXED" if len(a["units"]) > 1 else ""})
    return rows


def save_unit_price_rows(conn, rows):
    if not rows:
        return
    conn.executemany(
        "INSERT OR REPLACE INTO unit_price (flow, period, hs_code, value, qty, unit) "
        "VALUES (:flow, :period, :hs_code, :value, :qty, :unit)", rows)
    conn.commit()


def _rollup_levels(hs6_rows):
    """HS6 레코드 → HS2/HS4/HS6 모든 레벨로 집계.

    hs6_rows: {(hs6, period): value}
    반환: 저장용 dict 리스트 (flow 는 호출부에서 주입).
    """
    acc = {}  # (hs_code, level, period) -> value
    for (hs6, period), v in hs6_rows.items():
        for level in (2, 4, 6):
            code = hs6[:level]
            acc[(code, level, period)] = acc.get((code, level, period), 0) + v
    return acc


def save_hs_rows(conn, flow, acc):
    rows = [
        {"flow": flow, "period": period, "hs_code": code, "hs_level": level, "value": v}
        for (code, level, period), v in acc.items()
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO trade_hs (flow, period, hs_code, hs_level, value)
        VALUES (:flow, :period, :hs_code, :hs_level, :value)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def latest_period_in_db(conn):
    try:
        row = conn.execute("SELECT MAX(period) FROM trade_hs").fetchone()
        return row[0] if row and row[0] else None
    except sqlite3.OperationalError:
        return None


def run_collection(progress=None, incremental=True, db_path=None, api_key=None, years=YEARS):
    """統計品別表(세계합계) CSV 로 HS2/4/6 전량 수집(수입·수입).

    연도별 CSV 1개씩, 수출/수입 합쳐 약 (years×2)개 파일만 받으면 된다.
    """
    def emit(**kw):
        if progress:
            progress(kw)

    app_id = api_key or load_app_id()
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    db.ensure_schema(conn)

    emit(phase="catalog", message="統計品別表 CSV 목록 조회 중...")
    urls = catalog_csv_urls(app_id)
    this_year = dt.date.today().year
    want_years = sorted({y for y in range(this_year - years + 1, this_year + 1)})

    # 각 flow 에서 실제 제공되는 연도로 제한
    plan = []  # (flow, year, url)
    for flow in ("exp", "imp"):
        avail = urls.get(flow, {})
        for y in want_years:
            if y in avail:
                plan.append((flow, y, avail[y]))
    # 제공되는 최신 연도가 want 범위를 넘어가면(예: 아직 올해 자료 없음) 가장 최근 것 보강
    if not plan:
        raise RuntimeError("統計品別表 CSV 를 찾지 못했습니다.")

    total = len(plan)
    emit(phase="start", total=total, first=want_years[0], last=want_years[-1],
         message=f"統計品別表 CSV {total}개 수집 ({want_years[0]}~{want_years[-1]})")

    rows_total = 0
    for i, (flow, year, url) in enumerate(plan, 1):
        label = FLOW_LABEL[flow]
        emit(phase="step", index=i, total=total, flow=flow, year=year,
             message=f"[{i}/{total}] {year}년 {label} CSV 다운로드...")
        text = download_csv(url, app_id)
        agg, qagg = parse_hs_csv(text, year)
        acc = _rollup_levels(agg[flow])
        n = save_hs_rows(conn, flow, acc)
        save_unit_price_rows(conn, _unit_price_rows(flow, qagg[flow]))  # 단가(금액/수량) 저장
        rows_total += n
        emit(phase="step", index=i, total=total, flow=flow, year=year,
             rows=n, cumulative=rows_total,
             message=f"[{i}/{total}] {year}년 {label}: {n} rows")
        time.sleep(REQUEST_WAIT)

    latest = latest_period_in_db(conn)
    mn = conn.execute("SELECT MIN(period), MAX(period) FROM trade_hs").fetchone()
    for k, v in (
        ("latest_month", latest or ""),
        ("collected_at", dt.datetime.now().isoformat(timespec="seconds")),
        ("range", f"{mn[0]}~{mn[1]}" if mn and mn[0] else ""),
        ("years", str(years)),
        ("unit", "천엔"),
    ):
        conn.execute("INSERT OR REPLACE INTO collection_meta(key, value) VALUES (?, ?)", (k, v))
    conn.commit()

    cnt = conn.execute("SELECT COUNT(*) FROM trade_hs").fetchone()[0]
    conn.close()
    summary = {"latest_month": latest, "files": total, "rows": cnt,
               "range": f"{mn[0]}~{mn[1]}" if mn and mn[0] else ""}
    emit(phase="done", **summary, message=f"완료. {cnt} 행, 기간 {summary['range']}")
    return summary


# ----------------------------- 品別国別表 (국가별 온디맨드) -----------------------------
def _statsdata_country(app_id, stats_data_id, hs6, cat02_codes):
    """getStatsData 로 특정 HS6 하위(9자리)의 국가별 값을 조회.

    품별국별표는 cat01=9자리 품목. HS6 로 집계하려면 9자리 중 앞6=hs6 인 것만
    합산한다. cdCat01 에 '전방일치' 가 없으므로 전체를 받되 area/cat02 로 좁힌다.
    여기서는 '합계금액'(cat02=140) 만 받아 국가별 순위를 만든다(최근 연도).
    """
    data = _get_json({
        "_url": f"{BASE}/getStatsData",
        "appId": app_id,
        "statsDataId": stats_data_id,
        "cdCat02": ",".join(cat02_codes),
        "metaGetFlg": "N",
        "cntGetFlg": "N",
        "limit": 100000,
    })
    sd = data.get("GET_STATS_DATA", {}).get("STATISTICAL_DATA", {})
    vals = sd.get("DATA_INF", {}).get("VALUE", [])
    if isinstance(vals, dict):
        vals = [vals]
    return vals


def collect_country_breakdown(conn, app_id, hs6, force=False):
    """특정 HS6 의 국가별 금액(최근 연도 합계)을 수집하여 trade_country 에 저장.

    getStatsData 는 cdCat01 전방일치가 안 되므로, 해당 HS6 로 시작하는 9자리
    품목들을 area 별로 받아 HS6 로 합산한다. 데이터가 커질 수 있어 '연간 합계금액'
    (cat02=140) 만 사용하고, 가장 최근 제공 연도 기준으로 순위를 만든다.
    반환: 저장 행수.
    """
    # 이미 있으면 skip
    if not force:
        row = conn.execute(
            "SELECT 1 FROM trade_country WHERE hs_code=? LIMIT 1", (hs6,)
        ).fetchone()
        if row:
            return 0

    total = 0
    for flow in ("exp", "imp"):
        sid = KOKUBETSU[flow]["recent"]  # 최신 연도 표
        vals = _statsdata_country(app_id, sid, hs6, ["140"])  # 합계금액
        agg = {}  # cty_code -> (name, value)
        latest_time = None
        for v in vals:
            code = clean_hs(v.get("@cat01"))
            if len(code) < 6 or code[:6] != hs6:
                continue
            cty = (v.get("@area") or "").strip()
            tm = (v.get("@time") or "").strip()
            if latest_time is None or tm > latest_time:
                latest_time = tm
            val = to_int(v.get("$"))
            prev = agg.get(cty, [None, 0])
            agg[cty] = [prev[0], prev[1] + val]
        period = (latest_time[:4] + "-12") if latest_time else ""
        rows = [
            {"flow": flow, "period": period, "hs_code": hs6,
             "cty_code": c, "cty_name": "", "value": v[1]}
            for c, v in agg.items() if v[1] != 0
        ]
        if rows:
            conn.executemany(
                """
                INSERT OR REPLACE INTO trade_country
                    (flow, period, hs_code, cty_code, cty_name, value)
                VALUES (:flow, :period, :hs_code, :cty_code, :cty_name, :value)
                """,
                rows,
            )
            conn.commit()
            total += len(rows)
        time.sleep(REQUEST_WAIT)
    return total


def main():
    run_collection(progress=lambda e: print("  " + e.get("message", "")), incremental=False)


if __name__ == "__main__":
    main()
