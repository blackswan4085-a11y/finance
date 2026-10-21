"""주간 시장 Recap: 주요 지수 수집 + 지표 계산 + Codex 코멘터리 생성.

- 데이터: FinanceDataReader (Yahoo 소스, '^' 접두사 티커로 통일 → 최신값 안정적)
- 지표: 현재가, 1W/1M/3M/YTD 등락률, 52주 고점 대비, 미니 스파크라인(SVG)
- 코멘터리: 외부 CLI(codex)를 subprocess로 호출 (LLM API 비용 0)
- 결과는 recap_cache.json 에 저장 → 서버 재시작/재접속 시 즉시 표시

API 키 불필요. 서버에서 '업데이트' 클릭 시 refresh_recap() 호출.
"""
from __future__ import annotations

import json
import math
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
import FinanceDataReader as fdr

from . import naver
from .weekly import previous_week_friday


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
# 주요 원자재 (1-2) — Yahoo 공급자 선물 심볼 '=F'.
# ----------------------------------------------------------------------------
DEFAULT_COMMODITIES: List[Dict] = [
    {"group":"귀금속","name":"금","symbol":"GC=F"},
    {"group":"귀금속","name":"은","symbol":"SI=F"},
    {"group":"귀금속","name":"플래티넘","symbol":"PL=F"},
    {"group":"귀금속","name":"팔라듐","symbol":"PA=F"},
    {"group":"산업금속","name":"구리","symbol":"HG=F"},
    {"group":"에너지","name":"WTI 원유","symbol":"CL=F"},
    {"group":"에너지","name":"브렌트유","symbol":"BZ=F"},
    {"group":"에너지","name":"천연가스","symbol":"NG=F"},
    {"group":"에너지","name":"휘발유","symbol":"RB=F"},
    {"group":"에너지","name":"난방유","symbol":"HO=F"},
    {"group":"농산물","name":"옥수수","symbol":"ZC=F"},
    {"group":"농산물","name":"밀","symbol":"ZW=F"},
    {"group":"농산물","name":"대두","symbol":"ZS=F"},
    {"group":"농산물","name":"대두유","symbol":"ZL=F"},
    {"group":"농산물","name":"커피","symbol":"KC=F"},
    {"group":"농산물","name":"코코아","symbol":"CC=F"},
    {"group":"농산물","name":"설탕","symbol":"SB=F"},
    {"group":"농산물","name":"면화","symbol":"CT=F"},
]


# ----------------------------------------------------------------------------
# 1-3. 국채 금리 / 환율 — 네이버 금융 API (일별, 키 불필요).
# 각 국가의 2년/10년 RIC 사용. 공급자 조회 실패는 해당 행에 표시.
# ----------------------------------------------------------------------------
DEFAULT_RATES: List[Dict] = [
    {"group":"미국","name":"미국 2년","code":"US2YT=RR"},
    {"group":"미국","name":"미국 10년","code":"US10YT=RR"},
    {"group":"한국","name":"한국 2년","code":"KR2YT=RR"},
    {"group":"한국","name":"한국 10년","code":"KR10YT=RR"},
    {"group":"독일","name":"독일 2년","code":"DE2YT=RR"},
    {"group":"독일","name":"독일 10년","code":"DE10YT=RR"},
    {"group":"영국","name":"영국 2년","code":"GB2YT=RR"},
    {"group":"영국","name":"영국 10년","code":"GB10YT=RR"},
    {"group":"프랑스","name":"프랑스 2년","code":"FR2YT=RR"},
    {"group":"프랑스","name":"프랑스 10년","code":"FR10YT=RR"},
    {"group":"일본","name":"일본 2년","code":"JP2YT=RR"},
    {"group":"일본","name":"일본 10년","code":"JP10YT=RR"},
    {"group":"중국","name":"중국 2년","code":"CN2YT=RR"},
    {"group":"중국","name":"중국 10년","code":"CN10YT=RR"},
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
    # 코멘터리 생성 CLI. Astra/high 사용, 프롬프트는 항상 stdin으로 전달.
    #   codex는 git repo 밖에서도 돌도록 --skip-git-repo-check 필요.
    commentary_cmd: str = ("codex exec --model gpt-6-astra "
                           "-c model_reasoning_effort=high --skip-git-repo-check "
                           "--sandbox read-only --color never {prompt}")
    commentary_timeout: int = 300
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


def collect_items(items: List[Dict], lookback_days: int, asof_date=None) -> List[Dict]:
    """지수/원자재 등 임의의 심볼 목록을 수집해 표 행 리스트로 반환."""
    asof_date = asof_date or previous_week_friday()
    start = (asof_date - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    rows: List[Dict] = []
    for meta in items:
        df = _fetch_index(meta["symbol"], start)
        if df is not None and not df.empty:
            df = df[df.index.date <= asof_date]
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


def collect_indices(rcfg: RecapConfig, asof_date=None) -> List[Dict]:
    return collect_items(rcfg.indices, rcfg.lookback_days, asof_date)


def collect_commodities(rcfg: RecapConfig, asof_date=None) -> List[Dict]:
    return collect_items(rcfg.commodities, rcfg.lookback_days, asof_date)


# ----------------------------------------------------------------------------
# 코멘터리 생성 (외부 CLI 호출)
# ----------------------------------------------------------------------------

RECAP_PROMPT_VERSION = "2026-10-13-interpretation-v2"


def _valid_row(row: Dict) -> bool:
    price = row.get("price")
    return (not row.get("error") and not row.get("pending")
            and isinstance(price, (int, float)) and math.isfinite(price))


def _rows_to_lines(rows: List[Dict]) -> str:
    def fmt(value, suffix="%", digits=2):
        return (f"{value:+.{digits}f}{suffix}" if isinstance(value, (int, float))
                and math.isfinite(value) else "N/A")

    lines = []
    for row in rows:
        name = f"[{row.get('group', '')}] {row.get('name', '')}"
        if not _valid_row(row):
            lines.append(f"- {name}: 데이터 없음 (해석 대상에서 제외)")
            continue
        unit = row.get("unit", "")
        yield_row = unit == "bp"
        level_unit = "%" if yield_row else ""
        lines.append(
            f"- {name}: 기준일 {row.get('date', '미기록')}, "
            f"종가 {row['price']:,.3f}{level_unit} "
            f"(1W {fmt(row.get('chg_1w'), 'bp' if yield_row else '%')}, "
            f"1M {fmt(row.get('chg_1m'), 'bp' if yield_row else '%')}, "
            f"3M {fmt(row.get('chg_3m'), 'bp' if yield_row else '%')}"
            + ("" if unit else
               f", YTD {fmt(row.get('chg_ytd'))}, "
               f"52주 종가고점대비 {fmt(row.get('from_52w_high'))}")
            + ")"
        )
    return "\n".join(lines) or "- 제공된 데이터 없음"


def _rate_fx_lines(rows: List[Dict]) -> str:
    return _rows_to_lines(rows)


def _curve_lines(rate_rows: List[Dict]) -> str:
    """동일 기준일의 2년/10년 금리가 모두 있는 국가만 계산."""
    by_symbol = {row.get("symbol"): row for row in rate_rows if _valid_row(row)}
    lines = []
    for country in ("US", "KR", "DE", "GB", "FR", "JP", "CN"):
        short = by_symbol.get(f"{country}2YT=RR")
        long = by_symbol.get(f"{country}10YT=RR")
        if not short or not long:
            continue
        if not short.get("date") or short["date"] == "-" or short["date"] != long.get("date"):
            continue
        spread = (long["price"] - short["price"]) * 100
        change = ""
        short_delta, long_delta = short.get("chg_1w"), long.get("chg_1w")
        if all(isinstance(v, (int, float)) and math.isfinite(v)
               for v in (short_delta, long_delta)):
            change = f", 1W 스프레드 변화 {long_delta - short_delta:+.2f}bp"
        lines.append(f"- {short.get('group', country)}: 10년-2년 {spread:+.2f}bp"
                     f"{change} (기준일 {short['date']})")
    return "\n".join(lines) or "- 같은 기준일의 2년/10년 쌍 없음: 수익률곡선 해석 제한"


_COMMON_RULES = (
    "독자가 표를 다시 읽지 않고도 이번 주 움직임의 의미를 이해할 수 있게 작성하라.\n"
    "- 한국어 평문 3개 문단, 문단당 2~3문장, 전체 약 600~900자. 제목·목록·표·인사 없이 본문만 출력.\n"
    "- 1문단: 이 분야에서 가장 설명력이 높은 핵심 해석 하나를 첫 문장에 제시하고, "
    "선택한 수치와 상대성과로 뒷받침한다.\n"
    "- 2문단: 1W와 1M·3M의 관계를 통해 추세 지속/단기 반등/조정 중 무엇에 가까운지 설명하고, "
    "주된 해석과 엇갈리는 신호나 가능한 대안 해석을 짚는다. 근거가 부족하면 판단을 유보한다.\n"
    "- 3문단: 다음 주 어떤 상대성과·방향·동반 움직임이 지속되면 해석이 강화되고, "
    "무엇이 바뀌면 약해지는지 구체적인 확인 조건 1~2개를 제시한다.\n"
    "- 모든 항목을 순서대로 나열하지 않는다. 해석에 필요한 핵심 수치 3~6개만 선택한다. "
    "'변동성이 확대됐다', '자금이 유입됐다'처럼 제공된 종가 수익률만으로 알 수 없는 사실은 쓰지 않는다.\n"
    "- 관측된 사실과 원인 가설을 구분한다. 설명 메커니즘은 가능성으로 표현하고, "
    "데이터에 없는 뉴스·경제지표 발표·정책 결정·기업 사건을 원인으로 만들지 않는다.\n"
    "- 아래 데이터와 계산된 값만 사용한다. 외부 검색·파일 조회·도구 호출 없이 최종 코멘터리를 바로 작성한다. "
    "다른 자산군의 수치나 움직임은 입력에 있을 때만 언급한다.\n"
    "- 데이터 없음/N/A는 0이나 보합이 아니다. 기준일이 다른 항목의 차이는 동시 관측으로 단정하지 않는다. "
    "결론에 영향을 주는 결측·기준일 차이만 간결하게 밝힌다.\n"
    "- 1W/1M/3M은 각 행 최신 종가에서 약 7/30/91일 전 대비다. "
    "YTD는 연초 첫 거래일 종가 대비이며 52주 고점은 종가 기준이다. "
    "서로 다른 기간의 수익률을 합산하거나, 연초 이전 추세를 YTD로 추정하지 않는다.\n"
    "- 쉬운 말로 쓴다. 전문용어는 필요한 경우 뜻을 함께 설명한다. "
    "매매 권유·단정적인 전망·근거 없는 확률·뻔한 마무리 문구는 쓰지 않는다.\n"
)


def _prompt_header(subject: str, asof_date=None) -> str:
    date_text = asof_date.isoformat() if hasattr(asof_date, "isoformat") else str(asof_date or "각 행 기준일 참고")
    return (f"너는 주간 시장 리서치의 {subject} 담당 애널리스트다.\n"
            f"리포트 기준일: {date_text}. 아래 수집된 데이터가 이번 보고서의 사실 근거다.\n\n"
            f"[작성 기준]\n{_COMMON_RULES}\n")


def build_index_prompt(index_rows: List[Dict], *, asof_date=None) -> str:
    return (
        _prompt_header("주식 지수", asof_date)
        + "[분석 범위: 주식 지수 데이터만]\n"
        "미국 대형주·나스닥·러셀2000·반도체 및 국가별 지수의 상대성과를 이용해 "
        "어떤 지수·지역이 상승/하락을 주도하는지와 강세가 여러 지수에 확산되는지 해석하라. "
        "지수 수익률의 차이를 개별 종목의 시장 폭, 거래량, 업종 전체 실적의 증거로 간주하지 않는다. "
        "한국과 해외 시장의 동조/차별화, 단기 흐름과 52주 종가고점까지의 거리가 갖는 의미 중 "
        "이번 주에 중요한 쟁점만 선택하라. 금리·환율·원자재나 미제공 뉴스로 설명하지 않는다.\n\n"
        f"[주요 지수]\n{_rows_to_lines(index_rows)}\n"
    )


def build_commodity_prompt(commodity_rows: List[Dict], *, asof_date=None) -> str:
    return (
        _prompt_header("원자재", asof_date)
        + "[분석 범위: 원자재 데이터만]\n"
        "귀금속·산업금속·에너지·농산물의 상대성과와 동반/반대 방향을 이용해 "
        "움직임이 광범위한지 특정 품목에 집중되는지 해석하라. "
        "금·구리, 원유·정제제품 등의 대비가 경기 민감도나 원가 압력에 주는 신호는 "
        "가능성으로 설명하되 가격만으로 수요·공급 원인을 확정하지 않는다. "
        "농산물 급등을 곧바로 전체 소비자물가 상승으로 일반화하지 않는다. "
        "품목마다 가격 단위가 다르므로 가격 수준을 직접 비교하지 않고 수익률을 비교한다. "
        "선물 롤오버나 계절·공급 요인은 가능한 대안이며, 이번 주 발생 사실로 단정하지 않는다. "
        "주식·금리·환율의 움직임이나 미제공 뉴스로 설명하지 않는다.\n\n"
        f"[주요 원자재]\n{_rows_to_lines(commodity_rows)}\n"
    )


def build_rate_fx_prompt(rate_rows: List[Dict], fx_rows: List[Dict], *, asof_date=None) -> str:
    return (
        _prompt_header("금리·환율", asof_date)
        + "[분석 범위: 국채 금리와 환율 데이터만]\n"
        "2년과 10년 금리의 방향·크기, 장단기 스프레드 변화, 국가별 동조/차별화를 연결하라. "
        "스프레드 확대/축소와 금리 상승/하락을 함께 설명해 수익률곡선 변화의 성격을 밝힌다. "
        "단기물은 정책 기대, 장기물은 성장·물가·기간 프리미엄과 관련될 수 있지만 "
        "명목금리만으로 정책 결정이나 구성 요인의 기여를 확정하지 않는다. "
        "달러인덱스와 원/달러의 동조/괴리 및 다른 원화 교차환율로 달러 전반의 움직임과 "
        "원화의 상대 움직임을 구분하라. 원/외화 상승은 해당 외화 대비 원화 약세다. "
        "금리 수준은 %, 금리 변화와 스프레드는 bp이며 1%p=100bp다. "
        "주식·원자재의 움직임이나 미제공 뉴스로 설명하지 않는다.\n\n"
        f"[국채 금리]\n{_rate_fx_lines(rate_rows)}\n\n"
        f"[계산된 장단기 스프레드]\n{_curve_lines(rate_rows)}\n\n"
        f"[환율]\n{_rate_fx_lines(fx_rows)}\n"
    )


def build_overview_prompt(index_rows: List[Dict], commodity_rows: List[Dict],
                          rate_rows: List[Dict], fx_rows: List[Dict], *, asof_date=None) -> str:
    return (
        _prompt_header("종합 시장 해석", asof_date)
        + "[분석 범위: 아래 네 자산군의 전체 데이터]\n"
        "각 분야를 차례로 요약하는 대신 자산군 사이의 관계를 하나의 시장 해석으로 연결하라. "
        "주식의 리더십, 경기 민감 원자재와 귀금속, 단기·장기 금리, 달러·원화 중 "
        "실제로 유효 데이터가 있는 신호를 골라 서로 일치하거나 충돌하는 지점을 설명하라. "
        "금리 하락과 주가 상승이 함께 나타나도 할인율 부담 완화와 성장 우려가 모두 가능하므로 "
        "구리·원유·소형주 등 다른 관측이 어느 설명을 더 지지하는지 판단하라. "
        "이 예시의 움직임이 이번 데이터에 없다면 억지로 적용하지 않는다. "
        "위험선호/회피·성장 기대·물가 부담·달러의 영향 같은 해석 중 가장 근거 있는 것을 "
        "선택하되 모든 자산을 하나의 서사에 끼워 맞추지 않는다. "
        "마지막 문단에는 두 자산군 이상을 함께 보는 확인/반증 조건을 제시하라. "
        "분야별 코멘터리를 입력으로 사용하지 않고 아래 원자료에서 독립적으로 종합하라.\n\n"
        f"[주요 지수]\n{_rows_to_lines(index_rows)}\n\n"
        f"[주요 원자재]\n{_rows_to_lines(commodity_rows)}\n\n"
        f"[국채 금리]\n{_rate_fx_lines(rate_rows)}\n\n"
        f"[계산된 장단기 스프레드]\n{_curve_lines(rate_rows)}\n\n"
        f"[환율]\n{_rate_fx_lines(fx_rows)}\n"
    )


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


def run_commentary(prompt: str, rcfg: RecapConfig) -> Dict:
    """주어진 프롬프트를 외부 CLI(codex)로 실행. 반환: {text, source, ok}."""
    if not rcfg.commentary_enabled:
        return {"text": "", "source": "disabled", "ok": False}

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
def align_recap_catalog(payload: Optional[Dict], rcfg: RecapConfig) -> Optional[Dict]:
    """Align cached rows by their exact symbol; a new tenor never inherits old prices."""
    if not isinstance(payload, dict):
        return None
    result = dict(payload)
    changed = []
    sections = [("rows", rcfg.indices, "symbol", "commentary_index", "지수"),
                ("commodities", rcfg.commodities, "symbol", "commentary_commodity", "원자재"),
                ("rates", rcfg.rates, "code", "commentary_ratefx", "국채"),
                ("fx", rcfg.fx, "code", "commentary_ratefx", "환율")]
    for key, definitions, code_key, commentary_key, label in sections:
        cached = [row for row in payload.get(key, []) if isinstance(row, dict)]
        by_symbol = {str(row.get("symbol", "")).upper(): row for row in cached}
        aligned = []
        for meta in definitions:
            symbol = meta[code_key]
            row = by_symbol.get(symbol.upper())
            if row is None:
                row = {"symbol": symbol, "date": "-", "price": None,
                       "chg_1w": None, "chg_1m": None, "chg_3m": None, "chg_ytd": None,
                       "from_52w_high": None, "spark": "", "pending": True, "error": True,
                       "unit": "bp" if key == "rates" else "%" if key == "fx" else ""}
            aligned.append({**row, "group": meta["group"], "name": meta["name"]})
        before = [(row.get("symbol"), row.get("name"), row.get("group")) for row in cached]
        after = [(row.get("symbol"), row.get("name"), row.get("group")) for row in aligned]
        result[key] = aligned
        if before != after:
            changed.append(label)
            result[commentary_key] = {"ok": False, "source": "catalog-change",
                "text": "표시 목록이 변경되었습니다. [업데이트]를 눌러 새 목록의 시세와 코멘터리를 생성하세요."}
    if changed:
        result["commentary_overview"] = {"ok": False, "source": "catalog-change",
            "text": "표시 목록이 변경되었습니다. [업데이트]를 눌러 종합 코멘터리를 생성하세요."}
    pending = sum(bool(row.get("pending")) for key, *_ in sections for row in result[key])
    result["catalog_warning"] = (f"새 항목 {pending}개는 업데이트 후 표시됩니다." if pending else
                                  "표시 목록이 변경되었습니다. 업데이트로 코멘터리를 갱신해 주세요." if changed else
                                  payload.get("catalog_warning", ""))
    return result


def load_recap(rcfg: RecapConfig) -> Optional[Dict]:
    path = rcfg.cache_file
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return align_recap_catalog(json.load(f), rcfg)
    except Exception:  # noqa: BLE001
        return None


def save_recap(rcfg: RecapConfig, payload: Dict) -> None:
    try:
        with open(rcfg.cache_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


def refresh_recap(rcfg: RecapConfig, with_commentary: bool = True, asof_date=None) -> Dict:
    """지수+원자재+금리+환율 수집 + (선택)분야별 코멘터리 생성 → 캐시 저장."""
    asof_date = asof_date or previous_week_friday()
    rows = collect_indices(rcfg, asof_date)
    commodities = collect_commodities(rcfg, asof_date)
    rates = naver.collect_rates(rcfg.rates, asof_date)
    fx = naver.collect_fx(rcfg.fx, asof_date)

    none_c = {"text": "", "source": "", "ok": False}
    comm_index = comm_cmdty = comm_ratefx = comm_overview = dict(none_c)
    if with_commentary:
        # 분야별 입력은 해당 분야로 한정. 종합만 네 자산군을 모두 사용한다.
        comm_index = run_commentary(build_index_prompt(rows, asof_date=asof_date), rcfg)
        comm_cmdty = run_commentary(build_commodity_prompt(commodities, asof_date=asof_date), rcfg)
        comm_ratefx = run_commentary(build_rate_fx_prompt(rates, fx, asof_date=asof_date), rcfg)
        comm_overview = run_commentary(
            build_overview_prompt(rows, commodities, rates, fx, asof_date=asof_date), rcfg)

    payload = {
        "asof_date": asof_date.isoformat(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": rows,
        "commodities": commodities,
        "rates": rates,
        "fx": fx,
        "commentary_index": comm_index,
        "commentary_commodity": comm_cmdty,
        "commentary_ratefx": comm_ratefx,
        "commentary_overview": comm_overview,
        "commentary_prompt_version": RECAP_PROMPT_VERSION,
    }
    save_recap(rcfg, payload)
    return payload
