"""전체 스캔 오케스트레이션: 유니버스 -> 데이터 -> 지표 -> 결과 테이블."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from .config import Config
from .data import download_all, to_weekly
from .indicators import compute_signals
from .universe import build_universe
from .instruments import InstrumentStore
from .weekly import previous_week_friday


def run_screen(cfg: Config, asof_date=None) -> pd.DataFrame:
    asof_date = asof_date or previous_week_friday()
    # 1) 유니버스
    uni = build_universe(cfg.markets, exclude_special=cfg.exclude_special)
    store = InstrumentStore(cfg.base_dir)
    store.upsert(uni.to_dict("records"), "stock-listing")
    uni = store.equity_frame(uni)
    if uni.empty:
        raise RuntimeError("수집한 종목 목록이 비어 있어 스크리닝을 완료하지 못했습니다.")
    print(f"[screen] 총 {len(uni)} 종목 스캔")

    name_map = dict(zip(uni["symbol"], uni["name"]))
    market_map = dict(zip(uni["symbol"], uni["market"]))
    country_map = dict(zip(uni["symbol"], uni["country"]))
    currency_map = dict(zip(uni["symbol"], uni["currency"]))
    sector_map = dict(zip(uni["symbol"], uni.get("sector", pd.Series("", index=uni.index))))
    cap_map = dict(zip(uni["symbol"], uni.get("marketcap", pd.Series(pd.NA, index=uni.index))))

    # 2) 데이터 다운로드 (일봉, 캐시)
    data = download_all(list(uni["symbol"]), cfg, label="OHLCV", asof_date=asof_date)
    print(f"[screen] {len(data)} 종목 데이터 확보")
    if not data:
        raise RuntimeError("주가 데이터를 한 종목도 가져오지 못했습니다. 네트워크와 데이터 공급자를 확인해 주세요.")

    # 3) 지표 계산
    rows = []
    evaluated = 0
    valid_markets = set()
    stale = 0
    week_start = asof_date - timedelta(days=asof_date.weekday())
    for sym, daily in data.items():
        daily = daily[daily.index.date <= asof_date]
        if daily.empty:
            continue
        # A failed incremental download may return an old price cache. Never
        # label that earlier week's scan as a successful update for this week.
        if daily.index.max().date() < week_start:
            stale += 1
            continue
        weekly = to_weekly(daily)
        sig = compute_signals(weekly, cfg.high_periods_weeks, cfg.ma_periods_weeks)
        if sig is None:
            continue
        evaluated += 1
        valid_markets.add(market_map[sym])

        # 유동성 필터
        if cfg.min_avg_dollar_volume > 0 and sig["avg_dollar_volume"] < cfg.min_avg_dollar_volume:
            continue

        row = {
            "symbol": sym,
            "asset_type": "STOCK",
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
    if not evaluated:
        raise RuntimeError("기준 주의 유효한 주가 데이터가 없어 조건을 계산하지 못했습니다. "
                           + (f"이전 주 캐시 {stale}종목은 최신 결과로 사용하지 않았습니다." if stale else "수집 상태와 가격 이력을 확인해 주세요."))
    missing_markets = set(uni["market"]) - valid_markets
    if missing_markets:
        raise RuntimeError("기준 주 주가 수집 실패: " + ", ".join(sorted(missing_markets)) + ". 전체 시장 결과를 갱신하지 않았습니다.")
    scan = {"universe_count": len(uni), "downloaded_count": len(data), "evaluated_count": evaluated,
            "stale_count": stale, "markets": sorted(valid_markets)}
    if df.empty:  # All evaluated stocks were excluded by the liquidity filter.
        df.attrs["scan"] = scan
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
    df["high_count"] = df[high_cols].fillna(False).astype(bool).sum(axis=1).astype(int)
    # 원화는 환율로 나눠 달러 기준으로 공통 비교 (NaN은 최하위)
    usd_krw = float(cfg.usd_krw) if cfg.usd_krw else 1400.0
    cap = pd.to_numeric(df["marketcap"], errors="coerce")
    df["_cap_sort"] = cap.where(df["currency"] != "KRW", cap / usd_krw).fillna(-1)
    df = df.sort_values(["aligned", "high_count", "_cap_sort"],
                        ascending=[False, False, False]).reset_index(drop=True)
    df = df.drop(columns=["_cap_sort"])
    df.attrs["scan"] = scan
    return df
