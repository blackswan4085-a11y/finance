"""Build four OHLCV intervals from the screener's cached daily data."""
from __future__ import annotations

import math
import os

import pandas as pd


_OHLCV = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def _bars(frame: pd.DataFrame) -> list[dict]:
    result = []
    for date, row in frame.iterrows():
        values = {key: float(row[key]) for key in _OHLCV}
        if not all(math.isfinite(value) for value in values.values()):
            continue
        if values["High"] < max(values["Open"], values["Close"], values["Low"]):
            continue
        if values["Low"] > min(values["Open"], values["Close"], values["High"]):
            continue
        if values["Volume"] < 0:
            continue
        result.append({"time": int(date.timestamp() * 1000),
                       **{key.lower(): value for key, value in values.items()}})
    return result


def _aggregate(daily: pd.DataFrame, frequency: str | pd.DateOffset) -> pd.DataFrame:
    """Use the final actual trading day as each candle timestamp."""
    rows = []
    dates = []
    for _, group in daily.groupby(pd.Grouper(freq=frequency)):
        if group.empty:
            continue
        rows.append({"Open": group["Open"].iloc[0], "High": group["High"].max(),
                     "Low": group["Low"].min(), "Close": group["Close"].iloc[-1],
                     "Volume": group["Volume"].sum()})
        dates.append(group.index[-1])
    return pd.DataFrame(rows, index=pd.DatetimeIndex(dates))


def chart_payload(cache_dir: str, symbol: str, meta: dict, asof: str = "") -> dict:
    """Read a validated catalogue instrument from its dedicated cache directory."""
    filename = symbol.replace("/", "_").replace("\\", "_") + ".parquet"
    path = os.path.abspath(os.path.join(cache_dir, filename))
    if os.path.commonpath((os.path.abspath(cache_dir), path)) != os.path.abspath(cache_dir):
        raise ValueError("잘못된 종목 코드입니다")
    daily = pd.read_parquet(path)
    daily.index = pd.to_datetime(daily.index)
    if daily.index.tz is not None:
        daily.index = daily.index.tz_localize(None)
    daily = daily.sort_index()
    daily = daily[~daily.index.duplicated(keep="last")]
    if asof:
        daily = daily[daily.index <= pd.Timestamp(asof) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)]
    for column in _OHLCV:
        if column not in daily.columns:
            if column == "Volume":
                daily[column] = 0
            else:
                raise ValueError("OHLC 데이터가 없습니다: " + column)
        daily[column] = pd.to_numeric(daily[column], errors="coerce")
    daily = daily.dropna(subset=["Open", "High", "Low", "Close"])
    daily = daily[daily["Volume"].fillna(0) >= 0].fillna({"Volume": 0})
    if daily.empty:
        raise ValueError("표시할 차트 데이터가 없습니다")
    return {
        "symbol": symbol, "name": str(meta.get("name") or symbol),
        "market": str(meta.get("market") or ""),
        "currency": str(meta.get("currency") or ""),
        "asof": asof or daily.index[-1].date().isoformat(),
        "series": {
            "daily": _bars(daily),
            "weekly": _bars(_aggregate(daily, "W-FRI")),
            "monthly": _bars(_aggregate(daily, pd.offsets.MonthEnd())),
            "quarterly": _bars(_aggregate(daily, pd.offsets.QuarterEnd(startingMonth=12))),
        },
    }
