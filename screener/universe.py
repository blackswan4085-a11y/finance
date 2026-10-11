"""시장별 종목 유니버스(종목 코드/이름) 구성."""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

import pandas as pd
import requests
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

# 한국거래소(KRX) 시장 -> 캐시 CSV의 MarketId 값
_KRX_MARKET_ID = {"KOSPI": "STK", "KOSDAQ": "KSQ", "KONEX": "KNX"}

_KRX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd",
}

# 날짜별 캐시 CSV를 중복 다운로드하지 않도록 메모리 캐시
_krx_cache_df: Optional[pd.DataFrame] = None


def _krx_latest_business_date() -> str:
    """KRX에서 최근 영업일(YYYY-MM-DD) 조회."""
    url = ("http://data.krx.co.kr/comm/bldAttendant/executeForResourceBundle.cmd"
           "?baseName=krx.mdc.i18n.component&key=B128.bld")
    r = requests.get(url, headers=_KRX_HEADERS, timeout=20)
    j = json.loads(r.text)
    date_str = j["result"]["output"][0]["max_work_dt"]
    return datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")


def _load_krx_cache() -> pd.DataFrame:
    """FinanceData 공식 캐시 저장소에서 KRX 전체 상장 목록 CSV를 받는다.

    KRX 실시간 API(getJsonData.cmd)는 환경에 따라 'LOGOUT'을 반환하며 거부하므로,
    실시간 API 대신 날짜별 캐시 CSV를 직접 사용한다. 이 CSV에는 KOSPI/KOSDAQ/KONEX가
    MarketId(STK/KSQ/KNX)로 함께 들어 있다.
    """
    global _krx_cache_df
    if _krx_cache_df is not None:
        return _krx_cache_df
    fdate = _krx_latest_business_date()
    url = ("https://raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/"
           f"refs/heads/master/data/listing/krx/{fdate}.csv")
    df = pd.read_csv(url, index_col=0,
                     dtype={"Code": str, "Dept": str, "ChangeCode": str, "MarketId": str})
    df = df.reset_index(drop=True)
    _krx_cache_df = df
    return df


def _krx_listing(market: str) -> pd.DataFrame:
    """캐시 CSV에서 특정 KRX 시장(KOSPI/KOSDAQ/KONEX)만 추려 반환."""
    df = _load_krx_cache()
    mkt_id = _KRX_MARKET_ID[market]
    out = df[df["MarketId"] == mkt_id].reset_index(drop=True)
    return out


# 미국 시가총액 캐시 (Nasdaq 스크리너 API, 1회 호출로 전종목)
_us_marketcap: Optional[dict] = None


def _load_us_marketcap() -> dict:
    """Nasdaq 스크리너 API에서 미국 전종목 시가총액을 한 번에 받아 {symbol: marketcap(float)}.

    API 키 불필요. 심볼 표기 차이를 흡수하기 위해 점/하이픈을 제거한 키도 함께 등록한다.
    (예: BRK/A, BRK.B 등)
    """
    global _us_marketcap
    if _us_marketcap is not None:
        return _us_marketcap
    url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&download=true"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US",
    }
    cap: dict = {}
    try:
        r = requests.get(url, headers=headers, timeout=40)
        r.raise_for_status()
        rows = r.json().get("data", {}).get("rows") or []
        for row in rows:
            sym = (row.get("symbol") or "").strip().upper()
            raw = row.get("marketCap")
            if not sym or raw in (None, "", "0", "0.00"):
                continue
            try:
                val = float(str(raw).replace(",", ""))
            except (TypeError, ValueError):
                continue
            if val <= 0:
                continue
            cap[sym] = val
            # 심볼 표기 정규화 키 추가 (영숫자만)
            norm = "".join(ch for ch in sym if ch.isalnum())
            if norm != sym:
                cap.setdefault(norm, val)
    except Exception as e:  # noqa: BLE001
        print(f"[universe] 미국 시가총액 로드 실패(무시하고 진행): {e}")
    _us_marketcap = cap
    return cap


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
    # 섹터는 사용자가 직접 입력/관리하므로 데이터 소스에서 가져오지 않음 (항상 공란)
    out["sector"] = ""
    # 시가총액: 한국 캐시 CSV의 Marcap(원 단위)이 있으면 보존, 없으면 NaN(미국은 나중에 채움)
    cap_col = cols.get("marcap") or cols.get("marketcap")
    if cap_col:
        out["marketcap"] = pd.to_numeric(df[cap_col], errors="coerce")
    else:
        out["marketcap"] = pd.NA
    out = out.dropna(subset=["symbol"]).drop_duplicates(subset=["symbol"])
    return out


def build_universe(markets: List[str]) -> pd.DataFrame:
    """선택된 시장들의 종목 리스트를 하나의 DataFrame으로 반환."""
    frames = []
    for m in markets:
        raw = None
        # 한국 시장은 캐시 CSV를 우선 사용 (KRX 실시간 API의 LOGOUT 거부 회피)
        if m in _KRX_MARKET_ID:
            try:
                raw = _krx_listing(m)
            except Exception as e:  # noqa: BLE001
                print(f"[universe] {m} 캐시 리스팅 실패, FDR로 재시도: {e}")
                raw = None
        if raw is None or len(raw) == 0:
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
        # 미국 시장은 Nasdaq 스크리너 API 시총으로 채움
        meta = MARKET_META.get(m, {})
        if meta.get("country") == "US":
            cap = _load_us_marketcap()
            if cap:
                norm["marketcap"] = norm["symbol"].map(
                    lambda s: cap.get(str(s).upper())
                    or cap.get("".join(ch for ch in str(s).upper() if ch.isalnum()))
                )
                filled = int(norm["marketcap"].notna().sum())
                print(f"[universe] {m}: {len(norm)} 종목 (시총 {filled}개)")
            else:
                print(f"[universe] {m}: {len(norm)} 종목 (시총 소스 실패)")
        else:
            filled = int(norm["marketcap"].notna().sum())
            print(f"[universe] {m}: {len(norm)} 종목 (시총 {filled}개)")
        frames.append(norm)
    if not frames:
        return pd.DataFrame(
            columns=["symbol", "name", "market", "country", "currency", "sector", "marketcap"])
    uni = pd.concat(frames, ignore_index=True)
    return uni
