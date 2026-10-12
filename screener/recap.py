"""주간 시장 Recap: 주요 지수 수집 + 지표 계산 + Codex 코멘터리 생성.

- 데이터: FinanceDataReader (Yahoo 소스, '^' 접두사 티커로 통일 → 최신값 안정적)
- 지표: 현재가, 1W/1M/3M/YTD 등락률, 52주 고점 대비, 미니 스파크라인(SVG)
- 코멘터리: 외부 CLI(codex)를 subprocess로 호출 (LLM API 비용 0)
- 결과는 recap_cache.json 에 저장 → 서버 재시작/재접속 시 즉시 표시

API 키 불필요. 서버에서 '업데이트' 클릭 시 refresh_recap() 호출.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
import FinanceDataReader as fdr


# ----------------------------------------------------------------------------
# 지수 정의 (그룹 → [(표시명, FDR 티커)]) — 검증된 '^' 접두사 티커
# ----------------------------------------------------------------------------
DEFAULT_INDICES: List[Dict] = [
    {"group": "한국", "name": "코스피", "symbol": "^KS11"},
    {"group": "한국", "name": "코스닥", "symbol": "^KQ11"},
    {"group": "미국", "name": "S&P500", "symbol": "^GSPC"},
    {"group": "미국", "name": "나스닥", "symbol": "^IXIC"},
    {"group": "미국", "name": "다우", "symbol": "^DJI"},
    {"group": "미국", "name": "러셀2000", "symbol": "^RUT"},
    {"group": "미국", "name": "필라델피아반도체", "symbol": "^SOX"},
    {"group": "아시아", "name": "니케이225", "symbol": "^N225"},
    {"group": "아시아", "name": "대만가권", "symbol": "^TWII"},
]


@dataclass
class RecapConfig:
    base_dir: str = "."
    indices: List[Dict] = field(default_factory=lambda: list(DEFAULT_INDICES))
    lookback_days: int = 400  # 52주 비교 + YTD 위해 1년+ 확보
    # 코멘터리 생성 CLI. {prompt} 자리표시자가 있으면 치환, 없으면 stdin으로 전달.
    commentary_cmd: str = "codex exec {prompt}"
    commentary_timeout: int = 180
    commentary_enabled: bool = True

    @property
    def cache_file(self) -> str:
        return os.path.join(self.base_dir, "recap_cache.json")


# ----------------------------------------------------------------------------
# 데이터 수집 + 지표 계산
# ----------------------------------------------------------------------------
def _pct(cur: float, past: Optional[float]) -> Optional[float]:
    if past is None or past == 0:
        return None
    return (cur / past - 1.0) * 100.0


def _value_on_or_before(s: pd.Series, target: pd.Timestamp) -> Optional[float]:
    """target 날짜 또는 그 이전 가장 가까운 값(휴장일 보정)."""
    sub = s[s.index <= target]
    if sub.empty:
        return None
    return float(sub.iloc[-1])


def _fetch_index(symbol: str, start: str) -> Optional[pd.DataFrame]:
    for attempt in range(3):
        try:
            df = fdr.DataReader(symbol, start)
            if df is None or df.empty:
                return None
            df.index = pd.to_datetime(df.index)
            return df.sort_index()
        except Exception:  # noqa: BLE001
            continue
    return None


def _sparkline_svg(closes: List[float], up: bool, width: int = 120, height: int = 36) -> str:
    """최근 종가 흐름을 인라인 SVG 스파크라인으로. 상승=빨강, 하락=파랑(한국식)."""
    if not closes or len(closes) < 2:
        return ""
    lo, hi = min(closes), max(closes)
    rng = (hi - lo) or 1.0
    n = len(closes)
    pts = []
    for i, c in enumerate(closes):
        x = i / (n - 1) * (width - 4) + 2
        y = height - 2 - (c - lo) / rng * (height - 4)
        pts.append(f"{x:.1f},{y:.1f}")
    color = "#e5484d" if up else "#3b82f6"
    path = " ".join(pts)
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none" class="spark">'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.5" '
        f'stroke-linejoin="round" stroke-linecap="round" points="{path}"/>'
        f'</svg>'
    )


def compute_index_row(meta: Dict, df: pd.DataFrame) -> Dict:
    """한 지수의 표 행 데이터 계산."""
    close = df["Close"].dropna()
    last_date = close.index.max()
    cur = float(close.iloc[-1])

    w1 = _value_on_or_before(close, last_date - timedelta(days=7))
    m1 = _value_on_or_before(close, last_date - timedelta(days=30))
    m3 = _value_on_or_before(close, last_date - timedelta(days=91))

    # YTD: 올해 첫 거래일 종가
    ytd_base = None
    this_year = close[close.index >= pd.Timestamp(last_date.year, 1, 1)]
    if not this_year.empty:
        ytd_base = float(this_year.iloc[0])

    # 52주 고점 대비
    last_52w = close[close.index >= last_date - timedelta(weeks=52)]
    high_52w = float(last_52w.max()) if not last_52w.empty else cur
    from_high = _pct(cur, high_52w)

    spark_src = list(last_52w.iloc[-60:].astype(float)) if not last_52w.empty else []
    chg_1w = _pct(cur, w1)
    spark = _sparkline_svg(spark_src, up=(chg_1w or 0) >= 0)

    return {
        "group": meta["group"],
        "name": meta["name"],
        "symbol": meta["symbol"],
        "date": last_date.strftime("%m-%d"),
        "price": cur,
        "chg_1w": chg_1w,
        "chg_1m": _pct(cur, m1),
        "chg_3m": _pct(cur, m3),
        "chg_ytd": _pct(cur, ytd_base),
        "from_52w_high": from_high,
        "spark": spark,
    }


def collect_indices(rcfg: RecapConfig) -> List[Dict]:
    start = (datetime.now() - timedelta(days=rcfg.lookback_days)).strftime("%Y-%m-%d")
    rows: List[Dict] = []
    for meta in rcfg.indices:
        df = _fetch_index(meta["symbol"], start)
        if df is None or df.empty:
            rows.append({
                "group": meta["group"], "name": meta["name"], "symbol": meta["symbol"],
                "date": "-", "price": None, "chg_1w": None, "chg_1m": None,
                "chg_3m": None, "chg_ytd": None, "from_52w_high": None, "spark": "",
                "error": True,
            })
            continue
        rows.append(compute_index_row(meta, df))
    return rows


# ----------------------------------------------------------------------------
# 코멘터리 생성 (외부 CLI 호출)
# ----------------------------------------------------------------------------
def _build_prompt(rows: List[Dict]) -> str:
    def f(v):
        return f"{v:+.1f}%" if isinstance(v, (int, float)) else "N/A"

    lines = []
    for r in rows:
        if r.get("error"):
            continue
        lines.append(
            f"- [{r['group']}] {r['name']}: 종가 {r['price']:,.2f} "
            f"(1W {f(r['chg_1w'])}, 1M {f(r['chg_1m'])}, 3M {f(r['chg_3m'])}, "
            f"YTD {f(r['chg_ytd'])}, 52주고점대비 {f(r['from_52w_high'])})"
        )
    data_block = "\n".join(lines)
    return (
        "너는 금융 시장 애널리스트다. 아래는 주요 글로벌 지수의 주간 성과 데이터다.\n"
        "이 데이터를 바탕으로 한국어로 '지난주 시장 Recap - Editor's Comment'를 작성하라.\n\n"
        "요구사항:\n"
        "- 3~4개 문단, 각 문단은 2~4문장\n"
        "- 첫 문단: 지난주 전체 시장을 한 문장으로 요약 후 핵심 지수 등락 설명\n"
        "- 중간 문단: 눈에 띄는 지수(강세/약세), 섹터(반도체 등), 지역별 대비\n"
        "- 마지막 문단: 길게 본 추세(52주 고점 대비, YTD)와 전망/주목 포인트\n"
        "- 과장·투자권유 금지. 수치는 데이터에 있는 것만 사용. 마크다운 기호 없이 평문으로.\n\n"
        f"데이터:\n{data_block}\n"
    )


def generate_commentary(rows: List[Dict], rcfg: RecapConfig) -> Dict:
    """외부 CLI로 코멘터리 생성. 반환: {text, source, ok}."""
    if not rcfg.commentary_enabled:
        return {"text": "", "source": "disabled", "ok": False}

    prompt = _build_prompt(rows)
    cmd_tmpl = rcfg.commentary_cmd
    try:
        if "{prompt}" in cmd_tmpl:
            # 프롬프트를 인자로 안전하게 치환
            argv = shlex.split(cmd_tmpl.replace("{prompt}", ""))
            argv.append(prompt)
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=rcfg.commentary_timeout,
                cwd=rcfg.base_dir,
            )
        else:
            # stdin 으로 전달
            argv = shlex.split(cmd_tmpl)
            proc = subprocess.run(
                argv, input=prompt, capture_output=True, text=True,
                timeout=rcfg.commentary_timeout, cwd=rcfg.base_dir,
            )
        out = (proc.stdout or "").strip()
        if proc.returncode == 0 and out:
            return {"text": out, "source": "codex", "ok": True}
        err = (proc.stderr or "").strip()[:300]
        return {
            "text": f"(코멘터리 생성 실패: 종료코드 {proc.returncode}) {err}",
            "source": "codex", "ok": False,
        }
    except FileNotFoundError:
        return {
            "text": "(코멘터리 CLI를 찾을 수 없습니다. config.yaml의 recap.commentary_cmd 를 "
                    "설치된 명령에 맞게 설정하세요. 예: 'codex exec {prompt}')",
            "source": "codex", "ok": False,
        }
    except subprocess.TimeoutExpired:
        return {"text": "(코멘터리 생성 시간 초과)", "source": "codex", "ok": False}
    except Exception as e:  # noqa: BLE001
        return {"text": f"(코멘터리 생성 오류: {e})", "source": "codex", "ok": False}


# ----------------------------------------------------------------------------
# 캐시 I/O + 상위 refresh 함수
# ----------------------------------------------------------------------------
def load_recap(rcfg: RecapConfig) -> Optional[Dict]:
    path = rcfg.cache_file
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def save_recap(rcfg: RecapConfig, payload: Dict) -> None:
    try:
        with open(rcfg.cache_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


def refresh_recap(rcfg: RecapConfig, with_commentary: bool = True) -> Dict:
    """지수 데이터 수집 + (선택)코멘터리 생성 → 캐시 저장 → payload 반환."""
    rows = collect_indices(rcfg)
    commentary = {"text": "", "source": "", "ok": False}
    if with_commentary:
        commentary = generate_commentary(rows, rcfg)
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": rows,
        "commentary": commentary,
    }
    save_recap(rcfg, payload)
    return payload
