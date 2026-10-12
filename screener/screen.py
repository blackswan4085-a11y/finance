"""전체 스캔 오케스트레이션: 유니버스 -> 데이터 -> 지표 -> 결과 테이블."""
from __future__ import annotations

from typing import List

import pandas as pd

from .config import Config
from .data import download_all, to_weekly
from .indicators import compute_signals
from .universe import build_universe


def run_screen(cfg: Config) -> pd.DataFrame:
    # 1) 유니버스
    uni = build_universe(cfg.markets, exclude_special=cfg.exclude_special)
    if uni.empty:
        print("[screen] 유니버스가 비어있습니다.")
        return pd.DataFrame()
    print(f"[screen] 총 {len(uni)} 종목 스캔")

    name_map = dict(zip(uni["symbol"], uni["name"]))
    market_map = dict(zip(uni["symbol"], uni["market"]))
    country_map = dict(zip(uni["symbol"], uni["country"]))
    currency_map = dict(zip(uni["symbol"], uni["currency"]))
    sector_map = dict(zip(uni["symbol"], uni.get("sector", pd.Series("", index=uni.index))))
    cap_map = dict(zip(uni["symbol"], uni.get("marketcap", pd.Series(pd.NA, index=uni.index))))

    # 2) 데이터 다운로드 (일봉, 캐시)
    data = download_all(list(uni["symbol"]), cfg, label="OHLCV")
    print(f"[screen] {len(data)} 종목 데이터 확보")

    # 3) 지표 계산
    rows = []
    for sym, daily in data.items():
        weekly = to_weekly(daily)
        sig = compute_signals(weekly, cfg.high_periods_weeks, cfg.ma_periods_weeks)
        if sig is None:
            continue

        # 유동성 필터
        if cfg.min_avg_dollar_volume > 0 and sig["avg_dollar_volume"] < cfg.min_avg_dollar_volume:
            continue

        row = {
            "symbol": sym,
            "name": name_map.get(sym, sym),
            "market": market_map.get(sym, ""),
            "country": country_map.get(sym, ""),
            "currency": currency_map.get(sym, ""),
            "sector": sector_map.get(sym, ""),
            "last_date": sig["last_date"],
            "close": sig["last_close"],
            "aligned": sig["aligned"],
            "any_high": sig["any_high"],
            "avg_dollar_volume": sig["avg_dollar_volume"],
            "marketcap": cap_map.get(sym),
        }
        for p in cfg.high_periods_weeks:
            row[f"high_{p}w"] = sig["highs"].get(p)
        for p in cfg.ma_periods_weeks:
            row[f"ma_{p}w"] = sig["mas"].get(p)
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # 시가총액 숫자화 (정렬/필터용). 없으면 NaN
    df["marketcap"] = pd.to_numeric(df["marketcap"], errors="coerce")

    # 4) 포함 기준 필터
    mode = cfg.include_mode
    if mode == "any_high":
        df = df[df["any_high"]]
    elif mode == "any_signal":
        df = df[df["any_high"] | df["aligned"]]
    elif mode == "require_both":
        df = df[df["any_high"] & df["aligned"]]

    # 5) 정렬: 정배열 -> 신고가 충족수 -> (동률이면) 시가총액(환율 환산 USD) 순
    high_cols = [f"high_{p}w" for p in cfg.high_periods_weeks]
    df["high_count"] = df[high_cols].apply(lambda r: sum(bool(x) for x in r), axis=1)
    # 원화는 환율로 나눠 달러 기준으로 공통 비교 (NaN은 최하위)
    usd_krw = float(cfg.usd_krw) if cfg.usd_krw else 1400.0
    cap = pd.to_numeric(df["marketcap"], errors="coerce")
    df["_cap_sort"] = cap.where(df["currency"] != "KRW", cap / usd_krw).fillna(-1)
    df = df.sort_values(["aligned", "high_count", "_cap_sort"],
                        ascending=[False, False, False]).reset_index(drop=True)
    df = df.drop(columns=["_cap_sort"])
    return df
