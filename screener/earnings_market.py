"""Timestamped market data for completed earnings reports; no AI calculations."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
from urllib.parse import quote

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
           "Accept": "application/json", "Accept-Language": "en-US"}


def _positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _us_cap(ticker):
    url = f"https://api.nasdaq.com/api/quote/{quote(ticker, safe='')}/summary?assetclass=stocks"
    response = requests.get(url, headers=HEADERS, timeout=18)
    response.raise_for_status()
    data = response.json().get("data") or {}
    if str(data.get("symbol", "")).upper() != ticker.upper():
        raise ValueError("시가총액 응답의 종목이 일치하지 않습니다.")
    raw = (data.get("summaryData") or {}).get("MarketCap", {}).get("value", "")
    value = float(str(raw).replace(",", "").replace("$", ""))
    if not _positive(value):
        raise ValueError("시가총액 자료가 없습니다.")
    return value, url


def _chart(ticker, report_end):
    korean = bool(re.fullmatch(r"[0-9]{6}", ticker))
    symbols = [ticker + ".KS", ticker + ".KQ"] if korean else [ticker.replace(".", "-")]
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=370)
    if report_end:
        start = min(start, datetime.fromisoformat(report_end).replace(tzinfo=timezone.utc))
    for symbol in symbols:
        for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
            url = f"https://{host}/v8/finance/chart/{quote(symbol, safe='')}"
            try:
                response = requests.get(url, params={"period1": int(start.timestamp()),
                    "period2": int(now.timestamp()), "interval": "1d", "events": "splits"},
                    headers=HEADERS, timeout=18)
                response.raise_for_status()
                data = response.json()["chart"]["result"][0]
                meta = data["meta"]
                if meta.get("symbol", "").upper() != symbol.upper() or meta.get("instrumentType") != "EQUITY":
                    continue
                return data, url
            except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
                continue
    raise ValueError("주가 자료를 가져오지 못했습니다.")


def market_snapshot(financials, base_dir=None):
    ticker = financials["company"]["ticker"].upper()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshot = {"sourceId": "market_snapshot", "symbol": ticker, "currency": None,
                "price": None, "previousClose": None, "marketCap": None,
                "asOf": None, "marketCapAsOf": None, "collectedAt": now,
                "priceSource": None, "marketCapSource": None, "history": [],
                "historySource": "Yahoo Finance", "splitDates": [],
                "splitSinceReport": False, "notes": []}
    with ThreadPoolExecutor(max_workers=2) as pool:
        cap = pool.submit(_us_cap, ticker) if not ticker.isdigit() else None
        price = pool.submit(_chart, ticker, financials.get("reportPeriod", {}).get("end"))
        try:
            data, url = price.result()
            meta = data["meta"]
            currency = meta.get("currency")
            timestamps = data.get("timestamp", [])
            closes = data["indicators"]["quote"][0].get("close", [])
            cutoff = (datetime.now(timezone.utc) - timedelta(days=366)).date().isoformat()
            history = [{"date": datetime.fromtimestamp(ts, timezone.utc).date().isoformat(), "close": value}
                       for ts, value in zip(timestamps, closes) if _positive(value)]
            history = [point for point in history if point["date"] >= cutoff]
            value = meta.get("regularMarketPrice")
            stamp = meta.get("regularMarketTime")
            if not _positive(value) or not stamp or not currency:
                raise ValueError("주가 기준시점 또는 통화가 없습니다.")
            previous = meta.get("previousClose")
            if not _positive(previous) and len(history) > 1 and history[-1]["date"] == datetime.fromtimestamp(stamp, timezone.utc).date().isoformat():
                previous = history[-2]["close"]
            snapshot.update(price=value, previousClose=previous if _positive(previous) else None, currency=currency,
                            asOf=datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec="seconds"),
                            priceSource=url, history=history)
            end = financials.get("reportPeriod", {}).get("end", "")
            snapshot["splitDates"] = [datetime.fromtimestamp(item["date"], timezone.utc).date().isoformat()
                                      for item in (data.get("events", {}).get("splits") or {}).values()]
            snapshot["splitSinceReport"] = any(day > end for day in snapshot["splitDates"])
            # Some chart providers include market cap directly in quote metadata.
            if _positive(meta.get("marketCap")):
                snapshot.update(marketCap=meta["marketCap"], marketCapSource=url, marketCapAsOf=snapshot["asOf"])
        except Exception:
            snapshot["notes"].append("주가 자료 조회 실패")
        if cap:
            try:
                value, url = cap.result()
                if snapshot["currency"] in (None, "USD"):
                    snapshot.update(marketCap=value, marketCapSource=url, marketCapAsOf=now)
                    snapshot["currency"] = snapshot["currency"] or "USD"
            except Exception:
                snapshot["notes"].append("시가총액 조회 실패")
    if snapshot["marketCap"] is None and ticker.isdigit():
        # Naver publishes the security's market cap alongside its Korean quote.
        url = f"https://m.stock.naver.com/api/stock/{ticker}/integration"
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            response.raise_for_status()
            payload = response.json()
            item = next(item for item in payload.get("totalInfos", []) if item.get("code") == "marketValue")
            raw = str(item["value"]).replace(",", "").replace(" ", "")
            if "조" in raw:
                major, _, minor = raw.partition("조")
                value = float(major) * 1e12 + (float(minor.removesuffix("억")) * 1e8 if minor else 0)
            else:
                value = float(raw.removesuffix("억")) * 1e8
            if _positive(value) and snapshot["currency"] in (None, "KRW"):
                snapshot.update(marketCap=value, marketCapSource=url, marketCapAsOf=now, currency="KRW")
        except Exception:
            snapshot["notes"].append("시가총액 조회 실패")
    if base_dir:
        base = Path(base_dir)
        cache = base / "earnings_workspace" / "market" / (ticker + ".json")
        saved = {}
        if cache.is_file():
            try:
                saved = json.loads(cache.read_text(encoding="utf-8"))
                if saved.get("symbol") != ticker:
                    saved = {}
            except (OSError, ValueError):
                pass
        used_saved = False
        if snapshot["price"] is None and _positive(saved.get("price")):
            for key in ("price", "previousClose", "currency", "asOf", "priceSource", "splitDates"):
                if key in saved:
                    snapshot[key] = saved[key]
            snapshot["splitSinceReport"] = any(day > financials["reportPeriod"]["end"] for day in snapshot["splitDates"])
            used_saved = True
        if snapshot["marketCap"] is None and _positive(saved.get("marketCap")) and saved.get("currency") == snapshot["currency"]:
            for key in ("marketCap", "marketCapSource", "marketCapAsOf"):
                snapshot[key] = saved.get(key)
            used_saved = True
        if not snapshot["history"]:
            for path in (base / "cache" / (ticker + ".parquet"), base / "chart_cache" / "stock" / ("KR" if ticker.isdigit() else "US") / (ticker + ".parquet")):
                if not path.is_file():
                    continue
                try:
                    import pandas as pd
                    frame = pd.read_parquet(path).sort_index()
                    cutoff = datetime.now(timezone.utc).date() - timedelta(days=366)
                    history = [{"date": pd.Timestamp(day).date().isoformat(), "close": float(value)}
                               for day, value in frame["Close"].items()
                               if pd.Timestamp(day).date() >= cutoff and _positive(value)]
                    if history:
                        snapshot.update(history=history[-500:], historySource="Finance 저장 가격 자료")
                        if snapshot["price"] is None:
                            snapshot.update(price=history[-1]["close"], asOf=history[-1]["date"] + " 종가",
                                currency="KRW" if ticker.isdigit() else "USD", priceSource="Finance 가격 캐시",
                                previousClose=history[-2]["close"] if len(history)>1 else None)
                        used_saved = True
                        break
                except (OSError, ValueError, KeyError, ImportError):
                    continue
        if used_saved:
            snapshot["notes"].append("저장된 시장 자료 사용 · 각 항목의 기준시점 참조")
        if snapshot["price"] is not None or snapshot["marketCap"] is not None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot
