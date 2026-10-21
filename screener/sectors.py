"""종목별 섹터를 파일(sectors.json)에 영구 저장/로드.

- 종목코드(symbol)를 키로 사용하므로, 종목이 신고가 목록에서 빠졌다 다시 들어와도
  섹터가 그대로 유지된다.
- 브라우저 캐시/localStorage와 무관하게 사용자 PC의 파일에 저장된다.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Dict

_lock = threading.Lock()


def _path(base_dir: str) -> str:
    return os.path.join(base_dir, "sectors.json")


def load_manual_sectors(base_dir: str) -> Dict[str, str]:
    """{symbol: sector} 로드. 파일 없으면 빈 dict."""
    path = _path(base_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            # 값은 문자열로 정규화
            return {str(k): ("" if v is None else str(v)) for k, v in data.items()}
    except Exception:  # noqa: BLE001
        pass
    return {}


def load_sectors(base_dir: str) -> Dict[str, str]:
    """Verified automatic US assignments, with all manual values taking priority."""
    from .sector_classification import automatic_sectors
    mapping = automatic_sectors(base_dir)
    mapping.update(load_manual_sectors(base_dir))
    return mapping


def reset_sector(base_dir: str, symbol: str) -> Dict[str, str]:
    """Remove a personal override and restore automatic classification, if available."""
    with _lock:
        mapping = load_manual_sectors(base_dir)
        mapping.pop(str(symbol).strip(), None)
        path = _path(base_dir)
        with open(path + '.tmp', 'w', encoding='utf-8') as stream:
            json.dump(mapping, stream, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(path + '.tmp', path)
    return load_sectors(base_dir)


def save_sectors(base_dir: str, mapping: Dict[str, str]) -> None:
    """{symbol: sector} 전체를 저장 (원자적 쓰기)."""
    path = _path(base_dir)
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)


def set_sector(base_dir: str, symbol: str, sector: str) -> Dict[str, str]:
    """한 종목의 섹터를 설정하고 저장. 빈 값은 자동 분류를 가리는 수동 공란으로 저장. 갱신된 전체 맵 반환."""
    symbol = str(symbol).strip()
    sector = (sector or "").strip()
    with _lock:
        mapping = load_manual_sectors(base_dir)
        if sector:
            mapping[symbol] = sector
        else:
            mapping[symbol] = ""
        # save_sectors도 _lock을 쓰므로 여기선 직접 파일 기록
        path = _path(base_dir)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
    return load_sectors(base_dir)
