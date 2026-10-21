"""Publish only evaluated scans, with an atomic previous-result backup."""
from datetime import datetime
import json
import os
from pathlib import Path
from uuid import uuid4


def read_screen_cache(path):
    path = Path(path)
    for candidate in (path, path.with_name("screen_cache.previous.json")):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(data.get("rows"), list) or not data.get("asof_date"):
                continue
            # Legacy empty results cannot distinguish a failed scan from zero matches.
            if not data["rows"] and data.get("scan", {}).get("evaluated_count", 0) <= 0:
                continue
            return data
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return None


def _atomic_write(path, data):
    temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    os.replace(temp, path)


def publish_screen_cache(path, frame, asof_date):
    """A genuine zero-match scan is valid only after stocks were evaluated."""
    scan = frame.attrs.get("scan", {})
    if scan.get("evaluated_count", 0) <= 0:
        raise RuntimeError("수집·조건 계산 완료를 확인하지 못해 기존 결과를 유지했습니다.")
    data = {"asof_date": asof_date.isoformat(), "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "rows": json.loads(frame.to_json(orient="records", force_ascii=False)), "scan": scan}
    path = Path(path)
    previous = read_screen_cache(path)
    if previous:
        _atomic_write(path.with_name("screen_cache.previous.json"), previous)
    _atomic_write(path, data)
    return data
