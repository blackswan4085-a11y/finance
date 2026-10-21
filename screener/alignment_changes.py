"""정배열(이동평균 정배열) 종목 스냅샷 저장 + 주간 신규/이탈 비교.

- 스크리너가 성공적으로 갱신될 때마다, 결과에서 aligned==True 인 종목 목록을
  기준일(asof_date)과 함께 스냅샷으로 저장한다(alignment_snapshots.json).
- 같은 기준일이면 덮어쓰기(하루 여러 번 실행해도 그 주 1개), 다른 기준일이면
  새로 쌓는다 → 자연스럽게 "주간" 단위 스냅샷이 된다.
- changes()는 가장 최근 2개 스냅샷을 비교해 신규 진입/이탈 정배열 종목을 반환한다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading

_lock = threading.Lock()
MAX_SNAPSHOTS = 12  # 최근 N개만 보관


def _path(base_dir: str) -> Path:
    return Path(base_dir) / "alignment_snapshots.json"


def _load(base_dir: str) -> list[dict]:
    path = _path(base_dir)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (OSError, ValueError):
            pass
    return []


def _save(base_dir: str, snapshots: list[dict]) -> None:
    path = _path(base_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshots, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _aligned_rows(frame) -> list[dict]:
    """DataFrame 에서 정배열 종목만 추출(symbol·name·market·country)."""
    if frame is None or getattr(frame, "empty", True) or "aligned" not in frame:
        return []
    sub = frame[frame["aligned"] == True]  # noqa: E712 — pandas 불리언 마스킹
    out = []
    for _, r in sub.iterrows():
        out.append({
            "symbol": str(r.get("symbol", "")),
            "name": str(r.get("name", "")),
            "market": str(r.get("market", "")),
            "country": str(r.get("country", "")),
        })
    return out


def record(base_dir: str, frame, asof_date: str) -> None:
    """스크리너 결과에서 정배열 종목을 기준일 스냅샷으로 저장.

    같은 asof_date 스냅샷이 있으면 교체, 없으면 추가. 최근 MAX_SNAPSHOTS 개만 유지.
    """
    asof_date = str(asof_date)
    rows = _aligned_rows(frame)
    snapshot = {"asof_date": asof_date, "symbols": rows}
    with _lock:
        snapshots = [s for s in _load(base_dir) if s.get("asof_date") != asof_date]
        snapshots.append(snapshot)
        snapshots.sort(key=lambda s: s.get("asof_date", ""))
        snapshots = snapshots[-MAX_SNAPSHOTS:]
        _save(base_dir, snapshots)


def changes(base_dir: str) -> dict:
    """가장 최근 2개 스냅샷을 비교해 신규/이탈 정배열 종목 반환.

    반환: {current, previous, added[], removed[], kept_count}
      added:   직전엔 없고 현재 정배열인 종목(신규 진입)
      removed: 직전엔 정배열이고 현재 빠진 종목(이탈)
    """
    snapshots = _load(base_dir)
    if not snapshots:
        return {"current": "", "previous": "", "added": [], "removed": [], "kept_count": 0,
                "message": "아직 저장된 스냅샷이 없습니다. 스크리너를 한 번 이상 실행해 주세요."}
    current = snapshots[-1]
    if len(snapshots) < 2:
        return {"current": current["asof_date"], "previous": "", "added": [], "removed": [],
                "kept_count": len(current["symbols"]),
                "message": "비교할 직전 스냅샷이 아직 없습니다. 다음 주 스크리너 실행 후 변화가 표시됩니다."}
    previous = snapshots[-2]
    cur_map = {s["symbol"]: s for s in current["symbols"]}
    prev_set = {s["symbol"] for s in previous["symbols"]}
    cur_set = set(cur_map)
    prev_map = {s["symbol"]: s for s in previous["symbols"]}
    added = [cur_map[sym] for sym in cur_map if sym not in prev_set]
    removed = [prev_map[sym] for sym in prev_map if sym not in cur_set]
    added.sort(key=lambda s: (s.get("country", ""), s.get("symbol", "")))
    removed.sort(key=lambda s: (s.get("country", ""), s.get("symbol", "")))
    return {"current": current["asof_date"], "previous": previous["asof_date"],
            "added": added, "removed": removed,
            "kept_count": len(cur_set & prev_set), "message": ""}
