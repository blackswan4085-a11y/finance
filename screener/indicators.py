"""신고가 / 주봉 이평 정배열 지표 계산."""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd


def compute_signals(weekly: pd.DataFrame, high_periods: List[int],
                    ma_periods: List[int]) -> Optional[Dict]:
    """주봉 데이터로 신고가/정배열 신호 계산.

    - 신고가: 최근 봉의 High가 과거 N주(현재 포함) 중 최고가인지 (고가 기준)
    - 정배열: 종가 기준 MA들이 짧은주기 > 긴주기 로 내림차순이면 True
    데이터가 부족하면 None.
    """
    if weekly is None or weekly.empty:
        return None
    n = len(weekly)
    max_period = max(max(high_periods), max(ma_periods))
    # 최소한 가장 긴 기간만큼의 주봉이 있어야 판정 가능
    if n < max(max(high_periods), max(ma_periods)):
        # 완전히 부족하면 제외
        return None

    high = weekly["High"]
    close = weekly["Close"]
    last_high = float(high.iloc[-1])
    last_close = float(close.iloc[-1])

    result: Dict = {
        "last_close": last_close,
        "last_high": last_high,
        "last_date": weekly.index[-1].date().isoformat(),
        "weeks_available": n,
    }

    # ---- 신고가 판정 (고가 기준) ----
    highs = {}
    any_high = False
    for p in high_periods:
        if n < p:
            highs[p] = None  # 데이터 부족
            continue
        window_max = float(high.iloc[-p:].max())
        is_high = last_high >= window_max - 1e-9
        highs[p] = bool(is_high)
        if is_high:
            any_high = True
    result["highs"] = highs
    result["any_high"] = any_high

    # ---- 정배열 판정 (종가 이평, 내림차순) ----
    mas = {}
    ok = True
    prev = None
    enough = True
    for p in ma_periods:
        if n < p:
            mas[p] = None
            enough = False
            continue
        val = float(close.iloc[-p:].mean())
        mas[p] = round(val, 4)
    # 짧은주기 -> 긴주기 순으로 내림차순인지 확인
    if enough:
        ordered = [mas[p] for p in ma_periods]
        for i in range(len(ordered) - 1):
            if not (ordered[i] > ordered[i + 1]):
                ok = False
                break
    else:
        ok = False
    result["mas"] = mas
    result["aligned"] = bool(ok) if enough else False
    result["ma_enough"] = enough

    # 보조: 평균 거래대금 (최근 4주)
    if "Volume" in weekly.columns:
        recent = weekly.iloc[-4:]
        try:
            result["avg_dollar_volume"] = float((recent["Close"] * recent["Volume"]).mean())
        except Exception:  # noqa: BLE001
            result["avg_dollar_volume"] = 0.0
    else:
        result["avg_dollar_volume"] = 0.0

    return result
