"""Chart-only downloads and separate ETF OHLCV storage."""
from __future__ import annotations

import os
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import pandas as pd
import requests

from .chart_data import chart_payload
from .data import _cache_file
from .instruments import InstrumentStore
from .weekly import previous_week_friday

class ChartService:
    def __init__(self, cfg, store=None):
        self.cfg = cfg
        self.store = store or InstrumentStore(cfg.base_dir)
        self._locks = {}
        self._lock = threading.Lock()

    def cache_dir(self, instrument):
        group = "etf" if instrument["asset_type"]=="ETF" else "stock"
        return os.path.join(self.cfg.base_dir,"chart_cache",group,instrument["country"])

    def payload(self, requested, asof=""):
        instrument = self.store.resolve(requested)
        directory = self.cache_dir(instrument)
        symbol = instrument["symbol"]
        # Existing equity caches stay usable; ETF requests never use the screener cache.
        legacy = _cache_file(self.cfg.cache_path,symbol)
        if instrument["asset_type"]=="STOCK" and os.path.exists(legacy):
            return self._payload(self.cfg.cache_path,instrument,asof)
        key = (symbol,instrument["country"])
        with self._lock:
            lock = self._locks.setdefault(key,threading.Lock())
        with lock:
            filename = _cache_file(directory,symbol)
            cached = None
            if os.path.exists(filename):
                try:
                    cached = pd.read_parquet(filename)
                    cached.index = pd.to_datetime(cached.index)
                except (OSError,ValueError):
                    pass
            fetched_today = (cached is not None and not cached.empty and
                datetime.fromtimestamp(os.path.getmtime(filename)).date()==datetime.now().date())
            if not fetched_today:
                start = (previous_week_friday()-timedelta(days=self.cfg.lookback_days)).isoformat()
                if cached is not None and not cached.empty:
                    start = (cached.index.max()-pd.Timedelta(days=5)).date().isoformat()
                try:
                    fresh = self.fetch(instrument,start)
                    if cached is not None and not cached.empty:
                        fresh = pd.concat([cached,fresh])
                        fresh = fresh[~fresh.index.duplicated(keep="last")].sort_index()
                    self.save(fresh,filename)
                except Exception as exc:
                    if cached is None or cached.empty:
                        raise ValueError("시세를 가져오지 못했습니다: " + symbol +
                                         " (외부 연결 또는 공급자 응답을 확인해 주세요)") from exc
            self.store.upsert([instrument],"chart")
            return self._payload(directory,instrument,asof)

    @staticmethod
    def _payload(directory,instrument,asof):
        result = chart_payload(directory,instrument["symbol"],instrument,asof)
        result["symbol"] = (instrument["market"] + ":" if instrument["market"] != "US" else "") + instrument["symbol"]
        result["asset_type"] = instrument["asset_type"]
        return result

    @staticmethod
    def fetch(instrument,start):
        symbol = instrument["symbol"]
        headers = {"User-Agent":"Mozilla/5.0"}
        if instrument["country"]=="KR":
            response = requests.get("https://fchart.stock.naver.com/sise.nhn",
                params={"symbol":symbol,"timeframe":"day","count":6000,"requestType":0},
                headers=headers,timeout=20)
            response.raise_for_status()
            rows = [item.attrib["data"].split("|") for item in ET.fromstring(response.content).iter("item")]
            if not rows:
                raise ValueError("빈 한국 시세 응답")
            frame = pd.DataFrame(rows,columns=["Date","Open","High","Low","Close","Volume"])
            frame.index = pd.to_datetime(frame.pop("Date"),format="%Y%m%d")
            frame = frame.loc[frame.index>=pd.Timestamp(start)]
        else:
            response = requests.get("https://query2.finance.yahoo.com/v8/finance/chart/"+symbol,
                params={"period1":int(pd.Timestamp(start).timestamp()),
                        "period2":int(time.time()),"interval":"1d","includeAdjustedClose":"true"},
                headers=headers,timeout=20)
            response.raise_for_status()
            chart = response.json()["chart"]
            if chart.get("error") or not chart.get("result"):
                raise ValueError("빈 미국 시세 응답")
            result = chart["result"][0]
            quotes = result["indicators"]["quote"][0]
            index = pd.to_datetime(result["timestamp"],unit="s").normalize()
            frame = pd.DataFrame({k.title():quotes[k] for k in ["open","high","low","close","volume"]},index=index)
        frame = frame.apply(pd.to_numeric,errors="coerce").dropna()
        frame = frame[(frame["Close"]>0)&(frame["Volume"]>=0)]
        frame = frame[frame["High"]>=frame[["Open","Close","Low"]].max(axis=1)]
        frame = frame[frame["Low"]<=frame[["Open","Close","High"]].min(axis=1)]
        if frame.empty:
            raise ValueError("유효한 OHLCV 데이터가 없습니다.")
        return frame.sort_index()

    @staticmethod
    def save(frame,filename):
        directory = os.path.dirname(filename)
        os.makedirs(directory,exist_ok=True)
        fd,temp = tempfile.mkstemp(prefix=".download-",suffix=".parquet",dir=directory)
        os.close(fd)
        try:
            frame.to_parquet(temp)
            os.replace(temp,filename)
        finally:
            if os.path.exists(temp):
                os.remove(temp)
