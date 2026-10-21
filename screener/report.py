"""필터 가능한 HTML 리포트 생성 (의존성 없는 순수 HTML+JS)."""
from __future__ import annotations

import json
import html
import os
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd

from .config import Config
from .instruments import InstrumentStore
from .weekly import previous_week_friday
from .ui import shared_ui
from .industry import IndustryStore


def _fmt_num(v, currency: str) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    try:
        if currency == "KRW":
            return f"{v:,.0f}"
        return f"{v:,.2f}"
    except Exception:  # noqa: BLE001
        return str(v)


def _fmt_marketcap(v, currency: str) -> str:
    """시가총액 축약 표시. 한국(KRW)=조/억, 그 외=T/B/M."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == 0:
        return "-"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    if currency == "KRW":
        jo = 1_0000_0000_0000  # 조
        eok = 1_0000_0000      # 억
        if v >= jo:
            return f"{v/jo:,.1f}조"
        if v >= eok:
            return f"{v/eok:,.0f}억"
        return f"{v:,.0f}"
    # USD 등
    t, b, m = 1e12, 1e9, 1e6
    if v >= t:
        return f"${v/t:,.2f}T"
    if v >= b:
        return f"${v/b:,.2f}B"
    if v >= m:
        return f"${v/m:,.0f}M"
    return f"${v:,.0f}"


def build_records(df: pd.DataFrame, cfg: Config, sectors: dict | None = None) -> list:
    """DataFrame을 JS용 레코드 리스트로 변환. sectors(={symbol:섹터})가 있으면 반영."""
    df = InstrumentStore(cfg.base_dir).equity_frame(df)
    sectors = sectors or {}
    industry_store = IndustryStore(cfg.base_dir)
    high_periods = cfg.high_periods_weeks
    ma_periods = cfg.ma_periods_weeks
    usd_krw = float(cfg.usd_krw) if cfg.usd_krw else 1400.0
    records = []
    for _, r in df.iterrows():
        sym = str(r["symbol"])
        cap = None if pd.isna(r.get("marketcap")) else float(r.get("marketcap"))
        # 공통 통화(USD) 환산 시총: 원화는 환율로 나눔, 달러는 그대로
        if cap is None:
            cap_usd = None
        elif r["currency"] == "KRW":
            cap_usd = cap / usd_krw
        else:
            cap_usd = cap
        rec = {
            "symbol": sym,
            "name": r["name"],
            "market": r["market"],
            "country": r["country"],
            "currency": r["currency"],
            "sector": sectors.get(sym, "") or (r.get("sector", "") or ""),
            "last_date": r["last_date"],
            "close": None if pd.isna(r["close"]) else float(r["close"]),
            "close_fmt": _fmt_num(r["close"], r["currency"]),
            "aligned": bool(r["aligned"]),
            "high_count": int(r["high_count"]),
            "adv": None if pd.isna(r.get("avg_dollar_volume")) else float(r.get("avg_dollar_volume", 0)),
            "mcap": cap,
            "mcap_usd": cap_usd,  # 환율 환산 USD 기준 (정렬/비교용)
            "mcap_fmt": _fmt_marketcap(r.get("marketcap"), r["currency"]),
        }
        industry = industry_store.classify(r["country"], sym)
        rec["industry"] = {key: industry[key] for key in (
            "node_ids", "paths", "major_ids", "middle_ids", "minor_ids", "major_label", "middle_label", "minor_label",
            "depth", "path_label", "status", "status_label", "manual_override", "in_source")}
        for p in high_periods:
            v = r.get(f"high_{p}w")
            rec[f"h{p}"] = (None if v is None or (isinstance(v, float) and pd.isna(v)) else bool(v))
        records.append(rec)
    return records


def render_html(df: pd.DataFrame, cfg: Config, records: list, server_mode: bool = False,
                result_asof: str = "", generated_at: str = "", result_note: str = "") -> str:
    """레코드로 완성된 HTML 문자열 생성."""
    store = InstrumentStore(cfg.base_dir)
    df = store.equity_frame(df)
    kept = set(store.equity_frame(pd.DataFrame(records)).index)
    records = [r for index, r in enumerate(records) if index in kept]
    today = previous_week_friday().isoformat()
    markets = sorted(df["market"].unique().tolist()) if not df.empty else []
    usd_krw = float(cfg.usd_krw) if cfg.usd_krw else 1400.0

    def krw_label(usd: float) -> str:
        return _fmt_marketcap(usd * usd_krw, "KRW")

    return _TEMPLATE.format(
        today=today,
        shared_ui=shared_ui() + "<script>" + (Path(cfg.base_dir) / "web" / "industry-controls.js").read_text(encoding="utf-8") + "</script>",
        industry_json=json.dumps(IndustryStore(cfg.base_dir).catalogue(), ensure_ascii=False).replace("</", "<\\/"),
        result_status=((f"표시 결과: {result_asof} 기준 · 생성: {generated_at}"
                        if result_asof else "아직 스크리닝 결과가 없습니다")
                       + (" · " + html.escape(result_note) if result_note else "")),
        refresh_control=('<div class="update-group"><button class="update-button" id="screenRefreshBtn" type="button" '
                         'aria-describedby="screenRefreshStatus" onclick="refreshScreen()">스크리너 업데이트</button></div>' if server_mode else ""),
        total=len(records),
        aligned_count=int(df["aligned"].sum()) if not df.empty else 0,
        high_periods=json.dumps(cfg.high_periods_weeks),
        ma_periods=json.dumps(cfg.ma_periods_weeks),
        markets=json.dumps(markets, ensure_ascii=False),
        data_json=json.dumps(records, ensure_ascii=False),
        include_mode=cfg.include_mode,
        server_mode="true" if server_mode else "false",
        usd_krw=f"{usd_krw:,.0f}",
        krw_small=krw_label(3e8),
        krw_mid=krw_label(2e9),
        krw_large=krw_label(1e10),
        krw_mega=krw_label(1e11),
    )


def build_report(df: pd.DataFrame, cfg: Config, sectors: dict | None = None) -> str:
    """정적 HTML 파일로 저장 (서버 없이 보기용)."""
    today = previous_week_friday().isoformat()
    out_file = os.path.join(cfg.output_path, f"report_{today}.html")
    records = build_records(df, cfg, sectors)
    html = render_html(df, cfg, records, server_mode=False, result_asof=today,
                       generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html)
    return out_file


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>신고가 · 정배열 스크리너 — {today}</title>
<style>
  :root {{
    --bg:#0f1419; --panel:#1a2230; --panel2:#222c3c; --text:#e6edf3;
    --muted:#8b98a9; --accent:#4a9eff; --green:#2ecc71; --amber:#f5a623;
    --border:#2b3647; --red:#ff6b6b;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
    font-size:14px; }}
  header {{ padding:18px 24px; background:linear-gradient(135deg,#1a2230,#141b26);
    border-bottom:1px solid var(--border);
    display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
  header h1 {{ margin:0 0 4px; font-size:20px; }}
  header .sub {{ color:var(--muted); font-size:13px; }}
  .navbtn {{ background:#2563eb; color:#fff; text-decoration:none; border-radius:8px;
    padding:9px 16px; font-size:13px; font-weight:600; white-space:nowrap; }}
  .navbtn:hover {{ background:#1d4ed8; }}
  .wrap {{ padding:16px 24px 60px; max-width:100%; min-width:0; }}
  .controls {{ background:var(--panel); border:1px solid var(--border); border-radius:10px;
    padding:14px 16px; margin-bottom:16px; display:flex; flex-wrap:wrap; gap:16px; align-items:flex-end; }}
  .ctl {{ display:flex; flex-direction:column; gap:6px; min-width:0; max-width:100%; }}
  .ctl label {{ font-size:12px; color:var(--muted); }}
  .ctl input[type=text], .ctl select {{ background:var(--panel2); border:1px solid var(--border);
    color:var(--text); padding:7px 10px; border-radius:6px; font-size:13px; min-width:150px; }}
  /* 커스텀 드롭다운 (네이티브 select의 OS 기본 옵션 패널을 대체) */
  .dropdown {{ position:relative; min-width:150px; }}
  .dropdown-btn {{ width:100%; display:flex; align-items:center; justify-content:space-between;
    gap:8px; background:var(--panel2); border:1px solid var(--border); color:var(--text);
    padding:7px 10px; border-radius:6px; font-size:13px; cursor:pointer; text-align:left; }}
  .dropdown-btn:hover {{ border-color:#3a4a5f; }}
  .dropdown.open .dropdown-btn {{ border-color:var(--accent); }}
  .dropdown-arrow {{ color:var(--muted); font-size:11px; transition:transform .15s; }}
  .dropdown.open .dropdown-arrow {{ transform:rotate(180deg); }}
  .dropdown-menu {{ display:none; position:absolute; top:calc(100% + 4px); left:0; right:0; z-index:50;
    background:var(--panel); border:1px solid var(--border); border-radius:8px; padding:4px;
    box-shadow:0 8px 24px rgba(0,0,0,.45); max-height:280px; overflow-y:auto; }}
  .dropdown.open .dropdown-menu {{ display:block; }}
  .dropdown-item {{ padding:8px 10px; border-radius:5px; font-size:13px; color:var(--text);
    cursor:pointer; white-space:nowrap; }}
  .dropdown-item:hover {{ background:var(--panel2); }}
  .dropdown-item.selected {{ background:rgba(74,158,255,.18); color:var(--accent); font-weight:600; }}
  .chips {{ display:flex; flex-wrap:wrap; gap:8px; max-width:100%; }}
  .chip {{ user-select:none; cursor:pointer; padding:6px 11px; border-radius:20px;
    border:1px solid var(--border); background:var(--panel2); color:var(--muted); font-size:12px; }}
  .chip.active {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
  .chip.green.active {{ background:var(--green); border-color:var(--green); }}
  .match-mode {{ display:flex; gap:6px; }}
  .match-mode .chip.active {{ background:var(--amber); border-color:var(--amber); color:#111; }}
  .stats {{ color:var(--muted); font-size:13px; margin:0 0 10px; }}
  .stats b {{ color:var(--text); }}
  .mobile-sort {{ display:none; align-items:center; gap:8px; margin:0 0 10px; color:var(--muted); font-size:12px; }}
  .mobile-sort select, .mobile-sort button {{ background:var(--panel2); border:1px solid var(--border); color:var(--text); border-radius:6px; padding:7px 9px; font:inherit; }}
  .table-scroll {{ width:100%; border:1px solid var(--border); border-radius:10px; overflow:visible; }}
  table {{ width:100%; table-layout:fixed; border-collapse:collapse; background:var(--panel); }}
  thead th {{ position:sticky; top:0; background:var(--panel2); text-align:left; padding:9px 8px;
    font-size:12px; color:var(--muted); border-bottom:1px solid var(--border); cursor:pointer; white-space:nowrap; }}
  thead th:hover {{ color:var(--text); }}
  tbody td {{ padding:9px 8px; border-bottom:1px solid var(--border); overflow-wrap:anywhere; }}
  th:nth-child(1) {{ width:9%; }} th:nth-child(2) {{ width:20%; }}
  th:nth-child(3) {{ width:9%; }} th:nth-child(4) {{ width:10%; }}
  th:nth-child(5) {{ width:12%; }} th:nth-child(6) {{ width:19%; }}
  th:nth-child(7) {{ width:9%; }} th:nth-child(8) {{ width:12%; }}
  .high-tags {{ display:flex; flex-wrap:wrap; gap:4px; justify-content:flex-end; }}
  .high-summary {{ display:block; margin-bottom:4px; color:var(--muted); font-size:11px; }}
  .name-meta {{ display:block; margin-top:3px; font-size:11px; color:var(--muted); }}
  tbody tr:hover {{ background:#1e2735; }}
  .tag {{ display:inline-block; padding:2px 7px; border-radius:4px; font-size:11px; font-weight:600; }}
  .yes {{ background:rgba(46,204,113,.18); color:var(--green); }}
  .no {{ color:#55606f; }}
  .na {{ color:#3a4451; }}
  .aligned-yes {{ background:rgba(74,158,255,.18); color:var(--accent); font-weight:600;
    padding:2px 7px; border-radius:4px; }}
  .mkt {{ font-size:11px; color:var(--muted); }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .sym {{ font-weight:600; }}
  .chart-link {{ color:var(--accent); text-decoration:none; border-radius:4px; }}
  .chart-link:hover, .chart-link:focus-visible {{ text-decoration:underline; }}
  .cc {{ font-size:11px; color:var(--muted); }}
  footer {{ color:#55606f; font-size:12px; padding:16px 24px; }}
  .sector-edit {{ background:#172030; border:1px solid var(--border); color:var(--text);
    padding:4px 7px; border-radius:5px; font-size:12px; width:100%; min-width:0; }}
  .sector-edit:focus {{ outline:none; border-color:var(--accent); background:#1b2740; }}
  /* 커스텀 자동완성 (datalist의 흰색 OS 기본 목록을 대체) */
  .ac-wrap {{ position:relative; width:100%; }}
  .ac-menu {{ display:none; position:absolute; top:calc(100% + 4px); left:0; z-index:60;
    min-width:100%; background:var(--panel); border:1px solid var(--border); border-radius:8px;
    padding:4px; box-shadow:0 8px 24px rgba(0,0,0,.45); max-height:240px; overflow-y:auto; }}
  .ac-menu.open {{ display:block; }}
  .ac-item {{ padding:7px 10px; border-radius:5px; font-size:13px; color:var(--text);
    cursor:pointer; white-space:nowrap; }}
  .ac-item:hover, .ac-item.active {{ background:rgba(74,158,255,.18); color:var(--accent); }}
  .ac-empty {{ padding:7px 10px; font-size:12px; color:var(--muted); }}
  .sort-ind::after {{ content:" \25B4\25BE"; color:#3a4451; font-size:9px; }}
  th.sort-asc::after {{ content:" \25B4"; color:var(--accent); }}
  th.sort-desc::after {{ content:" \25BE"; color:var(--accent); }}
  @media (max-width:1000px) {{
    .mobile-sort {{ display:flex; }}
    .table-scroll {{ border:0; }}
    table, tbody {{ display:block; background:transparent; }}
    thead {{ display:none; }}
    tbody {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,450px),1fr)); gap:12px; }}
    tbody tr {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr));
      border:1px solid var(--border); border-radius:10px; background:var(--panel); overflow:visible; }}
    tbody td {{ min-width:0; display:flex; flex-direction:column; align-items:flex-start; gap:3px;
      padding:9px 11px; border-bottom:1px solid var(--border); text-align:left; }}
    tbody td::before {{ content:attr(data-label); color:var(--muted); font-size:11px; }}
    tbody td:nth-child(2) {{ grid-column:1 / -1; grid-row:1; }}
    tbody td:nth-child(1) {{ grid-column:1; grid-row:2; }}
    tbody td:nth-child(3) {{ grid-column:2; grid-row:2; }}
    tbody td:nth-child(8) {{ grid-column:1 / -1; border-bottom:0; }}
    .high-tags {{ justify-content:flex-start; }}
    .sector-edit {{ width:100%; }}
  }}
  @media (max-width:700px) {{ .wrap {{ padding:12px 10px 40px; }} header {{ padding:14px 10px; }} }}
</style>
{shared_ui}
</head>
<body class="finance-screen">
<header class="finance-header">
  <div class="finance-brand"><span class="brand-mark" aria-hidden="true">▥</span><h1>신고가 · 정배열 스크리너</h1></div>
  <div class="header-actions">
    <nav class="finance-nav" aria-label="화면 이동"><a class="navbtn" href="/weekly" aria-current="page">스크리너</a><a class="navbtn" href="/recap">시장 Recap</a><a class="navbtn" href="/industries">산업 분류</a><a class="navbtn" href="/sector-etfs">ETF 설정</a></nav>
    {refresh_control}
    <button class="theme-toggle" type="button" data-theme-toggle aria-label="테마 변경">☾</button>
  </div>
</header>
<div class="update-notice"><span class="update-scope">주간 스캔 · {today} 기준</span><span>{result_status}</span><span id="screenRefreshStatus" class="update-status" role="status" aria-live="polite"></span></div>
<div class="wrap">
  <div class="controls">
    <div class="ctl">
      <label for="search">검색 (종목명/코드)</label>
      <input id="search" type="text" placeholder="예: 삼성, AAPL..."/>
    </div>
    <div class="ctl">
      <label for="marketBtn">시장</label>
      <div class="dropdown" id="marketDropdown">
        <button type="button" class="dropdown-btn" id="marketBtn">
          <span id="marketBtnLabel">전체</span><span class="dropdown-arrow">▾</span>
        </button>
        <div class="dropdown-menu" id="marketMenu"></div>
      </div>
    </div>
    <div class="ctl"><label for="industryMajor">대분류</label><select id="industryMajor"></select></div>
    <div class="ctl"><label for="industryMiddle">중분류</label><select id="industryMiddle"></select></div>
    <div class="ctl"><label for="industryMinor">소분류</label><select id="industryMinor"></select></div>
    <div class="ctl"><label for="industryStatus">분류 상태</label><select id="industryStatus"><option value="">전체 상태</option><option value="unclassified">미분류</option><option value="partial">대·중분류만 지정</option><option value="draft">자동 분류 초안</option><option value="review">사업 검토 필요</option><option value="approved">사업 검토 완료</option><option value="manual">직접 지정</option><option value="excluded">분류 제외</option></select></div>
    <div class="ctl">
      <label>신고가 조건 (선택한 것만, OR/AND 전환 가능)</label>
      <div class="chips" id="highChips"></div>
    </div>
    <div class="ctl">
      <label>조건 결합</label>
      <div class="chips match-mode" id="matchMode">
        <button type="button" class="chip active" data-mode="or">하나라도(OR)</button>
        <button type="button" class="chip" data-mode="and">모두(AND)</button>
      </div>
    </div>
    <div class="ctl">
      <label>정배열</label>
      <div class="chips">
        <button type="button" class="chip green" id="alignChip">정배열만 보기</button>
      </div>
    </div>
    <div class="ctl">
      <label>최소 시가총액 (환율 {usd_krw}원 환산 · USD 기준)</label>
      <div class="chips" id="mcapChips">
        <button type="button" class="chip active" data-usd="0">전체</button>
        <button type="button" class="chip" data-usd="300000000">3억$↑ (약 {krw_small})</button>
        <button type="button" class="chip" data-usd="2000000000">20억$↑ (약 {krw_mid})</button>
        <button type="button" class="chip" data-usd="10000000000">100억$↑ (약 {krw_large})</button>
        <button type="button" class="chip" data-usd="100000000000">1000억$↑ (약 {krw_mega})</button>
      </div>
    </div>
  </div>

  <div class="industry-screen-note">산업 기준: KUIM · 소분류 미지정과 자동 분류 초안을 구분해 표시합니다. <a href="/industries">분류·근거 검토 →</a></div>
  <p class="stats" id="stats"></p>
  <div class="mobile-sort"><label for="sortSelect">정렬</label><select id="sortSelect"></select><button id="sortDirection" type="button" aria-label="정렬 방향">내림차순 ↓</button></div>

  <div class="table-scroll" role="region" aria-label="스크리너 결과" tabindex="0">
    <table id="tbl">
      <thead><tr id="thead"></tr></thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
</div>
<footer>FinanceDataReader 기반 · 고가 기준 신고가 · 주봉 이동평균 정배열 · 투자 판단의 책임은 본인에게 있습니다.</footer>

<script>
const DATA = {data_json};
const INDUSTRY_TAXONOMY = {industry_json};
const HIGHS = {high_periods};
const MAS = {ma_periods};
const MARKETS = {markets};

const SERVER_MODE = {server_mode};  // true면 섹터 입력/저장 활성화 (localhost 서버)

let screenPolling = false;
function screenUpdate(state, label, message) {{
  FinanceUI.update(document.getElementById('screenRefreshBtn'), state, label, message, document.getElementById('screenRefreshStatus'));
}}
async function pollScreen() {{
  const btn = document.getElementById('screenRefreshBtn');
  if (!btn || screenPolling) return;
  screenPolling = true;
  try {{
    const res = await fetch('/api/screen/status', {{cache:'no-store'}});
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const job = await res.json();
    if (job.state === 'running') {{
      const prog = (job.total && job.total > 0)
        ? ' · ' + (job.done || 0).toLocaleString() + '/' + job.total.toLocaleString() + '종목 ('
          + Math.floor((job.done || 0) / job.total * 100) + '%)'
        : ' · 종목 목록을 준비하는 중…';
      screenUpdate('running', '스크리닝 중…', (job.asof_date || '') + ' 기준' + prog);
      setTimeout(pollScreen, 2000);
    }} else if (job.state === 'done' && btn.dataset.state === 'running') {{
      const evaluated = job.scan?.evaluated_count;
      if (job.count === 0 && !evaluated) {{
        screenUpdate('error', '다시 업데이트', '수집·검사 완료를 확인할 수 없습니다. 서버를 재시작한 뒤 다시 시도해 주세요.');
        return;
      }}
      FinanceUI.remember(job.count === 0 && evaluated
        ? evaluated.toLocaleString() + '종목 검사 완료 · 조건 충족 0종목'
        : '스크리너 업데이트 완료 · ' + job.count + '종목');
      location.reload();
    }} else if (job.state === 'error') {{
      screenUpdate('error', '다시 업데이트', '업데이트 실패 · ' + (job.error || '알 수 없는 오류'));
    }} else if (btn.dataset.state === 'running') {{
      screenUpdate('idle', '스크리너 업데이트', '진행 중인 업데이트가 없습니다. 다시 시작할 수 있습니다.');
    }}
  }} catch (e) {{
    if (btn.dataset.state === 'running') {{
      screenUpdate('running', '스크리닝 중…', '연결을 다시 확인하고 있습니다.');
      setTimeout(pollScreen, 5000);
    }} else {{
      screenUpdate('error', '다시 업데이트', '서버 연결을 확인해 주세요.');
    }}
  }} finally {{ screenPolling = false; }}
}}
async function refreshScreen() {{
  const btn = document.getElementById('screenRefreshBtn');
  if (!btn || btn.disabled) return;
  screenUpdate('running', '업데이트 시작 중…', '주간 스크리닝을 시작합니다.');
  try {{
    const res = await fetch('/api/screen/refresh', {{method:'POST'}});
    const body = await res.json();
    if (!res.ok) throw new Error(body.error || 'HTTP ' + res.status);
    pollScreen();
  }} catch (e) {{ screenUpdate('error', '다시 업데이트', '업데이트 실패 · ' + e.message); }}
}}
if (SERVER_MODE) pollScreen();

const state = {{ search:"", market:"", industry:{{major:"",middle:"",minor:""}}, industryStatus:"", highs:new Set(), matchMode:"or",
  alignedOnly:false, sortKey:"high_count", sortDir:-1,
  minCapUsd:0 }};

// ---- 컨트롤 구성 ----
// 커스텀 시장 드롭다운
const marketDropdown = document.getElementById('marketDropdown');
const marketBtn = document.getElementById('marketBtn');
const marketBtnLabel = document.getElementById('marketBtnLabel');
const marketMenu = document.getElementById('marketMenu');

function buildMarketMenu() {{
  const items = [{{v:"", t:"전체"}}].concat(MARKETS.map(m => ({{v:m, t:m}})));
  marketMenu.innerHTML = items.map(it =>
    `<div class="dropdown-item${{it.v===state.market?' selected':''}}" data-v="${{it.v}}">${{it.t}}</div>`
  ).join('');
}}
buildMarketMenu();

marketBtn.addEventListener('click', e => {{
  e.stopPropagation();
  marketDropdown.classList.toggle('open');
}});
marketMenu.addEventListener('click', e => {{
  const item = e.target.closest('.dropdown-item');
  if(!item) return;
  state.market = item.dataset.v;
  marketBtnLabel.textContent = item.textContent;
  marketDropdown.classList.remove('open');
  buildMarketMenu();
  render();
}});
// 바깥 클릭 시 닫기
document.addEventListener('click', e => {{
  if(!marketDropdown.contains(e.target)) marketDropdown.classList.remove('open');
}});

document.getElementById('search').addEventListener('input', e => {{ state.search=e.target.value.toLowerCase(); render(); }});

const industryFilters = FinanceIndustry.createFilters([
  document.getElementById('industryMajor'),document.getElementById('industryMiddle'),document.getElementById('industryMinor')
],INDUSTRY_TAXONOMY,value=>{{state.industry=value;render();}});
document.getElementById('industryStatus').addEventListener('change',event=>{{state.industryStatus=event.target.value;render();}});

const highChips = document.getElementById('highChips');
HIGHS.forEach(p => {{
  const c=document.createElement('button'); c.type='button'; c.className='chip'; c.textContent=p+'주'; c.dataset.p=p;
  c.addEventListener('click', ()=>{{ if(state.highs.has(p)) state.highs.delete(p); else state.highs.add(p);
    c.classList.toggle('active'); render(); }});
  highChips.appendChild(c);
}});

document.querySelectorAll('#matchMode .chip').forEach(ch => {{
  ch.addEventListener('click', ()=>{{
    document.querySelectorAll('#matchMode .chip').forEach(x=>x.classList.remove('active'));
    ch.classList.add('active'); state.matchMode=ch.dataset.mode; render();
  }});
}});

const alignChip=document.getElementById('alignChip');
alignChip.addEventListener('click', ()=>{{ state.alignedOnly=!state.alignedOnly; alignChip.classList.toggle('active'); render(); }});

// 최소 시가총액 칩 (단일 선택). 달러 환산(USD) 기준 공통 임계값
document.querySelectorAll('#mcapChips .chip').forEach(ch => {{
  ch.addEventListener('click', ()=>{{
    document.querySelectorAll('#mcapChips .chip').forEach(x=>x.classList.remove('active'));
    ch.classList.add('active');
    state.minCapUsd = parseFloat(ch.dataset.usd) || 0;
    render();
  }});
}});

// ---- 테이블 헤더 ----
const COLS = [
  {{k:'symbol', t:'코드'}}, {{k:'name', t:'종목명'}}, {{k:'market', t:'시장'}},
  {{k:'close', t:'종가', num:true}}, {{k:'mcap', t:'시가총액', num:true}},
  {{k:'high_count', t:'신고가', num:true}}, {{k:'aligned', t:'정배열'}},
  {{k:'major', t:'대분류'}}, {{k:'middle', t:'중분류'}}, {{k:'minor', t:'소분류'}}
];

const sortSelect=document.getElementById('sortSelect');
const sortDirection=document.getElementById('sortDirection');
COLS.forEach(col => {{
  const option=document.createElement('option'); option.value=col.k; option.textContent=col.t;
  sortSelect.appendChild(option);
}});
sortSelect.value=state.sortKey;
sortSelect.addEventListener('change', () => {{
  state.sortKey=sortSelect.value;
  state.sortDir=['close','mcap','high_count'].includes(state.sortKey) ? -1 : 1;
  render();
}});
sortDirection.addEventListener('click', () => {{ state.sortDir*=-1; render(); }});

const thead=document.getElementById('thead');
COLS.forEach(col => {{
  const th=document.createElement('th'); th.textContent=col.t; th.className='sort-ind'; th.dataset.k=col.k;
  if(col.num) th.classList.add('num');
  th.addEventListener('click', ()=>{{
    if(state.sortKey===col.k) state.sortDir*=-1; else {{ state.sortKey=col.k; state.sortDir=(col.num?-1:1); }}
    render();
  }});
  thead.appendChild(th);
}});

// ---- 필터 로직 ----
function passFilter(r) {{
  if(state.market && r.market!==state.market) return false;
  if(state.alignedOnly && !r.aligned) return false;
  if(state.search) {{
    const s=(r.name+' '+r.symbol).toLowerCase();
    if(!s.includes(state.search)) return false;
  }}
  if(!FinanceIndustry.matches(r.industry,state.industry,state.industryStatus)) return false;
  if(state.highs.size>0) {{
    const sel=[...state.highs];
    if(state.matchMode==='or') {{
      if(!sel.some(p => r['h'+p]===true)) return false;
    }} else {{
      if(!sel.every(p => r['h'+p]===true)) return false;
    }}
  }}
  // 최소 시가총액 필터 (달러 환산 USD 기준). 시총 없는 종목은 임계값>0일 때 제외
  if(state.minCapUsd>0) {{
    if(r.mcap_usd==null || r.mcap_usd < state.minCapUsd) return false;
  }}
  return true;
}}

function escapeHTML(value) {{return String(value).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));}}
function cell(r, k) {{
  const chartUrl = SERVER_MODE ? '/chart?symbol=' + encodeURIComponent(r.symbol) : '';
  if(k==='symbol') return SERVER_MODE
    ? `<a class="sym chart-link" href="${{chartUrl}}" target="_blank" rel="noopener">${{r.symbol}}</a>`
    : `<span class="sym">${{r.symbol}}</span>`;
  if(k==='name') {{
    const title = SERVER_MODE
      ? `<a class="chart-link" href="${{chartUrl}}" target="_blank" rel="noopener">${{r.name}}</a>`
      : r.name;
    return `${{title}}<span class="name-meta">${{r.country}} · ${{r.last_date}}</span>`;
  }}
  if(k==='market') return `<span class="mkt">${{r.market}}</span>`;
  if(k==='close') return `<span class="num">${{r.close_fmt}}</span>`;
  if(k==='mcap') return `<span class="num">${{r.mcap_fmt}}</span>`;
  if(k==='aligned') return r.aligned ? '<span class="aligned-yes">정배열</span>' : '<span class="no">-</span>';
  if(['major','middle','minor'].includes(k)) {{
    const value=r.industry[k+'_label'];
    const status=k==='major'?'<span class="industry-state '+r.industry.status+'">'+escapeHTML(r.industry.in_source?r.industry.status_label:'KUIM 원본 없음')+'</span>':'';
    const edit=k==='minor'&&SERVER_MODE&&r.industry.status!=='excluded'?'<button class="industry-edit-button" type="button" data-industry-symbol="'+escapeHTML(r.symbol)+'" data-industry-country="'+escapeHTML(r.country)+'" aria-label="'+escapeHTML(r.name)+' 산업 분류 수정">분류 수정</button>':'';
    return '<span class="industry-cell-value">'+escapeHTML(value||(k==='major'?'미분류':'미지정'))+'</span>'+status+edit;
  }}
  if(k==='high_count') {{
    const badges = HIGHS.filter(p => r['h'+p]===true)
      .map(p => `<span class="tag yes">${{p}}주</span>`).join('');
    return `<span class="high-summary">${{r.high_count}}/${{HIGHS.length}} 충족</span><span class="high-tags">${{badges || '<span class="no">-</span>'}}</span>`;
  }}
  return '';
}}

function render() {{
  let rows = DATA.filter(passFilter);
  const k=state.sortKey, dir=state.sortDir;
  rows.sort((a,b)=>{{
    let av=a[k], bv=b[k];
    if(/^h\d+$/.test(k)||k==='aligned') {{ av=av?1:0; bv=bv?1:0; }}
    if(k==='close') {{ av=a.close||0; bv=b.close||0; }}
    // 시가총액은 환율 환산(USD) 값으로 비교
    if(k==='mcap') {{ av=(a.mcap_usd==null?-1:a.mcap_usd); bv=(b.mcap_usd==null?-1:b.mcap_usd); }}
    if(['major','middle','minor'].includes(k)) {{ av=a.industry[k+'_label']; bv=b.industry[k+'_label']; }}
    if(typeof av==='string') return av.localeCompare(bv)*dir;
    return (av-bv)*dir;
  }});

  const tbody=document.getElementById('tbody'); tbody.innerHTML='';
  const frag=document.createDocumentFragment();
  rows.forEach(r => {{
    const tr=document.createElement('tr');
    tr.innerHTML = COLS.map(c=>`<td data-label="${{c.t}}"${{c.num?' class="num"':''}}>${{cell(r,c.k)}}</td>`).join('');
    frag.appendChild(tr);
  }});
  tbody.appendChild(frag);

  document.getElementById('stats').innerHTML =
    `표시 <b>${{rows.length}}</b> / 전체 ${{DATA.length}}종목 · 정배열 <b>${{rows.filter(r=>r.aligned).length}}</b>`;

  sortSelect.value=k;
  sortDirection.textContent=dir>0?'오름차순 ↑':'내림차순 ↓';
  document.querySelectorAll('#thead th').forEach(th=>{{
    th.classList.remove('sort-asc','sort-desc','sort-ind');
    if(th.dataset.k===k) th.classList.add(dir>0?'sort-asc':'sort-desc'); else th.classList.add('sort-ind');
  }});
}}

document.getElementById('tbody').addEventListener('click',async event=>{{
  const button=event.target.closest('[data-industry-symbol]');if(!button||button.disabled)return;
  button.disabled=true;
  try {{
    const res=await fetch('/api/industry?'+new URLSearchParams({{symbol:button.dataset.industrySymbol,country:button.dataset.industryCountry}}));
    const data=await res.json();if(!res.ok)throw Error(data.error||'산업 분류를 불러오지 못했습니다.');
    await FinanceIndustry.openEditor({{item:data.industry,taxonomy:INDUSTRY_TAXONOMY,onSave:item=>{{
      const row=DATA.find(r=>r.symbol===item.symbol&&r.country===item.country);if(row)row.industry=item;render();
    }}}});
  }} catch(error){{document.getElementById('stats').textContent=error.message;}}
  finally{{button.disabled=false;}}
}});

render();
</script>
</body>
</html>
"""
