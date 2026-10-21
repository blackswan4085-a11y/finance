"""Chart-search catalogue. ETF membership never expands the equity screener."""
from __future__ import annotations

import io
import os
import re
import sqlite3
from datetime import datetime
from contextlib import contextmanager
import pandas as pd
import requests
from .security_policy import exclusion_reason, load_exclusions, remember_exclusions

SEED_ETFS = [
    ("IPAY", "Amplify Digital Payments ETF", "ARCA", "US"),
    ("SPY", "SPDR S&P 500 ETF Trust", "ARCA", "US"),
    ("QQQ", "Invesco QQQ Trust", "NASDAQ", "US"),
    ("VOO", "Vanguard S&P 500 ETF", "ARCA", "US"),
    ("IWM", "iShares Russell 2000 ETF", "ARCA", "US"),
    ("TLT", "iShares 20+ Year Treasury Bond ETF", "NASDAQ", "US"),
    ("GLD", "SPDR Gold Shares", "ARCA", "US"),
    ("XLF", "Financial Select Sector SPDR ETF", "ARCA", "US"),
    ("ARKK", "ARK Innovation ETF", "CBOE", "US"),
    ("069500", "KODEX 200", "KRX", "KR"),
    ("229200", "KODEX 코스닥150", "KRX", "KR"),
    ("360750", "TIGER 미국S&P500", "KRX", "KR"),
    ("SMH", "VanEck Semiconductor ETF", "NASDAQ", "US"),
    ("XLK", "Technology Select Sector SPDR ETF", "ARCA", "US"),
    ("XLC", "Communication Services Select Sector SPDR ETF", "ARCA", "US"),
    ("XLY", "Consumer Discretionary Select Sector SPDR ETF", "ARCA", "US"),
    ("XLP", "Consumer Staples Select Sector SPDR ETF", "ARCA", "US"),
    ("XLV", "Health Care Select Sector SPDR ETF", "ARCA", "US"),
    ("XLI", "Industrial Select Sector SPDR ETF", "ARCA", "US"),
    ("XLB", "Materials Select Sector SPDR ETF", "ARCA", "US"),
    ("XLE", "Energy Select Sector SPDR ETF", "ARCA", "US"),
    ("XLU", "Utilities Select Sector SPDR ETF", "ARCA", "US"),
    ("XLRE", "Real Estate Select Sector SPDR ETF", "ARCA", "US"),
]
KR_MARKETS = {"KRX", "KOSPI", "KOSDAQ", "KONEX"}
US_MARKETS = {"NASDAQ", "NYSE", "AMEX", "ARCA", "NYSEARCA", "NYSE_ARCA", "CBOE", "BATS", "IEX", "US", "SP500", "S&P500"}
ETF_NAME = re.compile(r"\bETF\b|exchange[\s-]*traded\s+fund", re.I)

def is_fund_record(row):
    for key in ("asset_type", "AssetType", "stockType", "securityType", "MarketId"):
        value = row.get(key, "")
        if isinstance(value, dict):
            value = value.get("code", value.get("name", ""))
        if str(value).upper() in {"ETF", "ETN", "FUND"}:
            return True
    for key in ("ETF", "etf", "is_etf", "IsETF"):
        if str(row.get(key, "")).upper() in {"Y", "YES", "TRUE", "1"}:
            return True
    return bool(ETF_NAME.search(str(row.get("name", row.get("Name", "")))))

class InstrumentStore:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.path = os.path.join(base_dir, "instruments.sqlite3")
        os.makedirs(base_dir, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS instruments (
                symbol TEXT NOT NULL, country TEXT NOT NULL, name TEXT NOT NULL,
                market TEXT NOT NULL, currency TEXT NOT NULL,
                asset_type TEXT NOT NULL CHECK(asset_type IN ('STOCK','ETF','UNKNOWN')),
                source TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(symbol, country))""")
            db.execute("CREATE INDEX IF NOT EXISTS instrument_name ON instruments(name COLLATE NOCASE)")
            now = datetime.now().isoformat(timespec="seconds")
            db.executemany("INSERT OR IGNORE INTO instruments VALUES (?,?,?,?,?,?,?,?)",
                [(s,c,n,m,"KRW" if c=="KR" else "USD","ETF","seed",now) for s,n,m,c in SEED_ETFS])

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def upsert(self, records, source="listing"):
        records = [{**row, 'asset_type': 'ETF' if is_fund_record(row) else row.get('asset_type') or 'STOCK'} for row in records]
        exclusions = remember_exclusions(self.base_dir, records)
        now = datetime.now().isoformat(timespec="seconds")
        values = []
        for row in records:
            symbol = str(row.get("symbol", "")).strip().upper()
            country = str(row.get("country", "")).upper()
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9./_-]{0,24}", symbol) or country not in {"US","KR","JP"}:
                continue
            kind = "ETF" if is_fund_record(row) else str(row.get("asset_type") or "STOCK").upper()
            if kind not in {"STOCK","ETF","UNKNOWN"}:
                kind = "UNKNOWN"
            if exclusion_reason(self.base_dir, country, symbol, row.get("name", ""), kind, exclusions):
                continue
            ccy = {"KR": "KRW", "JP": "JPY"}.get(country, "USD")
            default_market = {"KR": "KRX", "JP": "TSE"}.get(country, "NYSE")
            values.append((symbol,country,str(row.get("name") or symbol),
                           str(row.get("market") or default_market),
                           ccy,kind,source,now))
        with self.connect() as db:
            db.executemany("DELETE FROM instruments WHERE country=? AND symbol=? AND asset_type!='ETF'",
                [tuple(key.split(':', 1)) for key in exclusions])
            db.executemany("""INSERT INTO instruments VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol,country) DO UPDATE SET
                name=excluded.name, market=excluded.market, currency=excluded.currency,
                asset_type=excluded.asset_type, source=excluded.source, updated_at=excluded.updated_at
                WHERE instruments.asset_type != 'ETF' OR excluded.asset_type = 'ETF'""", values)

    def register_cached_equities(self, directory):
        # Legacy cache was built from equity scans. Keep richer listing metadata.
        if not os.path.isdir(directory):
            return
        now = datetime.now().isoformat(timespec="seconds")
        values = []
        exclusions = load_exclusions(self.base_dir)['instruments']
        for filename in os.listdir(directory):
            if not filename.endswith(".parquet"):
                continue
            symbol = filename[:-8].upper()
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9./_-]{0,24}", symbol):
                continue
            country = ("JP" if symbol.endswith(".T")
                       else "KR" if re.fullmatch(r"\d{4}[0-9A-HJ-NP-TV-Z][0-9KLMN]",symbol) else "US")
            if exclusion_reason(self.base_dir, country, symbol, records=exclusions):
                continue
            values.append((symbol,country,symbol,{"KR":"KRX","JP":"TSE"}.get(country,"US"),
                           {"KR":"KRW","JP":"JPY"}.get(country,"USD"),"STOCK","legacy-cache",now))
        with self.connect() as db:
            db.executemany("INSERT OR IGNORE INTO instruments VALUES (?,?,?,?,?,?,?,?)",values)

    def search(self, query="", limit=20, asset_type=""):
        asset_type = asset_type if asset_type in {"STOCK", "ETF"} else ""
        query = str(query).strip()[:120]
        escaped = query.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")
        with self.connect() as db:
            rows = db.execute("""SELECT * FROM instruments
                WHERE (? = '' OR asset_type = ?) AND
                    (symbol LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\')
                ORDER BY CASE WHEN symbol = ? COLLATE NOCASE THEN 0
                    WHEN symbol LIKE ? ESCAPE '\\' THEN 1 ELSE 2 END,
                    asset_type, symbol LIMIT ?""",
                (asset_type,asset_type,"%"+escaped+"%","%"+escaped+"%",query,escaped+"%",min(50,max(1,int(limit))))).fetchall()
        return [self.public(dict(row)) for row in rows]

    @staticmethod
    def public(row):
        row["code"] = (row["market"] + ":" if row["market"] != "US" else "") + row["symbol"]
        return row

    def resolve(self, value):
        value = str(value).strip()
        if not value or len(value) > 120:
            raise ValueError("종목 코드 또는 이름을 입력해 주세요.")
        market, symbol = value.upper().split(":",1) if ":" in value else ("",value.upper())
        country = "KR" if market in KR_MARKETS else "US" if market in US_MARKETS else None
        if market and country is None:
            raise ValueError("지원하지 않는 거래소입니다: " + market)
        with self.connect() as db:
            if country:
                rows = db.execute("SELECT * FROM instruments WHERE symbol=? AND country=?", (symbol,country)).fetchall()
            else:
                rows = db.execute("""SELECT * FROM instruments
                    WHERE symbol=? COLLATE NOCASE OR name=? COLLATE NOCASE""",(symbol,value)).fetchall()
        if len(rows) == 1:
            row = dict(rows[0])
            if row["market"] == "US" and market:
                row["market"] = market
            reason = exclusion_reason(self.base_dir, row['country'], row['symbol'], row['name'], row['asset_type'])
            if reason:
                raise ValueError("수집 제외 종목입니다 (우선주·스팩): " + row['symbol'])
            return row
        if len(rows) > 1:
            raise ValueError("같은 코드의 종목이 여러 개입니다. 거래소:코드로 선택해 주세요.")
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9./_-]{0,24}", symbol):
            raise ValueError("검색 결과에서 종목을 선택해 주세요.")
        country = country or ("JP" if symbol.endswith(".T")
                              else "KR" if re.fullmatch(r"\d{4}[0-9A-HJ-NP-TV-Z][0-9KLMN]",symbol) else "US")
        if exclusion_reason(self.base_dir, country, symbol):
            raise ValueError("수집 제외 종목입니다 (우선주·스팩): " + symbol)
        # Unlisted chart lookups remain UNKNOWN, never eligible for a screen.
        return {"symbol":symbol,"country":country,"name":symbol,
                "market":market or {"KR":"KRX","JP":"TSE"}.get(country,"US"),
                "currency":{"KR":"KRW","JP":"JPY"}.get(country,"USD"),"asset_type":"UNKNOWN"}

    def equity_frame(self, frame):
        if frame.empty or "symbol" not in frame:
            return frame.copy()
        with self.connect() as db:
            funds = {(r["symbol"],r["country"]) for r in db.execute(
                "SELECT symbol,country FROM instruments WHERE asset_type='ETF'")}
        exclusions = load_exclusions(self.base_dir)['instruments']
        def allowed(row):
            country = str(row.get("country") or ("KR" if row.get("market") in KR_MARKETS else "US"))
            if exclusion_reason(self.base_dir, country, row['symbol'], row.get('name', ''), row.get('asset_type', 'STOCK'), exclusions):
                return False
            return str(row.get("asset_type", "STOCK")).upper() != "UNKNOWN" and not is_fund_record(row) and (str(row["symbol"]).upper(),country) not in funds
        return frame.loc[frame.apply(allowed,axis=1)].copy()

    def counts(self):
        with self.connect() as db:
            return {r["asset_type"]:r["n"] for r in db.execute(
                "SELECT asset_type,COUNT(*) AS n FROM instruments GROUP BY asset_type")}

    def refresh_etfs(self):
        """Only ETF metadata is imported; no screen/cache mutation or bulk price fetch."""
        outcomes = []
        session = requests.Session()
        session.headers.update({"User-Agent":"Mozilla/5.0"})
        sources = [
            ("nasdaqlisted","https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"),
            ("otherlisted","https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"),
            ("ETF/KR","https://finance.naver.com/api/sise/etfItemList.nhn"),
        ]
        for source,url in sources:
            try:
                response = session.get(url,timeout=20)
                response.raise_for_status()
                if source == "ETF/KR":
                    raw = response.json()["result"]["etfItemList"]
                    records = [{"symbol":r["itemcode"],"name":r["itemname"],
                                "market":"KRX","country":"KR","asset_type":"ETF"} for r in raw]
                else:
                    table = pd.read_csv(io.StringIO(response.text),sep="|",dtype=str)
                    if "ETF" not in table or "Test Issue" not in table:
                        raise ValueError("ETF 구분 필드가 없는 목록입니다.")
                    table = table[table["ETF"].eq("Y") & table["Test Issue"].eq("N")]
                    markets = {"A":"AMEX","N":"NYSE","P":"ARCA","Z":"CBOE","V":"IEX"}
                    symbol_column = "Symbol" if source=="nasdaqlisted" else "ACT Symbol"
                    records = [{"symbol":r[symbol_column],"name":r["Security Name"],
                                "market":"NASDAQ" if source=="nasdaqlisted" else markets.get(r["Exchange"],"NYSE"),
                                "country":"US","asset_type":"ETF"} for r in table.to_dict("records")]
                if not records:
                    raise ValueError("ETF 목록이 비어 있습니다.")
                self.upsert(records,source)
                outcomes.append({"source":source,"ok":True,"count":len(records)})
            except Exception as exc:
                outcomes.append({"source":source,"ok":False,"error":str(exc)})
        return {"sources":outcomes,"counts":self.counts(),"ok":any(r["ok"] for r in outcomes)}
