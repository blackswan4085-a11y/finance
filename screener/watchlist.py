"""관심종목(워치리스트)을 파일(watchlist.json)에 영구 저장/로드.

- 종목코드(symbol)+국가(country)를 키로 사용한다.
- 저장 항목: symbol, country, name, market (목록 표시에 필요한 최소 정보).
- InstrumentStore.resolve 로 입력을 검증·정규화하므로, 존재하지 않는 종목이나
  수집 제외 종목(우선주·스팩 등)은 추가되지 않는다.
- 브라우저 캐시와 무관하게 사용자 PC의 파일에 저장된다(sectors.json 과 동일 방식).
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime

_lock = threading.Lock()


def _path(base_dir: str) -> str:
    return os.path.join(base_dir, "watchlist.json")


def _key(country: str, symbol: str) -> str:
    return f"{country}:{symbol}"


def load(base_dir: str) -> list[dict]:
    """관심종목 리스트 반환(추가한 순서 유지). 파일 없으면 빈 리스트."""
    path = _path(base_dir)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            out = []
            for item in data:
                if isinstance(item, dict) and item.get("symbol") and item.get("country"):
                    out.append({
                        "symbol": str(item["symbol"]),
                        "country": str(item["country"]),
                        "name": str(item.get("name", item["symbol"])),
                        "market": str(item.get("market", "")),
                        "added_at": str(item.get("added_at", "")),
                    })
            return out
    except (OSError, ValueError, TypeError):
        pass
    return []


def _save(base_dir: str, items: list[dict]) -> None:
    path = _path(base_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def add(base_dir: str, store, value: str) -> list[dict]:
    """종목을 관심종목에 추가. store.resolve 로 검증·정규화. 갱신된 리스트 반환.

    이미 있으면 중복 추가하지 않는다.
    """
    # resolve 는 코드 형식·거래소·수집 제외(우선주/스팩)를 검증한다. 실패 시 ValueError.
    # 종목 DB가 아직 비어 있어도(새 저장소) 형식이 맞으면 담을 수 있도록 UNKNOWN 은 허용한다.
    # DB가 채워지면 같은 종목이 실제 이름으로 표시된다.
    row = store.resolve(value)
    symbol, country = str(row["symbol"]), str(row["country"])
    entry = {
        "symbol": symbol,
        "country": country,
        "name": str(row.get("name") or symbol),
        "market": str(row.get("market") or ""),
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _lock:
        items = load(base_dir)
        if any(it["symbol"] == symbol and it["country"] == country for it in items):
            return items  # 이미 등록됨
        items.append(entry)
        _save(base_dir, items)
    return items


def remove(base_dir: str, symbol: str, country: str) -> list[dict]:
    """관심종목에서 제거. 갱신된 리스트 반환."""
    symbol, country = str(symbol).strip(), str(country).strip()
    with _lock:
        items = [it for it in load(base_dir)
                 if not (it["symbol"] == symbol and it["country"] == country)]
        _save(base_dir, items)
    return items


def contains(base_dir: str, symbol: str, country: str) -> bool:
    symbol, country = str(symbol).strip(), str(country).strip()
    return any(it["symbol"] == symbol and it["country"] == country for it in load(base_dir))
