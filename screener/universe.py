"""시장별 종목 유니버스(종목 코드/이름) 구성."""
from __future__ import annotations

from typing import List

import pandas as pd
import FinanceDataReader as fdr

from .config import MARKET_META

# FinanceDataReader StockListing에 넘길 실제 코드로 매핑
_LISTING_CODE = {
    "KOSPI": "KOSPI",
    "KOSDAQ": "KOSDAQ",
    "KONEX": "KONEX",
    "SP500": "S&P500",
    "S&P500": "S&P500",
    "NASDAQ": "NASDAQ",
    "NYSE": "NYSE",
    "AMEX": "AMEX",
}


def _normalize(df: pd.DataFrame, market: str) -> pd.DataFrame:
    """다양한 StockListing 결과를 공통 스키마로 정리.

    공통 컬럼: symbol, name, market, country, currency
    """
    cols = {c.lower(): c for c in df.columns}
    # 심볼 컬럼 찾기 (한국: Code, 미국: Symbol)
    sym_col = cols.get("code") or cols.get("symbol")
    name_col = cols.get("name")
    out = pd.DataFrame()
    out["symbol"] = df[sym_col].astype(str)
    out["name"] = df[name_col].astype(str) if name_col else out["symbol"]
    meta = MARKET_META.get(market, {"country": "", "currency": ""})
    out["market"] = market
    out["country"] = meta["country"]
    out["currency"] = meta["currency"]
    # 섹터 정보가 있으면 보존
    sec_col = cols.get("sector") or cols.get("industry")
    out["sector"] = df[sec_col].astype(str) if sec_col else ""
    out = out.dropna(subset=["symbol"]).drop_duplicates(subset=["symbol"])
    return out


def build_universe(markets: List[str]) -> pd.DataFrame:
    """선택된 시장들의 종목 리스트를 하나의 DataFrame으로 반환."""
    frames = []
    for m in markets:
        code = _LISTING_CODE.get(m, m)
        try:
            raw = fdr.StockListing(code)
        except Exception as e:  # noqa: BLE001
            print(f"[universe] {m} 리스팅 실패: {e}")
            continue
        if raw is None or len(raw) == 0:
            print(f"[universe] {m} 결과 없음")
            continue
        norm = _normalize(raw, m)
        print(f"[universe] {m}: {len(norm)} 종목")
        frames.append(norm)
    if not frames:
        return pd.DataFrame(columns=["symbol", "name", "market", "country", "currency", "sector"])
    uni = pd.concat(frames, ignore_index=True)
    return uni
