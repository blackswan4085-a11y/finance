"""필터 가능한 HTML 리포트 생성 (의존성 없는 순수 HTML+JS)."""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import List

import pandas as pd

from .config import Config


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
    sectors = sectors or {}
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
        for p in high_periods:
            v = r.get(f"high_{p}w")
            rec[f"h{p}"] = (None if v is None or (isinstance(v, float) and pd.isna(v)) else bool(v))
        records.append(rec)
    return records


def render_html(df: pd.DataFrame, cfg: Config, records: list, server_mode: bool = False) -> str:
    """레코드로 완성된 HTML 문자열 생성."""
    today = datetime.now().strftime("%Y-%m-%d")
    markets = sorted(df["market"].unique().tolist()) if not df.empty else []
    usd_krw = float(cfg.usd_krw) if cfg.usd_krw else 1400.0

    def krw_label(usd: float) -> str:
        return _fmt_marketcap(usd * usd_krw, "KRW")

    return _TEMPLATE.format(
        today=today,
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
    today = datetime.now().strftime("%Y-%m-%d")
    out_file = os.path.join(cfg.output_path, f"report_{today}.html")
    records = build_records(df, cfg, sectors)
    html = render_html(df, cfg, records, server_mode=False)
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
    display:flex; align-items:center; justify-content:space-between; gap:16px; }}
  header h1 {{ margin:0 0 4px; font-size:20px; }}
  header .sub {{ color:var(--muted); font-size:13px; }}
  .navbtn {{ background:#2563eb; color:#fff; text-decoration:none; border-radius:8px;
    padding:9px 16px; font-size:13px; font-weight:600; white-space:nowrap; }}
  .navbtn:hover {{ background:#1d4ed8; }}
  .wrap {{ padding:16px 24px 60px; }}
  .controls {{ background:var(--panel); border:1px solid var(--border); border-radius:10px;
    padding:14px 16px; margin-bottom:16px; display:flex; flex-wrap:wrap; gap:16px; align-items:flex-end; }}
  .ctl {{ display:flex; flex-direction:column; gap:6px; }}
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
  .chips {{ display:flex; flex-wrap:wrap; gap:8px; }}
  .chip {{ user-select:none; cursor:pointer; padding:6px 11px; border-radius:20px;
    border:1px solid var(--border); background:var(--panel2); color:var(--muted); font-size:12px; }}
  .chip.active {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
  .chip.green.active {{ background:var(--green); border-color:var(--green); }}
  .match-mode {{ display:flex; gap:6px; }}
  .match-mode .chip.active {{ background:var(--amber); border-color:var(--amber); color:#111; }}
  .stats {{ color:var(--muted); font-size:13px; margin:0 0 10px; }}
  .stats b {{ color:var(--text); }}
  table {{ width:100%; border-collapse:collapse; background:var(--panel); border-radius:10px; overflow:hidden; }}
  thead th {{ position:sticky; top:0; background:var(--panel2); text-align:left; padding:10px 12px;
    font-size:12px; color:var(--muted); border-bottom:1px solid var(--border); cursor:pointer; white-space:nowrap; }}
  thead th:hover {{ color:var(--text); }}
  tbody td {{ padding:9px 12px; border-bottom:1px solid var(--border); white-space:nowrap; }}
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
  .cc {{ font-size:11px; color:var(--muted); }}
  footer {{ color:#55606f; font-size:12px; padding:16px 24px; }}
  .sector-edit {{ background:#172030; border:1px solid var(--border); color:var(--text);
    padding:4px 7px; border-radius:5px; font-size:12px; width:130px; }}
  .sector-edit:focus {{ outline:none; border-color:var(--accent); background:#1b2740; }}
  /* 커스텀 자동완성 (datalist의 흰색 OS 기본 목록을 대체) */
  .ac-wrap {{ position:relative; }}
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
</style>
</head>
<body>
<header>
  <div>
    <h1>📈 신고가 · 정배열 스크리너</h1>
    <div class="sub">기준일 {today} · 포함모드 <code>{include_mode}</code> · 전체 {total}종목 (정배열 {aligned_count})</div>
  </div>
  <a class="navbtn" href="/recap">📊 시장 Recap →</a>
</header>
<div class="wrap">
  <div class="controls">
    <div class="ctl">
      <label>검색 (종목명/코드)</label>
      <input id="search" type="text" placeholder="예: 삼성, AAPL..."/>
    </div>
    <div class="ctl">
      <label>시장</label>
      <div class="dropdown" id="marketDropdown">
        <button type="button" class="dropdown-btn" id="marketBtn">
          <span id="marketBtnLabel">전체</span><span class="dropdown-arrow">▾</span>
        </button>
        <div class="dropdown-menu" id="marketMenu"></div>
      </div>
    </div>
    <div class="ctl">
      <label>섹터 필터 (입력한 섹터로 거르기)</label>
      <div class="ac-wrap">
        <input id="sectorInput" type="text" autocomplete="off" placeholder="예: 반도체, 2차전지..."/>
      </div>
    </div>
    <div class="ctl">
      <label>섹터 미기입</label>
      <div class="chips">
        <span class="chip" id="noSectorChip">미기입만 보기</span>
      </div>
    </div>
    <div class="ctl">
      <label>신고가 조건 (선택한 것만, OR/AND 전환 가능)</label>
      <div class="chips" id="highChips"></div>
    </div>
    <div class="ctl">
      <label>조건 결합</label>
      <div class="chips match-mode" id="matchMode">
        <span class="chip active" data-mode="or">하나라도(OR)</span>
        <span class="chip" data-mode="and">모두(AND)</span>
      </div>
    </div>
    <div class="ctl">
      <label>정배열</label>
      <div class="chips">
        <span class="chip green" id="alignChip">정배열만 보기</span>
      </div>
    </div>
    <div class="ctl">
      <label>최소 시가총액 (환율 {usd_krw}원 환산 · USD 기준)</label>
      <div class="chips" id="mcapChips">
        <span class="chip active" data-usd="0">전체</span>
        <span class="chip" data-usd="300000000">3억$↑ (약 {krw_small})</span>
        <span class="chip" data-usd="2000000000">20억$↑ (약 {krw_mid})</span>
        <span class="chip" data-usd="10000000000">100억$↑ (약 {krw_large})</span>
        <span class="chip" data-usd="100000000000">1000억$↑ (약 {krw_mega})</span>
      </div>
    </div>
  </div>

  <p class="stats" id="stats"></p>

  <table id="tbl">
    <thead><tr id="thead"></tr></thead>
    <tbody id="tbody"></tbody>
  </table>
</div>
<footer>FinanceDataReader 기반 · 고가 기준 신고가 · 주봉 이동평균 정배열 · 투자 판단의 책임은 본인에게 있습니다.</footer>

<script>
const DATA = {data_json};
const HIGHS = {high_periods};
const MAS = {ma_periods};
const MARKETS = {markets};

const SERVER_MODE = {server_mode};  // true면 섹터 입력/저장 활성화 (localhost 서버)

const state = {{ search:"", market:"", sector:"", noSector:false, highs:new Set(), matchMode:"or",
  alignedOnly:false, sortKey:"high_count", sortDir:-1,
  minCapUsd:0 }};

// symbol -> 섹터 맵 (DATA에서 초기화, 서버 저장과 동기화)
const SECTORS = {{}};
DATA.forEach(r => {{ if(r.sector) SECTORS[r.symbol] = r.sector; }});

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

// ---- 섹터 공통 유틸 ----
function uniqueSectors() {{
  // 현재 저장된 섹터 값들의 고유 목록 (대소문자 무시 중복 제거)
  const seen = new Set(); const out = [];
  Object.values(SECTORS).forEach(s => {{
    s = (s||'').trim(); if(!s) return;
    const k = s.toLowerCase();
    if(!seen.has(k)) {{ seen.add(k); out.push(s); }}
  }});
  out.sort((a,b)=>a.localeCompare(b));
  return out;
}}

// ---- 커스텀 자동완성 (datalist 대체, 다크테마) ----
// input 아래에 .ac-menu 패널을 띄워 추천 섹터를 보여준다.
function attachAutocomplete(input, onPick) {{
  const wrap = input.closest('.ac-wrap') || (() => {{
    // 행 입력칸처럼 .ac-wrap이 없으면 즉석에서 감싼다
    const w = document.createElement('span'); w.className = 'ac-wrap';
    w.style.position = 'relative'; w.style.display = 'inline-block';
    input.parentNode.insertBefore(w, input); w.appendChild(input);
    return w;
  }})();
  let menu = wrap.querySelector('.ac-menu');
  if(!menu) {{ menu = document.createElement('div'); menu.className = 'ac-menu'; wrap.appendChild(menu); }}
  let activeIdx = -1, items = [];

  function close() {{ menu.classList.remove('open'); activeIdx = -1; }}
  function open() {{
    const q = input.value.trim().toLowerCase();
    const all = uniqueSectors();
    items = q ? all.filter(s => s.toLowerCase().includes(q)) : all;
    if(items.length === 0) {{ close(); return; }}
    menu.innerHTML = items.map((s,i) =>
      `<div class="ac-item${{i===activeIdx?' active':''}}" data-i="${{i}}">${{s.replace(/</g,'&lt;')}}</div>`
    ).join('');
    menu.classList.add('open');
  }}
  function pick(val) {{ input.value = val; close(); onPick(val); }}

  input.addEventListener('focus', open);
  input.addEventListener('click', open);
  input.addEventListener('input', () => {{ activeIdx = -1; open(); }});
  input.addEventListener('keydown', e => {{
    if(!menu.classList.contains('open')) return;
    if(e.key === 'ArrowDown') {{ e.preventDefault(); activeIdx = Math.min(activeIdx+1, items.length-1); open(); }}
    else if(e.key === 'ArrowUp') {{ e.preventDefault(); activeIdx = Math.max(activeIdx-1, 0); open(); }}
    else if(e.key === 'Enter') {{ if(activeIdx>=0) {{ e.preventDefault(); pick(items[activeIdx]); }} }}
    else if(e.key === 'Escape') {{ close(); }}
  }});
  menu.addEventListener('mousedown', e => {{   // blur보다 먼저 처리되도록 mousedown
    const it = e.target.closest('.ac-item'); if(!it) return;
    e.preventDefault(); pick(items[parseInt(it.dataset.i)]);
  }});
  input.addEventListener('blur', () => setTimeout(close, 120));
  return {{ close, open }};
}}

// 상단 섹터 필터 입력칸
const sectorInput = document.getElementById('sectorInput');
attachAutocomplete(sectorInput, () => {{
  state.sector = sectorInput.value.trim().toLowerCase(); render();
}});
sectorInput.addEventListener('input', () => {{ state.sector = sectorInput.value.trim().toLowerCase(); render(); }});

// 미기입만 보기 토글
const noSectorChip = document.getElementById('noSectorChip');
noSectorChip.addEventListener('click', ()=>{{
  state.noSector = !state.noSector; noSectorChip.classList.toggle('active'); render();
}});

// ---- 서버에 섹터 저장 ----
async function saveSector(symbol, sector) {{
  SECTORS[symbol] = sector;  // 로컬 즉시 반영
  if(!SERVER_MODE) return;
  try {{
    await fetch('/api/sector', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{symbol, sector}})
    }});
  }} catch(e) {{ console.warn('섹터 저장 실패', e); }}
}}

const highChips = document.getElementById('highChips');
HIGHS.forEach(p => {{
  const c=document.createElement('span'); c.className='chip'; c.textContent=p+'주'; c.dataset.p=p;
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
  {{k:'close', t:'종가', num:true}},
  {{k:'mcap', t:'시가총액', num:true}},
];
HIGHS.forEach(p => COLS.push({{k:'h'+p, t:p+'주신고가'}}));
COLS.push({{k:'aligned', t:'정배열'}});
COLS.push({{k:'sector', t:'섹터 (직접 입력)'}});
COLS.push({{k:'high_count', t:'충족수', num:true}});
COLS.push({{k:'last_date', t:'기준주'}});

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
  const curSector = (SECTORS[r.symbol]||'');
  if(state.noSector) {{
    if(curSector.trim()!=='') return false;
  }}
  if(state.sector) {{
    if(!curSector.toLowerCase().includes(state.sector)) return false;
  }}
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

function cell(r, k) {{
  if(k==='symbol') return `<span class="sym">${{r.symbol}}</span>`;
  if(k==='name') return `${{r.name}} <span class="cc">${{r.country}}</span>`;
  if(k==='market') return `<span class="mkt">${{r.market}}</span>`;
  if(k==='close') return `<span class="num">${{r.close_fmt}}</span>`;
  if(k==='mcap') return `<span class="num">${{r.mcap_fmt}}</span>`;
  if(k==='aligned') return r.aligned ? '<span class="aligned-yes">정배열</span>' : '<span class="no">-</span>';
  if(k==='sector') {{
    const v = (SECTORS[r.symbol]||'').replace(/"/g,'&quot;');
    return `<input class="sector-edit" data-sym="${{r.symbol}}" autocomplete="off" `
      + `value="${{v}}" placeholder="섹터 입력..." />`;
  }}
  if(k==='high_count') return `<span class="num">${{r.high_count}}</span>`;
  if(k==='last_date') return `<span class="cc">${{r.last_date}}</span>`;
  if(k.startsWith('h')) {{
    const v=r[k];
    if(v===null) return '<span class="na">·</span>';
    return v ? '<span class="tag yes">신고가</span>' : '<span class="no">-</span>';
  }}
  return '';
}}

function render() {{
  let rows = DATA.filter(passFilter);
  const k=state.sortKey, dir=state.sortDir;
  rows.sort((a,b)=>{{
    let av=a[k], bv=b[k];
    if(k.startsWith('h')||k==='aligned') {{ av=av?1:0; bv=bv?1:0; }}
    if(k==='close') {{ av=a.close||0; bv=b.close||0; }}
    // 시가총액은 환율 환산(USD) 값으로 비교
    if(k==='mcap') {{ av=(a.mcap_usd==null?-1:a.mcap_usd); bv=(b.mcap_usd==null?-1:b.mcap_usd); }}
    if(k==='sector') {{ av=(SECTORS[a.symbol]||''); bv=(SECTORS[b.symbol]||''); }}
    if(typeof av==='string') return av.localeCompare(bv)*dir;
    return (av-bv)*dir;
  }});

  const tbody=document.getElementById('tbody'); tbody.innerHTML='';
  const frag=document.createDocumentFragment();
  rows.forEach(r => {{
    const tr=document.createElement('tr');
    tr.innerHTML = COLS.map(c=>`<td${{c.num?' class="num"':''}}>${{cell(r,c.k)}}</td>`).join('');
    frag.appendChild(tr);
  }});
  tbody.appendChild(frag);

  document.getElementById('stats').innerHTML =
    `표시 <b>${{rows.length}}</b> / 전체 ${{DATA.length}}종목 · 정배열 <b>${{rows.filter(r=>r.aligned).length}}</b>`;

  document.querySelectorAll('#thead th').forEach(th=>{{
    th.classList.remove('sort-asc','sort-desc','sort-ind');
    if(th.dataset.k===k) th.classList.add(dir>0?'sort-asc':'sort-desc'); else th.classList.add('sort-ind');
  }});
}}

// 섹터 입력칸: 변경 시 서버 저장 (이벤트 위임으로 재렌더링에도 안전)
const tbodyEl = document.getElementById('tbody');
tbodyEl.addEventListener('change', e => {{
  const inp = e.target.closest('.sector-edit');
  if(!inp) return;
  saveSector(inp.dataset.sym, inp.value.trim());
}});
// 행 섹터 입력칸: 포커스되면 커스텀 자동완성 1회 연결 (테이블은 매번 재렌더됨)
tbodyEl.addEventListener('focusin', e => {{
  const inp = e.target.closest('.sector-edit');
  if(!inp) return;
  if(!inp.dataset.acReady) {{
    inp.dataset.acReady = '1';
    inp._ac = attachAutocomplete(inp, (val) => saveSector(inp.dataset.sym, val));
  }}
  // 지금 발생한 포커스 이벤트는 attach 전이라 놓치므로 즉시 한 번 연다
  if(inp._ac) inp._ac.open();
}});

render();
</script>
</body>
</html>
"""
