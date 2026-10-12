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

from . import naver


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
    {"group": "일본", "name": "니케이225", "symbol": "^N225"},
    {"group": "중화권", "name": "대만가권", "symbol": "^TWII"},
    {"group": "중화권", "name": "상해종합", "symbol": "SSEC"},
    {"group": "중화권", "name": "CSI300", "symbol": "000300"},
    {"group": "중화권", "name": "홍콩 항셍", "symbol": "^HSI"},
    {"group": "인도", "name": "센섹스", "symbol": "^BSESN"},
    {"group": "인도", "name": "니프티50", "symbol": "^NSEI"},
    {"group": "유럽", "name": "유로스톡스50", "symbol": "^STOXX50E"},
    {"group": "유럽", "name": "독일 DAX", "symbol": "^GDAXI"},
    {"group": "유럽", "name": "영국 FTSE100", "symbol": "^FTSE"},
    {"group": "유럽", "name": "프랑스 CAC40", "symbol": "^FCHI"},
    {"group": "북미", "name": "캐나다 TSX", "symbol": "^GSPTSE"},
]


# ----------------------------------------------------------------------------
# 주요 원자재 (1-2) — FDR 선물 심볼 '=F'. 검증 완료.
# ----------------------------------------------------------------------------
DEFAULT_COMMODITIES: List[Dict] = [
    {"group": "귀금속",   "name": "금",         "symbol": "GC=F"},
    {"group": "귀금속",   "name": "은",         "symbol": "SI=F"},
    {"group": "귀금속",   "name": "플래티넘",    "symbol": "PL=F"},
    {"group": "귀금속",   "name": "팔라듐",      "symbol": "PA=F"},
    {"group": "산업금속", "name": "구리",        "symbol": "HG=F"},
    {"group": "에너지",   "name": "WTI 원유",    "symbol": "CL=F"},
    {"group": "에너지",   "name": "브렌트유",    "symbol": "BZ=F"},
    {"group": "에너지",   "name": "천연가스",    "symbol": "NG=F"},
    {"group": "농산물",   "name": "옥수수",      "symbol": "ZC=F"},
    {"group": "농산물",   "name": "밀",         "symbol": "ZW=F"},
    {"group": "농산물",   "name": "대두",        "symbol": "ZS=F"},
]


# ----------------------------------------------------------------------------
# 1-3. 국채 금리 / 환율 — 네이버 금융 공개 API (일별, 키 불필요). 검증 완료.
# ----------------------------------------------------------------------------
DEFAULT_RATES: List[Dict] = [
    {"group": "미국", "name": "미국 2년",  "code": "US2YT=RR"},
    {"group": "미국", "name": "미국 10년", "code": "US10YT=RR"},
    {"group": "미국", "name": "미국 30년", "code": "US30YT=RR"},
    {"group": "한국", "name": "한국 3년",  "code": "KR3YT=RR"},
    {"group": "한국", "name": "한국 10년", "code": "KR10YT=RR"},
    {"group": "유럽", "name": "독일 10년", "code": "DE10YT=RR"},
    {"group": "유럽", "name": "영국 10년", "code": "GB10YT=RR"},
    {"group": "아시아", "name": "일본 10년", "code": "JP10YT=RR"},
    {"group": "아시아", "name": "중국 10년", "code": "CN10YT=RR"},
]

DEFAULT_FX: List[Dict] = [
    {"group": "지수",  "name": "달러인덱스",  "code": ".DXY"},
    {"group": "원화",  "name": "원/달러",    "code": "FX_USDKRW"},
    {"group": "원화",  "name": "원/엔(100)", "code": "FX_JPYKRW"},
    {"group": "원화",  "name": "원/유로",    "code": "FX_EURKRW"},
    {"group": "원화",  "name": "원/위안",    "code": "FX_CNYKRW"},
]


@dataclass
class RecapConfig:
    base_dir: str = "."
    indices: List[Dict] = field(default_factory=lambda: list(DEFAULT_INDICES))
    commodities: List[Dict] = field(default_factory=lambda: list(DEFAULT_COMMODITIES))
    rates: List[Dict] = field(default_factory=lambda: list(DEFAULT_RATES))
    fx: List[Dict] = field(default_factory=lambda: list(DEFAULT_FX))
    lookback_days: int = 400  # 52주 비교 + YTD 위해 1년+ 확보
    # 코멘터리 생성 CLI. {prompt} 자리표시자가 있으면 치환, 없으면 stdin으로 전달.
    #   codex는 git repo 밖에서도 돌도록 --skip-git-repo-check 필요.
    commentary_cmd: str = ("codex exec --skip-git-repo-check "
                           "--sandbox read-only --color never {prompt}")
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


def collect_items(items: List[Dict], lookback_days: int) -> List[Dict]:
    """지수/원자재 등 임의의 심볼 목록을 수집해 표 행 리스트로 반환."""
    start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    rows: List[Dict] = []
    for meta in items:
        df = _fetch_index(meta["symbol"], start)
        if df is None or df.empty or df["Close"].dropna().empty:
            rows.append({
                "group": meta["group"], "name": meta["name"], "symbol": meta["symbol"],
                "date": "-", "price": None, "chg_1w": None, "chg_1m": None,
                "chg_3m": None, "chg_ytd": None, "from_52w_high": None, "spark": "",
                "error": True,
            })
            continue
        rows.append(compute_index_row(meta, df))
    return rows


def collect_indices(rcfg: RecapConfig) -> List[Dict]:
    return collect_items(rcfg.indices, rcfg.lookback_days)


def collect_commodities(rcfg: RecapConfig) -> List[Dict]:
    return collect_items(rcfg.commodities, rcfg.lookback_days)


# ----------------------------------------------------------------------------
# 코멘터리 생성 (외부 CLI 호출)
# ----------------------------------------------------------------------------
def _rows_to_lines(rows: List[Dict]) -> str:
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
    return "\n".join(lines)


def _rate_fx_lines(rows: List[Dict]) -> str:
    lines = []
    for r in rows:
        if r.get("error") or r.get("price") is None:
            continue
        unit = r.get("unit", "")
        def d(v):
            if not isinstance(v, (int, float)):
                return "N/A"
            return f"{v:+.0f}bp" if unit == "bp" else f"{v:+.2f}%"
        lines.append(
            f"- [{r['group']}] {r['name']}: {r['price']:,.3f} "
            f"(1W {d(r['chg_1w'])}, 1M {d(r['chg_1m'])}, 3M {d(r['chg_3m'])})"
        )
    return "\n".join(lines)


def _build_prompt(index_rows: List[Dict], commodity_rows: Optional[List[Dict]] = None,
                  rate_rows: Optional[List[Dict]] = None,
                  fx_rows: Optional[List[Dict]] = None) -> str:
    index_block = _rows_to_lines(index_rows)
    commodity_block = _rows_to_lines(commodity_rows or [])
    rate_block = _rate_fx_lines(rate_rows or [])
    fx_block = _rate_fx_lines(fx_rows or [])
    parts = [
        "너는 금융 시장 애널리스트다. 아래는 지난주 주요 글로벌 지수·원자재·국채금리·환율 데이터다.\n"
        "이 데이터를 바탕으로 한국어로 '지난주 시장 Recap - Editor's Comment'를 작성하라.\n\n"
        "요구사항:\n"
        "- 4~6개 문단, 각 문단은 2~4문장\n"
        "- 첫 문단: 지난주 전체 시장을 한 문장으로 요약 후 핵심 지수 등락 설명\n"
        "- 지수 문단: 눈에 띄는 지수(강세/약세), 섹터, 지역별 대비\n"
        "- 원자재 문단: 귀금속·에너지·농산물 흐름과 의미(인플레·경기 신호 등)\n"
        "- 금리/환율 문단: 국채금리 변화(bp)와 환율 흐름이 주는 신호(통화정책·위험선호 등)\n"
        "- 마지막 문단: 길게 본 추세(52주 고점 대비, YTD)와 전망/주목 포인트\n"
        "- 과장·투자권유 금지. 수치는 데이터에 있는 것만 사용. 마크다운 기호 없이 평문으로.\n\n"
        f"[주요 지수]\n{index_block}\n",
    ]
    if commodity_block:
        parts.append(f"\n[주요 원자재]\n{commodity_block}\n")
    if rate_block:
        parts.append(f"\n[국채 금리] (등락 bp)\n{rate_block}\n")
    if fx_block:
        parts.append(f"\n[환율] (등락 %)\n{fx_block}\n")
    return "".join(parts)


def _resolve_argv(cmd_tmpl: str, use_prompt_arg: bool, prompt: str) -> List[str]:
    """명령 템플릿 → 실행 가능한 argv로 변환.

    Windows에서 npm 전역 CLI는 보통 codex.ps1 / codex.cmd 래퍼로 설치되는데,
    이는 실행 파일이 아니라 PATH 조회로는 바로 실행되지 않는다.
    - .ps1  → powershell -ExecutionPolicy Bypass -File <ps1> <args...>
    - .cmd/.bat → cmd /c <bat> <args...>
    - 그 외(이름만 있는 경우) → shutil.which 로 PATH에서 실제 경로/래퍼 탐색
    """
    import shutil

    # Windows 경로의 백슬래시가 shlex 에서 escape 로 먹히지 않도록 posix=False
    on_windows = os.name == "nt"
    parts = shlex.split(cmd_tmpl, posix=not on_windows)
    # posix=False 는 토큰을 따옴표째 남기므로 제거
    parts = [p.strip('"').strip("'") for p in parts]
    if not parts:
        return []

    exe, rest = parts[0], parts[1:]

    # PATH 에서 실제 경로 탐색 (codex → codex.ps1/.cmd 자동 매칭)
    resolved = shutil.which(exe) or exe
    low = resolved.lower()

    if on_windows and low.endswith(".ps1"):
        argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", resolved, *rest]
    elif on_windows and (low.endswith(".cmd") or low.endswith(".bat")):
        argv = ["cmd", "/c", resolved, *rest]
    else:
        argv = [resolved, *rest]

    if use_prompt_arg:
        argv.append(prompt)
    return argv


def _clean_codex_output(raw: str) -> str:
    """codex exec 출력에서 실제 답변 본문만 추출.

    codex v0.160 출력 구조:
        OpenAI Codex v0.160.0
        --------
        workdir: ...
        model: ...
        --------
        user
        <질문 에코백>
        warning: ...            (선택)
        codex
        <실제 답변>             ← 이 부분만 필요
        tokens used
        16,444

    전략:
      1) 마지막 'codex' 단독 라인 ~ 'tokens used' 라인 사이를 본문으로 추출
      2) 실패 시: 마지막 구분선(----) 이후에서 메타/에코백/경고 라인 제거
      3) 그래도 비면 원본 반환(안전)
    """
    text = (raw or "").replace("\r\n", "\n").strip()
    if not text:
        return ""
    lines = text.split("\n")

    def is_sep(ln: str) -> bool:
        s = ln.strip()
        return len(s) >= 4 and set(s) <= {"-"}

    # 1) 'codex' 마커 ~ 'tokens used' 사이
    codex_idx = -1
    for i, ln in enumerate(lines):
        if ln.strip().lower() == "codex":
            codex_idx = i  # 마지막 것을 사용
    if codex_idx >= 0:
        end = len(lines)
        for j in range(codex_idx + 1, len(lines)):
            if lines[j].strip().lower().startswith("tokens used"):
                end = j
                break
        body = "\n".join(lines[codex_idx + 1:end]).strip()
        if body:
            return body

    # 2) 마지막 구분선 이후 + 군더더기 제거
    noise_prefixes = (
        "workdir:", "model:", "provider:", "approval:", "sandbox:",
        "reasoning", "tokens used", "session id", "openai codex",
        "codex session", "user instructions", "warning:", "error:",
    )
    sep_idx = -1
    for i, ln in enumerate(lines):
        if is_sep(ln):
            sep_idx = i
    candidate = lines[sep_idx + 1:] if sep_idx >= 0 else lines
    kept = []
    for ln in candidate:
        low = ln.strip().lower()
        if low in ("", "user", "codex"):
            if low in ("user", "codex"):
                continue
        if low.startswith(noise_prefixes):
            continue
        kept.append(ln)
    cleaned = "\n".join(kept).strip()
    return cleaned or text


def generate_commentary(rows: List[Dict], rcfg: RecapConfig,
                        commodity_rows: Optional[List[Dict]] = None,
                        rate_rows: Optional[List[Dict]] = None,
                        fx_rows: Optional[List[Dict]] = None) -> Dict:
    """외부 CLI로 코멘터리 생성. 반환: {text, source, ok}."""
    if not rcfg.commentary_enabled:
        return {"text": "", "source": "disabled", "ok": False}

    prompt = _build_prompt(rows, commodity_rows, rate_rows, fx_rows)
    cmd_tmpl = rcfg.commentary_cmd
    try:
        # 긴 멀티라인 프롬프트를 인자로 넘기면 Windows(powershell -File)에서
        # 인자가 유실/절단되는 문제가 있다 → stdin 전달을 기본으로 한다.
        #   {prompt} 자리표시자가 있으면 그 자리를 '-' 로 바꿔(= codex: stdin에서 읽기)
        #   없으면 명령 그대로 사용. 어느 경우든 프롬프트는 stdin으로 넣는다.
        if "{prompt}" in cmd_tmpl:
            cmd_for_stdin = cmd_tmpl.replace("{prompt}", "-")
        else:
            cmd_for_stdin = cmd_tmpl
        argv = _resolve_argv(cmd_for_stdin, use_prompt_arg=False, prompt=prompt)
        proc = subprocess.run(
            argv, input=prompt, capture_output=True, text=True,
            timeout=rcfg.commentary_timeout, cwd=rcfg.base_dir,
            encoding="utf-8", errors="replace",
        )
        out = _clean_codex_output(proc.stdout or "")
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
                    "설치된 명령에 맞게 설정하세요. 예: 'codex exec {prompt}'. "
                    "Windows에서 codex.ps1 로 설치된 경우 PATH 에 있으면 자동 인식되며, "
                    "안 되면 전체 경로를 지정하세요: "
                    "'C:\\\\Users\\\\<이름>\\\\AppData\\\\Roaming\\\\npm\\\\codex.ps1 exec {prompt}')",
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
    """지수+원자재+금리+환율 수집 + (선택)코멘터리 생성 → 캐시 저장 → payload 반환."""
    rows = collect_indices(rcfg)
    commodities = collect_commodities(rcfg)
    rates = naver.collect_rates(rcfg.rates)
    fx = naver.collect_fx(rcfg.fx)
    commentary = {"text": "", "source": "", "ok": False}
    if with_commentary:
        commentary = generate_commentary(rows, rcfg, commodity_rows=commodities,
                                         rate_rows=rates, fx_rows=fx)
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": rows,
        "commodities": commodities,
        "rates": rates,
        "fx": fx,
        "commentary": commentary,
    }
    save_recap(rcfg, payload)
    return payload
