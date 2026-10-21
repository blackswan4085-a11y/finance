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
from .security_policy import exclusion_reason, load_exclusions
import re


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


def _fetched_today(path: str) -> bool:
    """캐시 파일을 오늘 저장(갱신)했는지 여부. 파일 수정시각 기준."""
    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(path)).date()
        return mtime == datetime.now().date()
    except OSError:
        return False


def _load_or_update(symbol: str, start: str, cache_dir: str, use_cache: bool,
                    sleep: float, offline: bool = False):
    """반환: (DataFrame|None, status) — status in {'cache','update','new','fail'}.

    offline=True 면 캐시가 있을 때 증분 갱신 없이 그대로 재사용한다(네트워크 0).
    과거 기준 backfill 처럼 '이미 받은 과거 데이터로 충분'한 경우에 쓴다. 캐시가
    아예 없는 종목만 새로 내려받는다.
    """
    path = _cache_file(cache_dir, symbol)
    cached: Optional[pd.DataFrame] = None
    if use_cache and os.path.exists(path):
        try:
            cached = pd.read_parquet(path)
            cached.index = pd.to_datetime(cached.index)
        except Exception:  # noqa: BLE001
            cached = None

    if cached is not None and not cached.empty:
        # offline: 과거 계산이면 최신 증분이 필요 없으므로 캐시를 그대로 사용(다운로드 0).
        if offline:
            return cached, "cache"
        # 오늘 이미 받은 캐시면 네트워크 없이 즉시 재사용
        # (주말/공휴일/장중이라 '최근 거래일'이 어제보다 과거여도 그날 한 번만 받으면 됨)
        if use_cache and _fetched_today(path):
            return cached, "cache"
        # 그 외: 증분 업데이트 (마지막 거래일 며칠 전부터 다시 받아 병합)
        last = cached.index.max().date()
        inc_start = (last - timedelta(days=5)).strftime("%Y-%m-%d")
        fresh = _fetch_one(symbol, inc_start, sleep)
        if fresh is not None:
            merged = pd.concat([cached, fresh])
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
            _save(merged, path)   # 저장 -> mtime 갱신 -> 오늘 다시 실행 시 재사용됨
            return merged, "update"
        # 네트워크 실패해도 기존 캐시 반환 (단, mtime은 그대로라 다음 시도 때 재시도)
        return cached, "cache"

    # 캐시 없음 -> 전체 다운로드
    fresh = _fetch_one(symbol, start, sleep)
    if fresh is not None:
        _save(fresh, path)
        return fresh, "new"
    return None, "fail"


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


def download_all(symbols, cfg, label: str = "다운로드", asof_date=None, progress=None,
                 offline: bool = False) -> Dict[str, pd.DataFrame]:
    """심볼 리스트의 일봉을 병렬 다운로드하여 {symbol: df} 반환.

    progress: callable(done:int, total:int) — 진행 상황 콜백(웹 진행바용). 선택.
    offline: True 면 캐시가 있는 종목은 증분 갱신 없이 그대로 사용(과거 backfill용).
    """
    exclusions = load_exclusions(cfg.base_dir)['instruments']
    symbols = [symbol for symbol in symbols if not exclusion_reason(cfg.base_dir,
        'KR' if re.fullmatch(r'[0-9]{4}[0-9A-HJ-NP-TV-Z][0-9KLMN]', str(symbol).upper()) else 'US',
        symbol, records=exclusions)]
    start = ((asof_date or datetime.now().date()) - timedelta(days=cfg.lookback_days)).strftime("%Y-%m-%d")
    results: Dict[str, pd.DataFrame] = {}

    def task(sym):
        df, status = _load_or_update(sym, start, cfg.cache_path, cfg.use_cache,
                                     cfg.request_sleep, offline=offline)
        return sym, df, status

    counts = {"cache": 0, "update": 0, "new": 0, "fail": 0}
    total = len(symbols)
    if progress:
        progress(0, total)
    done = 0
    with ThreadPoolExecutor(max_workers=cfg.max_workers) as ex:
        futs = [ex.submit(task, s) for s in symbols]
        for fut in tqdm(as_completed(futs), total=len(futs), desc=label, ncols=80):
            sym, df, status = fut.result()
            counts[status] = counts.get(status, 0) + 1
            if df is not None and not df.empty:
                results[sym] = df
            done += 1
            # 매 종목마다 콜백은 과하니 25개마다 또는 마지막에 보고(웹 진행바 갱신).
            if progress and (done % 25 == 0 or done == total):
                progress(done, total)
    print(f"[data] 캐시재사용 {counts['cache']} · 갱신 {counts['update']} · "
          f"신규 {counts['new']} · 실패 {counts['fail']}")
    return results
