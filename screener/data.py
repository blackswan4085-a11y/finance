"""OHLCV 다운로드 + 로컬 캐싱 + 주봉 변환."""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, Optional

import pandas as pd
import FinanceDataReader as fdr
from tqdm import tqdm


def _cache_file(cache_dir: str, symbol: str) -> str:
    safe = symbol.replace("/", "_").replace("\\", "_")
    return os.path.join(cache_dir, f"{safe}.parquet")


def _fetch_one(symbol: str, start: str, sleep: float) -> Optional[pd.DataFrame]:
    """일봉 OHLCV 다운로드. 실패 시 None."""
    for attempt in range(3):
        try:
            df = fdr.DataReader(symbol, start)
            if sleep:
                time.sleep(sleep)
            if df is None or df.empty:
                return None
            df = df.rename(columns=str.title)  # Open/High/Low/Close/Volume
            keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
            df = df[keep].copy()
            df.index = pd.to_datetime(df.index)
            return df
        except Exception:  # noqa: BLE001
            time.sleep(0.5 * (attempt + 1))
    return None


def _load_or_update(symbol: str, start: str, cache_dir: str, use_cache: bool,
                    sleep: float) -> Optional[pd.DataFrame]:
    path = _cache_file(cache_dir, symbol)
    cached: Optional[pd.DataFrame] = None
    if use_cache and os.path.exists(path):
        try:
            cached = pd.read_parquet(path)
            cached.index = pd.to_datetime(cached.index)
        except Exception:  # noqa: BLE001
            cached = None

    today = datetime.now().date()
    if cached is not None and not cached.empty:
        last = cached.index.max().date()
        # 캐시가 오늘(또는 어제 이후)까지면 재사용
        if last >= today - timedelta(days=1):
            return cached
        # 증분 업데이트: 마지막 날짜부터 다시 받아 병합
        inc_start = (last - timedelta(days=5)).strftime("%Y-%m-%d")
        fresh = _fetch_one(symbol, inc_start, sleep)
        if fresh is not None:
            merged = pd.concat([cached, fresh])
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
            _save(merged, path)
            return merged
        return cached

    # 캐시 없음 -> 전체 다운로드
    fresh = _fetch_one(symbol, start, sleep)
    if fresh is not None:
        _save(fresh, path)
    return fresh


def _save(df: pd.DataFrame, path: str) -> None:
    try:
        df.to_parquet(path)
    except Exception:  # noqa: BLE001
        pass


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """일봉 -> 주봉(금요일 마감 기준) 변환."""
    agg = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }
    use = {k: v for k, v in agg.items() if k in df.columns}
    wk = df.resample("W-FRI").agg(use).dropna(subset=["Close"])
    return wk


def download_all(symbols, cfg, label: str = "다운로드") -> Dict[str, pd.DataFrame]:
    """심볼 리스트의 일봉을 병렬 다운로드하여 {symbol: df} 반환."""
    start = (datetime.now() - timedelta(days=cfg.lookback_days)).strftime("%Y-%m-%d")
    results: Dict[str, pd.DataFrame] = {}

    def task(sym):
        return sym, _load_or_update(sym, start, cfg.cache_path, cfg.use_cache, cfg.request_sleep)

    with ThreadPoolExecutor(max_workers=cfg.max_workers) as ex:
        futs = [ex.submit(task, s) for s in symbols]
        for fut in tqdm(as_completed(futs), total=len(futs), desc=label, ncols=80):
            sym, df = fut.result()
            if df is not None and not df.empty:
                results[sym] = df
    return results
