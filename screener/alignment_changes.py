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
    """정배열 종목 목록 추출(symbol·name·market·country).

    run_screen 이 필터 전에 담아 둔 attrs['aligned_all'] 을 우선 사용한다(전체 정배열).
    없으면(구버전/외부 호출) 필터 후 DataFrame 에서 aligned==True 로 폴백한다.
    """
    attr = getattr(frame, "attrs", {}).get("aligned_all") if frame is not None else None
    if isinstance(attr, list):
        return [{"symbol": str(x.get("symbol", "")), "name": str(x.get("name", "")),
                 "market": str(x.get("market", "")), "country": str(x.get("country", ""))}
                for x in attr]
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


def has_comparison(base_dir: str) -> bool:
    """비교 가능한 스냅샷(2개 이상)이 있는지."""
    return len(_load(base_dir)) >= 2


_backfill_lock = threading.Lock()
_backfill_running = False


def backfill_running() -> bool:
    return _backfill_running


def backfill(base_dir: str, cfg, weeks: int = 2) -> dict:
    """저장된 스냅샷이 부족할 때, 과거 주(금요일) 기준으로 정배열을 재계산해 채운다.

    첫 주차 계산에서 전 종목 주가를 받아 캐시에 저장하면, 나머지 주차는 같은 날
    같은 캐시를 재사용하므로 다운로드는 1회로 끝난다(data._load_or_update 의
    '오늘 받은 캐시 재사용'). 전 종목 스캔이라 캐시가 비어 있으면 최초 1회는
    수십 분 걸릴 수 있다.

    재진입 방지: 이미 실행 중이면 바로 반환(사용자가 버튼을 여러 번 눌러도 1회만 수행).
    반환: {created, skipped, busy}.
    """
    global _backfill_running
    from datetime import timedelta
    from .screen import run_screen
    from .weekly import previous_week_friday

    with _backfill_lock:
        if _backfill_running:
            return {"created": [], "skipped": [], "busy": True}
        _backfill_running = True
    try:
        base_friday = previous_week_friday()
        targets = sorted(base_friday - timedelta(days=7 * i) for i in range(weeks))
        existing = {s.get("asof_date") for s in _load(base_dir)}
        created, skipped = [], []
        for asof in targets:
            iso = asof.isoformat()
            if iso in existing:
                skipped.append(iso)
                continue
            # 첫 호출이 캐시를 채우고, 이후 호출은 같은 날 캐시를 재사용(다운로드 0).
            df = run_screen(cfg, asof_date=asof)
            record(base_dir, df, iso)
            created.append(iso)
        return {"created": created, "skipped": skipped, "busy": False}
    finally:
        with _backfill_lock:
            _backfill_running = False


def changes(base_dir: str) -> dict:
    """가장 최근 2개 스냅샷을 비교해 신규/이탈 정배열 종목 반환.

    반환: {current, previous, added[], removed[], kept_count}
      added:   직전엔 없고 현재 정배열인 종목(신규 진입)
      removed: 직전엔 정배열이고 현재 빠진 종목(이탈)
    """
    snapshots = _load(base_dir)
    if not snapshots:
        return {"current": "", "previous": "", "added": [], "removed": [], "kept_count": 0,
                "can_backfill": True,
                "message": "저장된 스냅샷이 없습니다. '지난 데이터로 비교 생성'을 누르면 과거 2주 기준으로 즉시 계산합니다."}
    current = snapshots[-1]
    if len(snapshots) < 2:
        return {"current": current["asof_date"], "previous": "", "added": [], "removed": [],
                "kept_count": len(current["symbols"]), "can_backfill": True,
                "message": "비교할 직전 스냅샷이 없습니다. '지난 데이터로 비교 생성'을 누르면 과거 기준으로 즉시 계산합니다."}
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
            "kept_count": len(cur_set & prev_set), "can_backfill": False, "message": ""}
