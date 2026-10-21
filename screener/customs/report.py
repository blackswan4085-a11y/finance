"""HTML 셸 + 클라이언트 JS/CSS 생성. 외부 의존성 0, 차트는 순수 인라인 SVG.

서버는 JSON API(/api/*)를 제공하고, 이 페이지의 바닐라 JS 가 이를 받아
표와 SVG 차트를 그린다. --static 모드에서는 데이터를 미리 임베드한다.
"""
from __future__ import annotations

import json
from html import escape

from ..ui import shared_ui

PAGE_CSS = """
:root{
  --bg:#0f1420; --panel:#161c2b; --panel2:#1d2639; --line:#2a3550;
  --txt:#e6ecf5; --muted:#8a97b1; --up:#ff5c6c; --down:#4a90ff;
  --exp:#4a90ff; --imp:#ff5c6c; --accent:#5ad1a8; --chip:#243049;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Malgun Gothic","Apple SD Gothic Neo",sans-serif;}
a{color:inherit;text-decoration:none}
.wrap{max-width:1280px;margin:0 auto;padding:18px 20px 60px}
header.top{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;
  border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:14px}
header.top h1{font-size:20px;margin:0;letter-spacing:-.3px}
header.top .title-wrap{display:flex;flex-direction:column;gap:4px}
header.top .meta{color:var(--muted);font-size:12.5px}
.update-btn{background:linear-gradient(180deg,#5ad1a8,#39b98c);color:#06281e;border:none;
  border-radius:9px;padding:9px 15px;font-weight:700;font-size:13px;cursor:pointer;box-shadow:0 2px 10px rgba(90,209,168,.25)}
.update-btn:hover{filter:brightness(1.05)}
.update-btn:disabled{opacity:.6;cursor:progress;filter:grayscale(.3)}
.update-status{background:var(--panel2);border:1px solid var(--line);border-radius:10px;
  padding:10px 14px;margin-bottom:14px;font-size:13px;display:flex;align-items:center;gap:12px}
.update-status .bar{flex:1;height:7px;background:#0e1626;border-radius:6px;overflow:hidden;min-width:120px}
.update-status .bar>i{display:block;height:100%;background:linear-gradient(90deg,#5ad1a8,#4a90ff);width:0;transition:width .3s}
.update-status .msg{color:var(--muted);white-space:nowrap}
.update-status.done{border-color:#2f6b52}
.update-status.err{border-color:#7a3340}
.breadcrumb{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:4px 0 16px;font-size:13px}
.breadcrumb .crumb{background:var(--chip);padding:5px 11px;border-radius:999px;cursor:pointer;
  border:1px solid var(--line);white-space:nowrap}
.breadcrumb .crumb:hover{border-color:var(--accent)}
.breadcrumb .crumb.active{background:var(--accent);color:#06281e;border-color:var(--accent);font-weight:600;cursor:default}
.breadcrumb .sep{color:var(--muted)}
.grid{display:grid;grid-template-columns:1fr;gap:16px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}
.panel h2{font-size:14px;margin:0 0 12px;color:var(--muted);font-weight:600;letter-spacing:.2px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--muted);font-weight:600;cursor:pointer;user-select:none;position:sticky;top:0;background:var(--panel)}
th:first-child,td:first-child{text-align:left}
td.name{text-align:left;color:var(--muted);max-width:360px;overflow:hidden;text-overflow:ellipsis}
tr.row{cursor:pointer}
tr.row:hover td{background:var(--panel2)}
tr.leaf{cursor:default}
tr.leaf:hover td{background:transparent}
.code{font-variant-numeric:tabular-nums;font-weight:600}
.pos{color:var(--up)} .neg{color:var(--down)}
.tablewrap{max-height:520px;overflow:auto;border-radius:8px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:4px}
.kpi{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.kpi .label{color:var(--muted);font-size:12px;margin-bottom:6px}
.kpi .val{font-size:19px;font-weight:700;font-variant-numeric:tabular-nums}
.kpi .sub{font-size:12px;margin-top:4px}
/* ===== 첫 화면 히어로 / 개요 ===== */
.hero{background:linear-gradient(135deg,#19233a 0%,#141c2e 60%,#17283a 100%);
  border:1px solid var(--line);border-radius:16px;padding:20px 22px;position:relative;overflow:hidden}
.hero::after{content:"";position:absolute;right:-40px;top:-40px;width:220px;height:220px;
  background:radial-gradient(circle,rgba(90,209,168,.14),transparent 70%)}
.hero .htitle{font-size:13px;color:var(--muted);margin-bottom:14px;font-weight:600}
.hero .htitle b{color:var(--txt)}
.hero-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;position:relative;z-index:1}
.hero-card{background:#0f172799;border:1px solid var(--line);border-radius:13px;padding:15px 17px}
.hero-card .hc-label{font-size:12.5px;color:var(--muted);display:flex;align-items:center;gap:7px;margin-bottom:9px}
.hero-card .hc-label .ic{width:8px;height:8px;border-radius:2px;display:inline-block}
.hero-card .hc-val{font-size:28px;font-weight:800;letter-spacing:-.5px;font-variant-numeric:tabular-nums}
.hero-card .hc-chips{display:flex;gap:7px;margin-top:11px;flex-wrap:wrap}
.chip-pct{font-size:11.5px;font-weight:700;padding:3px 9px;border-radius:999px;
  display:inline-flex;align-items:center;gap:4px;font-variant-numeric:tabular-nums;
  background:#1b2538;border:1px solid var(--line)}
.chip-pct .k{color:var(--muted);font-weight:600}
.chip-pct.up{color:var(--up);border-color:#4a2a30}
.chip-pct.down{color:var(--down);border-color:#223a63}
.ov-row2{display:grid;grid-template-columns:1.3fr 1fr;gap:16px}
@media(max-width:900px){.ov-row2{grid-template-columns:1fr}.hero-grid{grid-template-columns:1fr}}
.spark-row td{vertical-align:middle}
.cell-pct{font-weight:700;font-variant-numeric:tabular-nums}
.mini-bars{display:flex;align-items:flex-end;gap:2px;height:26px}
.mini-bars i{flex:1;background:#33508a;border-radius:1px;min-height:2px}
.rankbar{position:relative;height:8px;background:#0e1626;border-radius:5px;overflow:hidden;min-width:60px}
.rankbar>i{display:block;height:100%;background:linear-gradient(90deg,#4a90ff,#5ad1a8);border-radius:5px}
.charts{display:grid;grid-template-columns:1fr;gap:16px}
.charts .full{grid-column:1/-1}
.chart-row{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.legend{display:flex;gap:16px;font-size:12px;color:var(--muted);margin-bottom:6px}
.legend .dot{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:middle}
svg{display:block;width:100%;height:auto;touch-action:none}
.svg-tip{font-size:10.5px;fill:var(--muted)}
.svg-ax{font-size:11.5px;fill:#c3cde3;font-weight:700}
.svg-mo{font-size:9.5px;fill:#6b7794}
.svg-val{font-size:10px;fill:#c3cde3;font-weight:600}
.badge-txt{font-size:10.5px;fill:#fff;font-weight:700}
.chart-tip{position:fixed;z-index:9999;pointer-events:none;min-width:150px;
  background:#0b1019;border:1px solid #39456685;border-radius:10px;padding:9px 11px;
  box-shadow:0 8px 28px rgba(0,0,0,.5);font-size:12.5px;color:var(--txt);backdrop-filter:blur(2px)}
.chart-tip .th{font-weight:700;margin-bottom:6px;color:#fff;border-bottom:1px solid #2a3550;padding-bottom:5px}
.chart-tip .tr{display:flex;align-items:center;gap:7px;padding:2px 0;white-space:nowrap}
.chart-tip .tr b{margin-left:auto;font-variant-numeric:tabular-nums}
.chart-tip .tr.sub{color:var(--muted);font-size:11.5px;margin-top:2px}
.chart-tip .dot{width:9px;height:9px;border-radius:2px;display:inline-block}
.companies .co{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--line)}
.companies .co .nm{font-weight:600}
.companies .co .nt{color:var(--muted);flex:1;font-size:12.5px}
.companies form{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}
input,button{font:inherit}
input[type=text]{background:var(--panel2);border:1px solid var(--line);color:var(--txt);
  border-radius:8px;padding:8px 10px;outline:none}
input[type=text]:focus{border-color:var(--accent)}
button{background:var(--accent);color:#06281e;border:none;border-radius:8px;padding:8px 14px;
  font-weight:600;cursor:pointer}
button.ghost{background:var(--chip);color:var(--txt);border:1px solid var(--line)}
button:hover{filter:brightness(1.06)}
.del{background:transparent;color:var(--muted);border:1px solid var(--line);padding:4px 9px;border-radius:7px}
.del:hover{color:var(--up);border-color:var(--up)}
.empty{color:var(--muted);font-size:13px;padding:6px 0}
.hint{color:var(--muted);font-size:12px;margin-top:8px}
@media(max-width:860px){.kpis{grid-template-columns:repeat(2,1fr)}.chart-row{grid-template-columns:1fr}}
"""


FINANCE_CSS = """
.finance-customs{margin:0;font-size:13px}
.finance-customs .wrap{max-width:1440px;padding-top:22px}
.finance-customs .top h1{font-size:22px;letter-spacing:-.04em}
.finance-customs .hero{background:linear-gradient(120deg,var(--panel),var(--accent-soft));border-radius:12px}
.finance-customs .hero::after{display:none}
.finance-customs .hero-card,.finance-customs .chip-pct{background:var(--panel)}
.finance-customs .hero-card{border-radius:9px}
.finance-customs .panel{border-radius:9px}
.finance-customs .chip-pct.up,.finance-customs .chip-pct.down{border-color:var(--line)}
.finance-customs .crumb{background:var(--panel)}
.finance-customs .crumb{max-width:min(100%,80ch);overflow:hidden;text-overflow:ellipsis}
.finance-customs .crumb.active{background:var(--accent-soft);color:var(--accent);border-color:var(--accent)}
.finance-customs .chart-tip{background:var(--panel);border-color:var(--line);box-shadow:var(--shadow)}
.finance-customs .chart-tip .th{color:var(--txt);border-color:var(--line)}
.finance-customs .svg-ax,.finance-customs .svg-val{fill:var(--text)}
.finance-customs .svg-mo{fill:var(--muted)}
.finance-customs .rankbar,.finance-customs .update-status .bar{background:var(--panel2)}
.finance-customs button:not(.theme-toggle):not(.update-button):not(.del):not(.ghost){background:var(--accent-soft);color:var(--accent)}
.finance-customs .update-status{background:var(--panel);border-radius:8px;flex-wrap:wrap}
.finance-customs .update-status .msg{white-space:normal;line-height:1.7}
.finance-customs .empty{padding:24px;text-align:center;line-height:1.8}
.finance-customs .companies .empty{padding:8px;text-align:left}
.finance-customs .finance-brand h1{font-size:17px}
@media(max-width:600px){.finance-customs .wrap{padding:16px 12px 40px}.finance-customs .finance-header{padding:12px}.finance-customs .hero{padding:16px}.finance-customs .hero-card .hc-val{font-size:25px}.finance-customs .finance-nav{flex-wrap:wrap}}
"""


def page_html(meta: dict, embedded: dict | None = None) -> str:
    """대시보드 메인 페이지. embedded 가 주어지면 정적 모드로 데이터를 임베드."""
    latest = meta.get("latest_month", "")
    latest_disp = f"{latest[:4]}.{latest[4:]}" if latest else "-"
    embed_json = json.dumps(embedded, ensure_ascii=False).replace("<", "\\u003c") if embedded else "null"
    static_flag = "true" if embedded else "false"
    theme = shared_ui() if embedded else '<link rel="stylesheet" href="/ui.css"><script src="/ui.js"></script>'
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>수출입 통계 · Finance</title>
<style>{PAGE_CSS}</style>
{theme}
<style>{FINANCE_CSS}</style>
</head><body class="finance-customs">
<header class="finance-header workspace-bar">
  <a class="finance-brand" href="/"><span class="brand-mark" aria-hidden="true">▥</span><h1>Finance</h1></a>
  <div class="header-actions"><nav class="finance-nav" aria-label="화면 이동"></nav><button class="theme-toggle" type="button" data-theme-toggle aria-label="테마 변경">☾</button></div>
</header>
<div class="wrap">
  <header class="top">
    <div class="title-wrap">
      <h1>수출입 통계</h1>
      <span class="meta" id="meta-line">관세청 · 기준월 <b>{escape(latest_disp)}</b> · 수집범위 {escape(meta.get('range','-'))} · 수집시각 {escape(meta.get('collected_at','-'))}</span>
    </div>
    <div class="top-actions">
      <button id="update-btn" class="update-button" title="관세청 API에서 최신 데이터를 가져옵니다">데이터 업데이트</button>
    </div>
  </header>
  <p class="hint">금액: USD · YoY: 전년동월 대비 · QoQ: 분기 누적액의 전분기 대비 (진행 중인 분기 포함)</p>
  <div id="update-status" class="update-status" style="display:none"></div>
  <div class="breadcrumb" id="breadcrumb"></div>
  <div id="app" class="grid"></div>
</div>
<script>
const EMBEDDED = {embed_json};
const STATIC = {static_flag};
const LATEST = {json.dumps(latest).replace('<', chr(92) + 'u003c')};
</script>
<script>{PAGE_JS}</script>
</body></html>"""


PAGE_JS = r"""
// ---------- 유틸 ----------
function fmtUSD(v){
  if(v===null||v===undefined||isNaN(v)) return '-';
  const a=Math.abs(v);
  if(a>=1e9) return '$'+(v/1e9).toFixed(2)+'B';
  if(a>=1e6) return '$'+(v/1e6).toFixed(2)+'M';
  if(a>=1e3) return '$'+(v/1e3).toFixed(1)+'K';
  return '$'+Math.round(v).toLocaleString();
}
function fmtPct(v){ return (v===null||v===undefined||isNaN(v))?'-':(v>=0?'+':'')+v.toFixed(1)+'%'; }
function cls(v){ return v>=0?'pos':'neg'; }
function esc(value){ return String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
// 방향 색상(한국식): 상승=빨강, 하락=파랑. 증감률(YoY/QoQ) 막대·배지에 사용.
const UP='#ff5c6c', DOWN='#4a90ff';
function dirColor(v){ return v>=0?UP:DOWN; }
// 계열 식별 색상: 수출=파랑, 수입=빨강 (라인/그룹막대 등 2계열 구분용)
const C_EXP='#4a90ff', C_IMP='#ff5c6c';
function el(tag,attrs,children){
  const e=document.createElement(tag);
  if(attrs) for(const k in attrs){ if(k==='class')e.className=attrs[k]; else if(k==='html')e.innerHTML=attrs[k]; else e.setAttribute(k,attrs[k]); }
  (children||[]).forEach(c=>{ if(typeof c==='string')e.appendChild(document.createTextNode(c)); else if(c)e.appendChild(c); });
  return e;
}

// ---------- API ----------
async function api(path){
  if(STATIC){ return EMBEDDED[path] || null; }
  const r=await fetch(path.replace('/api/', '/api/customs/'), {cache:'no-store'});
  const data=await r.json();
  if(!r.ok) throw new Error(data.error || '자료를 불러오지 못했습니다.');
  return data;
}
async function apiPost(path,body){
  if(STATIC) return {ok:false,static:true};
  const r=await fetch(path.replace('/api/', '/api/customs/'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await r.json();
  if(!r.ok || data.ok===false) throw new Error(data.error || '변경 내용을 저장하지 못했습니다.');
  return data;
}

// ---------- 상태 ----------
const state={ path:[] }; // ['85','8542','854232'] 최대 3

function pathKey(){ return state.path.join('/'); }

// ---------- 공통: 툴팁 + 차트 래퍼 ----------
const SVGNS='http://www.w3.org/2000/svg';
function svgAdd(parent,tag,at){const e=document.createElementNS(SVGNS,tag);for(const k in at)e.setAttribute(k,at[k]);parent.appendChild(e);return e;}
let _tipEl=null;
function tipEl(){
  if(!_tipEl){ _tipEl=document.createElement('div'); _tipEl.className='chart-tip'; _tipEl.style.display='none'; document.body.appendChild(_tipEl); }
  return _tipEl;
}
function hideTip(){ tipEl().style.display='none'; }
function showTip(html, clientX, clientY){
  const t=tipEl(); t.innerHTML=html; t.style.display='block';
  const pad=14, tw=t.offsetWidth, th=t.offsetHeight;
  let x=clientX+pad, y=clientY+pad;
  if(x+tw>window.innerWidth-8) x=clientX-tw-pad;
  if(y+th>window.innerHeight-8) y=clientY-th-pad;
  t.style.left=Math.max(6,x)+'px'; t.style.top=Math.max(6,y)+'px';
}
function ymLabel(period){ return period.slice(0,4)+'.'+period.slice(4); }     // 2026.03
function ymLong(period){ return period.slice(0,4)+'년 '+(+period.slice(4))+'월'; } // 2026년 3월
function qLabel(label){ // "2026 Q3" -> "3Q26"
  const m=label.match(/(\d{4})\s*Q(\d)/); if(!m) return label;
  return m[2]+'Q'+m[1].slice(2);
}

// 주식 차트식 hover: 세로+가로 십자선 + x축 날짜 배지(아래 뾰족) + y축 값 배지.
// geom: {m,iw,ih,W,H,X(i),n, onIndex(i,markG)-> {html, yFocus, xBadge, yBadge}}
function attachHover(svg, geom){
  const {m,W,H,n}=geom;
  const top=m.t, bot=m.t+geom.ih, left=m.l, right=W-m.r;
  // 십자선 (세로/가로)
  const vLine=svgAdd(svg,'line',{x1:0,y1:top,x2:0,y2:bot,stroke:'#9aa6c0','stroke-width':1,'stroke-dasharray':'3 3',opacity:0});
  const hLine=svgAdd(svg,'line',{x1:left,y1:0,x2:right,y2:0,stroke:'#9aa6c0','stroke-width':1,'stroke-dasharray':'3 3',opacity:0});
  const markG=svgAdd(svg,'g',{opacity:0});
  // x축 날짜 배지 (플롯 하단 밖으로 뾰족 튀어나옴)
  const xBadgeG=svgAdd(svg,'g',{opacity:0});
  const xTri=svgAdd(xBadgeG,'path',{fill:'#38466a'});
  const xRect=svgAdd(xBadgeG,'rect',{rx:3,fill:'#38466a'});
  const xTxt=svgAdd(xBadgeG,'text',{'text-anchor':'middle',class:'badge-txt'});
  // y축 값 배지 (왼쪽 축 위에)
  const yBadgeG=svgAdd(svg,'g',{opacity:0});
  const yRect=svgAdd(yBadgeG,'rect',{rx:3,fill:'#38466a'});
  const yTxt=svgAdd(yBadgeG,'text',{'text-anchor':'end',class:'badge-txt'});

  const overlay=svgAdd(svg,'rect',{x:left,y:top,width:geom.iw,height:geom.ih,fill:'transparent','pointer-events':'all'});

  function idxFromClient(evt){
    const r=svg.getBoundingClientRect();
    const sx=(evt.clientX-r.left)/r.width*W;
    let best=0,bd=1e9;
    for(let i=0;i<n;i++){ const d=Math.abs(geom.X(i)-sx); if(d<bd){bd=d;best=i;} }
    return best;
  }
  function placeXBadge(cx, label){
    const w=Math.max(44, label.length*8+14), h=17, bx=Math.min(Math.max(cx-w/2,left-20),right-w+20), by=bot+6;
    xRect.setAttribute('x',bx); xRect.setAttribute('y',by); xRect.setAttribute('width',w); xRect.setAttribute('height',h);
    xTxt.setAttribute('x',bx+w/2); xTxt.setAttribute('y',by+12); xTxt.textContent=label;
    // 삼각 꼭지 (위쪽 중앙, 플롯 경계를 향함)
    xTri.setAttribute('d',`M${cx-5} ${by} L${cx+5} ${by} L${cx} ${by-5} Z`);
  }
  function placeYBadge(cy, label){
    const w=Math.max(44, label.length*7.2+12), h=16, bx=left-w-6, by=Math.min(Math.max(cy-h/2,top),bot-h);
    yRect.setAttribute('x',bx); yRect.setAttribute('y',by); yRect.setAttribute('width',w); yRect.setAttribute('height',h);
    yTxt.setAttribute('x',bx+w-6); yTxt.setAttribute('y',by+11.5); yTxt.textContent=label;
  }
  function move(evt){
    const i=idxFromClient(evt);
    const cx=geom.X(i);
    while(markG.firstChild) markG.removeChild(markG.firstChild);
    const res=geom.onIndex(i, markG);
    vLine.setAttribute('x1',cx); vLine.setAttribute('x2',cx); vLine.setAttribute('opacity',1);
    markG.setAttribute('opacity',1);
    // 가로선 + y배지 (yFocus 가 있을 때만)
    if(res.yFocus!=null){
      hLine.setAttribute('y1',res.yFocus); hLine.setAttribute('y2',res.yFocus); hLine.setAttribute('opacity',1);
      if(res.yBadge!=null){ placeYBadge(res.yFocus,res.yBadge); yBadgeG.setAttribute('opacity',1); } else yBadgeG.setAttribute('opacity',0);
    } else { hLine.setAttribute('opacity',0); yBadgeG.setAttribute('opacity',0); }
    // x배지
    if(res.xBadge!=null){ placeXBadge(cx,res.xBadge); xBadgeG.setAttribute('opacity',1); } else xBadgeG.setAttribute('opacity',0);
    showTip(res.html, evt.clientX, evt.clientY);
  }
  function leave(){ vLine.setAttribute('opacity',0); hLine.setAttribute('opacity',0); markG.setAttribute('opacity',0);
    xBadgeG.setAttribute('opacity',0); yBadgeG.setAttribute('opacity',0); hideTip(); }
  overlay.addEventListener('mousemove',move);
  overlay.addEventListener('mouseleave',leave);
  overlay.addEventListener('touchmove',e=>{ if(e.touches[0]){move(e.touches[0]); e.preventDefault();} },{passive:false});
  overlay.addEventListener('touchend',leave);
}

// ---------- SVG 차트 ----------
function lineChart(series, opts){
  // series: [{period, exp_dlr, imp_dlr}] 오름차순
  const W=opts.w||920, H=opts.h||344, m={t:18,r:18,b:48,l:70};
  const iw=W-m.l-m.r, ih=H-m.t-m.b;
  const keys=opts.keys; // [{field,color,name}]
  let maxv=0;
  series.forEach(d=>keys.forEach(k=>{maxv=Math.max(maxv,d[k.field]||0)}));
  maxv=(maxv||1)*1.08;
  const n=series.length;
  const X=i=> m.l + (n<=1?iw/2:(i/(n-1))*iw);
  const Y=v=> m.t + ih - (v/maxv)*ih;
  const svg=document.createElementNS(SVGNS,'svg');
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio','xMidYMid meet');
  const add=(tag,at)=>svgAdd(svg,tag,at);
  // 그라데이션
  const defs=add('defs',{});
  keys.forEach((k,ki)=>{
    const gid='g'+ki+'_'+Math.random().toString(36).slice(2,7); k._gid=gid;
    const lg=svgAdd(defs,'linearGradient',{id:gid,x1:0,y1:0,x2:0,y2:1});
    svgAdd(lg,'stop',{offset:'0%','stop-color':k.color,'stop-opacity':0.26});
    svgAdd(lg,'stop',{offset:'100%','stop-color':k.color,'stop-opacity':0});
  });
  // y 그리드
  for(let g=0; g<=4; g++){ const v=maxv*g/4, y=Y(v);
    add('line',{x1:m.l,y1:y,x2:W-m.r,y2:y,stroke:'#273149','stroke-width':1});
    const t=add('text',{x:m.l-8,y:y+3.5,'text-anchor':'end'}); t.setAttribute('class','svg-tip'); t.textContent=fmtUSD(v);
  }
  // x축: 연 경계(1월)는 굵은 라벨+구분선, 그 사이 분기(4/7/10월)는 옅은 월 눈금.
  // 간격이 안 맞는 맨 왼쪽(1월이 아닌 시작월) 연도 라벨은 생략한다.
  const axY=H-m.b+26;
  series.forEach((d,i)=>{
    const yr=d.period.slice(0,4), mo=d.period.slice(4);
    if(mo==='01'){
      add('line',{x1:X(i),y1:m.t,x2:X(i),y2:m.t+ih,stroke:'#303c58','stroke-width':1});
      const t=add('text',{x:X(i),y:axY,'text-anchor':'middle'}); t.setAttribute('class','svg-ax'); t.textContent=yr;
    } else if(mo==='04'||mo==='07'||mo==='10'){
      const t=add('text',{x:X(i),y:axY,'text-anchor':'middle'}); t.setAttribute('class','svg-mo'); t.textContent=(+mo)+'월';
      add('line',{x1:X(i),y1:m.t+ih-4,x2:X(i),y2:m.t+ih,stroke:'#3a4765','stroke-width':1});
    }
  });
  // 면적 + 라인
  keys.forEach(k=>{
    let dpath='', area='';
    series.forEach((d,i)=>{ const px=X(i),py=Y(d[k.field]||0);
      dpath+=(i===0?'M':'L')+px.toFixed(1)+' '+py.toFixed(1)+' ';
      area+=(i===0?('M'+px.toFixed(1)+' '+(m.t+ih)+' L'):'L')+px.toFixed(1)+' '+py.toFixed(1)+' ';
    });
    area+='L'+X(n-1).toFixed(1)+' '+(m.t+ih)+' Z';
    add('path',{d:area,fill:'url(#'+k._gid+')',stroke:'none'});
    add('path',{d:dpath,fill:'none',stroke:k.color,'stroke-width':2.2,'stroke-linejoin':'round','stroke-linecap':'round'});
    const last=series[n-1];
    add('circle',{cx:X(n-1),cy:Y(last[k.field]||0),r:3.2,fill:k.color,stroke:'#0f1420','stroke-width':1.5});
  });
  // hover
  attachHover(svg,{m,iw,ih,W,H,n,X,onIndex:(i,markG)=>{
    const d=series[i];
    keys.forEach(k=>{ svgAdd(markG,'circle',{cx:X(i),cy:Y(d[k.field]||0),r:4,fill:k.color,stroke:'#0f1420','stroke-width':1.5}); });
    let rows='';
    keys.forEach(k=>{ const nm=k.name||(k.field==='exp_dlr'?'수출':k.field==='imp_dlr'?'수입':k.field);
      rows+=`<div class="tr"><span class="dot" style="background:${k.color}"></span>${nm}<b>${fmtUSD(d[k.field]||0)}</b></div>`; });
    const bal=(d.exp_dlr||0)-(d.imp_dlr||0);
    rows+=`<div class="tr sub">무역수지<b class="${bal>=0?'pos':'neg'}">${fmtUSD(bal)}</b></div>`;
    // 가로 십자선은 주 계열(첫번째=수출)에 맞춤
    const prim=keys[0], yF=Y(d[prim.field]||0);
    return {html:`<div class="th">${ymLong(d.period)}</div>${rows}`, yFocus:yF, xBadge:ymLabel(d.period), yBadge:fmtUSD(d[prim.field]||0)};
  }});
  return svg;
}

function barChart(items, opts){
  // items: [{label, value}], label 은 "2026 Q3", value 는 % (음수 가능)
  items=items.filter(d=>d.value!=null);
  if(!items.length){ const s=document.createElementNS(SVGNS,'svg'); s.setAttribute('viewBox','0 0 460 120');
    svgAdd(s,'text',{x:230,y:60,'text-anchor':'middle',class:'svg-tip'}).textContent='데이터가 부족합니다';
    return s; }
  const W=opts.w||460, H=opts.h||284, m={t:16,r:14,b:50,l:52};
  const iw=W-m.l-m.r, ih=H-m.t-m.b;
  const vals=items.map(d=>d.value);
  const {lo,hi}=niceBounds(Math.min(...vals),Math.max(...vals));
  const n=items.length, step=iw/n;
  const svg=document.createElementNS(SVGNS,'svg');
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio','xMidYMid meet');
  const add=(tag,at)=>svgAdd(svg,tag,at);
  const Y=v=> m.t + ih - ((v-lo)/(hi-lo))*ih;
  const zeroY=Y(0);
  const cxOf=i=> m.l+step*i+step/2;
  for(let g=0;g<=4;g++){ const v=lo+(hi-lo)*g/4, y=Y(v);
    add('line',{x1:m.l,y1:y,x2:W-m.r,y2:y,stroke:'#273149','stroke-width':1});
    const t=add('text',{x:m.l-8,y:y+3.5,'text-anchor':'end'}); t.setAttribute('class','svg-tip'); t.textContent=v.toFixed(0)+'%';
  }
  add('line',{x1:m.l,y1:zeroY,x2:W-m.r,y2:zeroY,stroke:'#4a5675','stroke-width':1.4});
  const bw=Math.max(3, Math.min(26, step*0.6));
  const labelEvery=Math.max(1, Math.ceil(34/step));
  const bars=[];
  items.forEach((d,i)=>{
    const cx=cxOf(i), v=d.value, y=Y(v), h=Math.abs(y-zeroY);
    const rect=add('rect',{x:cx-bw/2,y:Math.min(y,zeroY),width:bw,height:Math.max(1,h),
      fill: dirColor(v), rx:2}); bars.push(rect);
    if(n<=14){ const ty = v>=0 ? Math.min(y,zeroY)-4 : Math.max(y,zeroY)+12;
      const vt=add('text',{x:cx,y:ty,'text-anchor':'middle'}); vt.setAttribute('class','svg-val'); vt.textContent=(v>=0?'+':'')+v.toFixed(0);
    }
    if(i%labelEvery===0 || i===n-1){
      const t=add('text',{x:cx,y:H-m.b+16,'text-anchor':'end',transform:`rotate(-40 ${cx} ${H-m.b+16})`});
      t.setAttribute('class','svg-ax'); t.textContent=qLabel(d.label);
    }
  });
  // hover
  attachHover(svg,{m,iw,ih,W,H,n,X:cxOf,onIndex:(i,markG)=>{
    const d=items[i], v=d.value, yF=Y(v);
    bars.forEach((b,bi)=>b.setAttribute('opacity', bi===i?1:0.35));
    svgAdd(markG,'rect',{x:cxOf(i)-bw/2-2,y:m.t,width:bw+4,height:ih,fill:'#ffffff',opacity:0.04});
    return {html:`<div class="th">${qLabel(d.label)}</div>`+
           `<div class="tr"><span class="dot" style="background:${dirColor(v)}"></span>수출 QoQ<b class="${v>=0?'pos':'neg'}">${fmtPct(v)}</b></div>`,
           yFocus:yF, xBadge:qLabel(d.label), yBadge:(v>=0?'+':'')+v.toFixed(1)+'%'};
  }});
  svg.addEventListener('mouseleave',()=>bars.forEach(b=>b.setAttribute('opacity',1)));
  return svg;
}

function niceBounds(minv, maxv){
  // 0 을 항상 포함하고 보기 좋은 min/max 로 확장
  minv=Math.min(0,minv); maxv=Math.max(0,maxv);
  if(minv===maxv){ maxv=1; }
  const span=maxv-minv||1;
  const pad=span*0.12;
  return {lo:minv-(minv<0?pad:0), hi:maxv+pad};
}

function groupedBar(series, opts){
  // series:[{period, expYoy, impYoy}] YoY 두 계열. null(앞 12개월) 구간은 잘라낸다.
  series=series.filter(d=>d.expYoy!=null || d.impYoy!=null);
  if(!series.length){ const s=document.createElementNS(SVGNS,'svg'); s.setAttribute('viewBox','0 0 460 120');
    svgAdd(s,'text',{x:230,y:60,'text-anchor':'middle',class:'svg-tip'}).textContent='전년동월 데이터가 아직 없습니다';
    return s; }
  const W=opts.w||460, H=opts.h||288, m={t:16,r:14,b:42,l:52};
  const iw=W-m.l-m.r, ih=H-m.t-m.b;
  const all=[]; series.forEach(d=>{ if(d.expYoy!=null)all.push(d.expYoy); if(d.impYoy!=null)all.push(d.impYoy);});
  const {lo,hi}=niceBounds(Math.min(...all),Math.max(...all));
  const n=series.length, step=iw/n;
  const svg=document.createElementNS(SVGNS,'svg');
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`); svg.setAttribute('preserveAspectRatio','xMidYMid meet');
  const add=(tag,at)=>svgAdd(svg,tag,at);
  const Y=v=> m.t + ih - ((v-lo)/(hi-lo))*ih; const zeroY=Y(0);
  const cxOf=i=> m.l+step*i+step/2;
  const axY=H-m.b+24;
  for(let g=0;g<=4;g++){ const v=lo+(hi-lo)*g/4,y=Y(v);
    add('line',{x1:m.l,y1:y,x2:W-m.r,y2:y,stroke:'#273149','stroke-width':1});
    const t=add('text',{x:m.l-8,y:y+3.5,'text-anchor':'end'});t.setAttribute('class','svg-tip');t.textContent=v.toFixed(0)+'%';
  }
  add('line',{x1:m.l,y1:zeroY,x2:W-m.r,y2:zeroY,stroke:'#4a5675','stroke-width':1.4});
  const bw=Math.max(1.5, Math.min(9, step*0.34));
  series.forEach((d,i)=>{
    const cx=cxOf(i);
    [['expYoy','#4a90ff',-1],['impYoy','#ff5c6c',1]].forEach(([f,c,s])=>{
      const v=d[f]; if(v==null)return;
      const y=Y(v),h=Math.abs(y-zeroY);
      add('rect',{x:cx+(s*bw/2)-(bw/2)+(s*0.6),y:Math.min(y,zeroY),width:bw,height:Math.max(1,h),fill:c,rx:1.5});
    });
    // 간격 안 맞는 좌측 연도는 생략: 1월 경계만 연도 라벨, 7월은 옅은 눈금
    const mo=d.period.slice(4);
    if(mo==='01'){const t=add('text',{x:cx,y:axY,'text-anchor':'middle'});t.setAttribute('class','svg-ax');t.textContent=d.period.slice(0,4);}
    else if(mo==='07'){const t=add('text',{x:cx,y:axY,'text-anchor':'middle'});t.setAttribute('class','svg-mo');t.textContent='7월';}
  });
  // hover
  attachHover(svg,{m,iw,ih,W,H,n,X:cxOf,onIndex:(i,markG)=>{
    const d=series[i];
    svgAdd(markG,'rect',{x:cxOf(i)-step/2,y:m.t,width:step,height:ih,fill:'#ffffff',opacity:0.04});
    let rows='';
    if(d.expYoy!=null) rows+=`<div class="tr"><span class="dot" style="background:#4a90ff"></span>수출 YoY<b class="${d.expYoy>=0?'pos':'neg'}">${fmtPct(d.expYoy)}</b></div>`;
    if(d.impYoy!=null) rows+=`<div class="tr"><span class="dot" style="background:#ff5c6c"></span>수입 YoY<b class="${d.impYoy>=0?'pos':'neg'}">${fmtPct(d.impYoy)}</b></div>`;
    const yF = d.expYoy!=null ? Y(d.expYoy) : (d.impYoy!=null?Y(d.impYoy):null);
    const yB = d.expYoy!=null ? (d.expYoy>=0?'+':'')+d.expYoy.toFixed(1)+'%' : null;
    return {html:`<div class="th">${ymLong(d.period)}</div>${rows}`, yFocus:yF, xBadge:ymLabel(d.period), yBadge:yB};
  }});
  return svg;
}

// ---------- 렌더 ----------
function renderBreadcrumb(names){
  const bc=document.getElementById('breadcrumb'); bc.innerHTML='';
  const home=el('div',{class:'crumb'+(state.path.length===0?' active':'')},['전체 (HS 2자리)']);
  home.onclick=()=>{ state.path=[]; route(); };
  bc.appendChild(home);
  state.path.forEach((code,idx)=>{
    bc.appendChild(el('span',{class:'sep'},['▸']));
    const nm=(names[idx]&&names[idx][code])?names[idx][code]:'';
    const active=idx===state.path.length-1;
    const c=el('div',{class:'crumb'+(active?' active':''),title:'HS '+code+' '+nm},['HS '+code+(nm?('  '+nm):'')]);
    if(!active) c.onclick=()=>{ state.path=state.path.slice(0,idx+1); route(); };
    bc.appendChild(c);
  });
}

let sortState={col:'exp_dlr',dir:-1};
function renderTable(data, names){
  const app=document.getElementById('app');
  const level=(state.path.length+1)*2; // 다음 레벨 (2/4/6)
  const canDrill=level<=6;
  const panel=el('div',{class:'panel'});
  const title = state.path.length===0 ? 'HS 2자리 — 수출입 금액 · 증감률'
    : ('하위 HS '+level+'자리 — 수출입 금액 · 증감률');
  panel.appendChild(el('h2',{},[title]));
  const wrap=el('div',{class:'tablewrap'});
  const tbl=el('table');
  const thead=el('thead');
  const trh=el('tr');
  const cols=[['code','HS코드'],['name','품목명'],['exp_dlr','수출(USD)'],['imp_dlr','수입(USD)'],['bal','무역수지'],
    ['exp_yoy','수출 YoY'],['exp_qoq','수출 QoQ'],['imp_yoy','수입 YoY'],['imp_qoq','수입 QoQ']];
  cols.forEach(([k,label])=>{
    const th=el('th',{},[label + (sortState.col===k?(sortState.dir<0?' ▼':' ▲'):'')]);
    th.onclick=()=>{ if(sortState.col===k)sortState.dir*=-1; else {sortState.col=k;sortState.dir=-1;} panel.remove(); renderTable(data,names); };
    trh.appendChild(th);
  });
  thead.appendChild(trh); tbl.appendChild(thead);
  const tb=el('tbody');
  const rows=[...data].sort((a,b)=>{
    let x=a[sortState.col], y=b[sortState.col];
    if(sortState.col==='code'||sortState.col==='name'){
      x=sortState.col==='name'?(names.cur[a.code]||''):a.code;
      y=sortState.col==='name'?(names.cur[b.code]||''):b.code;
      return x<y?sortState.dir:x>y?-sortState.dir:0;
    }
    x=(x==null?-1e18:x); y=(y==null?-1e18:y);
    return (x-y)*sortState.dir;
  });
  function pctCell(v){
    const td=el('td',{class:'cell-pct '+(v==null?'':(v>=0?'pos':'neg'))},[fmtPct(v)]);
    return td;
  }
  rows.forEach(r=>{
    const tr=el('tr',{class:canDrill?'row':'leaf'});
    tr.appendChild(el('td',{class:'code'},[r.code]));
    tr.appendChild(el('td',{class:'name',title:names.cur[r.code]||''},[names.cur[r.code]||'']));
    tr.appendChild(el('td',{},[fmtUSD(r.exp_dlr)]));
    tr.appendChild(el('td',{},[fmtUSD(r.imp_dlr)]));
    tr.appendChild(el('td',{class:cls(r.bal)},[fmtUSD(r.bal)]));
    for(const key of ['exp_yoy','exp_qoq','imp_yoy','imp_qoq']) tr.appendChild(pctCell(r[key]));
    if(canDrill) tr.onclick=()=>{ state.path.push(r.code); route(); };
    tb.appendChild(tr);
  });
  tbl.appendChild(tb); wrap.appendChild(tbl); panel.appendChild(wrap);
  if(canDrill) panel.appendChild(el('div',{class:'hint'},['행을 클릭하면 하위 품목으로 들어갑니다. · YoY=전년동월, QoQ=분기 누적액의 전분기 대비 (상승 빨강/하락 파랑)']));
  app.appendChild(panel);
}

function renderDetail(detail){
  const app=document.getElementById('app');
  const s=detail.series, prefix=detail.prefix, level=detail.level;
  const nm=detail.name||'';
  // KPI
  const panel=el('div',{class:'panel'});
  panel.appendChild(el('h2',{},['📊 HS '+prefix+(nm?('  ·  '+nm):'')+'  ('+level+'자리)']));
  const kp=el('div',{class:'kpis'});
  const last=s.length?s[s.length-1]:{exp_dlr:0,imp_dlr:0};
  const expYoy=detail.expYoy.length?detail.expYoy[detail.expYoy.length-1].yoy:null;
  const impYoy=detail.impYoy.length?detail.impYoy[detail.impYoy.length-1].yoy:null;
  const qExp=detail.qExp.length?detail.qExp[detail.qExp.length-1].qoq:null;
  function kpi(label,val,sub,subcls){
    const d=el('div',{class:'kpi'});
    d.appendChild(el('div',{class:'label'},[label]));
    d.appendChild(el('div',{class:'val'},[val]));
    if(sub!==undefined&&sub!==null) d.appendChild(el('div',{class:'sub '+(subcls||'')},[sub]));
    return d;
  }
  kp.appendChild(kpi('수출 (최근월)',fmtUSD(last.exp_dlr), expYoy!=null?fmtPct(expYoy)+' YoY':null, expYoy>=0?'pos':'neg'));
  kp.appendChild(kpi('수입 (최근월)',fmtUSD(last.imp_dlr), impYoy!=null?fmtPct(impYoy)+' YoY':null, impYoy>=0?'pos':'neg'));
  kp.appendChild(kpi('무역수지 (최근월)',fmtUSD(last.exp_dlr-last.imp_dlr), null));
  kp.appendChild(kpi('수출 QoQ (최근분기)', qExp!=null?fmtPct(qExp):'-', null, qExp>=0?'pos':'neg'));
  panel.appendChild(kp);
  // 월간 추이
  const legend=el('div',{class:'legend'},[]);
  legend.innerHTML='<span><span class="dot" style="background:#4a90ff"></span>수출(USD)</span>'+
                   '<span><span class="dot" style="background:#ff5c6c"></span>수입(USD)</span>';
  panel.appendChild(el('h2',{},['월간 수출·수입 추이 (최근 5개년)']));
  panel.appendChild(legend);
  panel.appendChild(lineChart(s,{keys:[{field:'exp_dlr',color:'#4a90ff',name:'수출'},{field:'imp_dlr',color:'#ff5c6c',name:'수입'}]}));
  app.appendChild(panel);

  // YoY / QoQ 두 패널
  const row=el('div',{class:'chart-row'});
  const p1=el('div',{class:'panel'});
  p1.appendChild(el('h2',{},['전년동월 대비 증감률 (YoY %)']));
  const lg=el('div',{class:'legend'}); lg.innerHTML='<span><span class="dot" style="background:#4a90ff"></span>수출</span><span><span class="dot" style="background:#ff5c6c"></span>수입</span>';
  p1.appendChild(lg);
  const merged=detail.expYoy.map((d,i)=>({period:d.period,expYoy:d.yoy,impYoy:detail.impYoy[i]?detail.impYoy[i].yoy:null}));
  p1.appendChild(groupedBar(merged,{}));
  row.appendChild(p1);
  const p2=el('div',{class:'panel'});
  p2.appendChild(el('h2',{},['전분기 대비 증감률 (수출 QoQ %)']));
  const lg2=el('div',{class:'legend'}); lg2.innerHTML=`<span><span class="dot" style="background:${UP}"></span>상승</span><span><span class="dot" style="background:${DOWN}"></span>하락</span>`;
  p2.appendChild(lg2);
  p2.appendChild(barChart(detail.qExp.map(d=>({label:d.label,value:d.qoq})),{}));
  row.appendChild(p2);
  app.appendChild(row);

  // 관련 기업
  renderCompanies(prefix, level, detail.companies);
}

function renderCompanies(prefix, level, companies){
  const app=document.getElementById('app');
  const panel=el('div',{class:'panel companies'});
  panel.appendChild(el('h2',{},['🏢 관련 기업']));
  if(!STATIC){
    const form=el('form');
    const co=el('input',{type:'text',placeholder:'기업명',style:'flex:1;min-width:140px'});
    const nt=el('input',{type:'text',placeholder:'메모 (선택)',style:'flex:2;min-width:160px'});
    const btn=el('button',{type:'submit'},['추가']);
    const status=el('div',{class:'empty',role:'status'});
    form.appendChild(co); form.appendChild(nt); form.appendChild(btn);
    form.onsubmit=async(e)=>{ e.preventDefault(); if(!co.value.trim())return;
      btn.disabled=true;
      try {
        await apiPost('/api/company/add',{hs_code:prefix,hs_level:level,company:co.value.trim(),note:nt.value.trim()});
        await route();
      } catch(error) { status.textContent=error.message; }
      finally { btn.disabled=false; }
    };
    panel.appendChild(form);
    panel.appendChild(status);
  }
  if(!companies||!companies.length){
    panel.appendChild(el('div',{class:'empty'},['등록된 관련 기업이 없습니다.']));
  } else {
    companies.forEach(c=>{
      const row=el('div',{class:'co'});
      row.appendChild(el('span',{class:'nm'},[c.company]));
      row.appendChild(el('span',{class:'nt'},[c.note||'']));
      if(!STATIC){
        const d=el('button',{class:'del'},['삭제']);
        d.onclick=async()=>{
          d.disabled=true;
          try { await apiPost('/api/company/delete',{id:c.id}); await route(); }
          catch(error) { d.disabled=false; row.appendChild(el('span',{role:'alert'},[error.message])); }
        };
        row.appendChild(d);
      }
      panel.appendChild(row);
    });
  }
  app.appendChild(panel);
}

// ---------- 첫 화면 개요 ----------
function pctChip(label, v){
  const c = v==null ? '' : (v>=0?'up':'down');
  return `<span class="chip-pct ${c}"><span class="k">${label}</span>${fmtPct(v)}</span>`;
}
function renderOverview(ov){
  const app=document.getElementById('app');
  const t=ov.totals||{};
  // 히어로 밴드
  const hero=el('div',{class:'hero'});
  const pd=ov.period||LATEST;
  hero.appendChild(el('div',{class:'htitle',html:`기준월 <b>${pd.slice(0,4)}.${pd.slice(4)}</b> · 전체 품목(HS 2자리 ${t.hs2_count||0}개) 종합`}));
  const hg=el('div',{class:'hero-grid'});
  function card(label, color, val, chips){
    return el('div',{class:'hero-card',html:
      `<div class="hc-label"><span class="ic" style="background:${color}"></span>${label}</div>`+
      `<div class="hc-val">${val}</div>`+
      `<div class="hc-chips">${chips}</div>`});
  }
  hg.appendChild(card('총 수출 (최근월)', C_EXP, fmtUSD(t.exp_dlr),
    pctChip('YoY',t.exp_yoy)+pctChip('QoQ',t.exp_qoq)));
  hg.appendChild(card('총 수입 (최근월)', C_IMP, fmtUSD(t.imp_dlr),
    pctChip('YoY',t.imp_yoy)+pctChip('QoQ',t.imp_qoq)));
  const balCls = (t.bal||0)>=0?'up':'down';
  hg.appendChild(card('무역수지 (최근월)', '#5ad1a8',
    `<span class="${(t.bal||0)>=0?'pos':'neg'}">${fmtUSD(t.bal)}</span>`,
    `<span class="chip-pct ${balCls}">${(t.bal||0)>=0?'흑자':'적자'}</span>`));
  hero.appendChild(hg);
  app.appendChild(hero);

  // 전체 추이 + TOP HS2 (2열)
  const row=el('div',{class:'ov-row2'});
  const p1=el('div',{class:'panel'});
  p1.appendChild(el('h2',{},['전체 수출·수입 월간 추이 (최근 5개년)']));
  const lg=el('div',{class:'legend'});
  lg.innerHTML=`<span><span class="dot" style="background:${C_EXP}"></span>수출</span><span><span class="dot" style="background:${C_IMP}"></span>수입</span>`;
  p1.appendChild(lg);
  p1.appendChild(lineChart(ov.series,{keys:[{field:'exp_dlr',color:C_EXP,name:'수출'},{field:'imp_dlr',color:C_IMP,name:'수입'}],h:300}));
  row.appendChild(p1);

  const p2=el('div',{class:'panel'});
  p2.appendChild(el('h2',{},['수출 상위 품목 TOP 10 (HS 2자리)']));
  p2.appendChild(topBarChart(ov.hs2.slice(0,10)));
  row.appendChild(p2);
  app.appendChild(row);
}

// 가로 막대 랭킹 차트 (SVG)
function topBarChart(rows){
  const W=460, rowH=26, m={t:6,r:14,b:6,l:46};
  const H=m.t+m.b+rows.length*rowH;
  const maxv=Math.max(1,...rows.map(r=>r.exp_dlr));
  const svg=document.createElementNS(SVGNS,'svg');
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`); svg.setAttribute('preserveAspectRatio','xMidYMid meet');
  const iw=W-m.l-m.r;
  rows.forEach((r,i)=>{
    const y=m.t+i*rowH, bw=Math.max(2,(r.exp_dlr/maxv)*iw);
    const g=svgAdd(svg,'g',{});
    svgAdd(g,'text',{x:m.l-6,y:y+rowH/2+4,'text-anchor':'end',class:'svg-ax'}).textContent=r.code;
    svgAdd(g,'rect',{x:m.l,y:y+4,width:iw,height:rowH-11,rx:4,fill:'#0e1626'});
    const grad=svgAdd(g,'rect',{x:m.l,y:y+4,width:bw,height:rowH-11,rx:4,fill:'#4a90ff'});
    svgAdd(g,'text',{x:m.l+8,y:y+rowH/2+4,class:'svg-val'}).textContent=(r.name||'').slice(0,10);
    svgAdd(g,'text',{x:W-m.r,y:y+rowH/2+4,'text-anchor':'end',class:'svg-val'}).textContent=fmtUSD(r.exp_dlr);
    // hover 툴팁
    const hit=svgAdd(g,'rect',{x:0,y:y,width:W,height:rowH,fill:'transparent'});
    hit.addEventListener('mousemove',e=>{ grad.setAttribute('fill','#5ad1a8');
      showTip(`<div class="th">HS ${esc(r.code)} ${esc(r.name)}</div>`+
        `<div class="tr"><span class="dot" style="background:${C_EXP}"></span>수출<b>${fmtUSD(r.exp_dlr)}</b></div>`+
        `<div class="tr"><span class="dot" style="background:${C_IMP}"></span>수입<b>${fmtUSD(r.imp_dlr)}</b></div>`+
        `<div class="tr sub">YoY<b class="${r.exp_yoy>=0?'pos':'neg'}">${fmtPct(r.exp_yoy)}</b></div>`+
        `<div class="tr sub">QoQ<b class="${r.exp_qoq>=0?'pos':'neg'}">${fmtPct(r.exp_qoq)}</b></div>`, e.clientX, e.clientY); });
    hit.addEventListener('mouseleave',()=>{ grad.setAttribute('fill','#4a90ff'); hideTip(); });
    hit.style&&(hit.style.cursor='pointer');
  });
  return svg;
}

// ---------- 라우팅 ----------
let routeVersion=0;
async function route(){
  const version=++routeVersion;
  try { await renderRoute(version); }
  catch(error) {
    if(version!==routeVersion) return;
    const app=document.getElementById('app');
    app.replaceChildren(el('div',{class:'panel empty',role:'alert'},[error.message]));
    const retry=el('button',{type:'button'},['다시 불러오기']); retry.onclick=()=>route(); app.append(retry);
  }
}
async function renderRoute(version){
  const app=document.getElementById('app'); app.innerHTML='';
  app.appendChild(el('div',{class:'empty',role:'status'},['수출입 자료를 불러오는 중...']));
  const names=await loadNames();
  if(version!==routeVersion) return;
  renderBreadcrumb(names.levels);

  if(state.path.length===0){
    // 첫 화면: 개요(히어로+차트) + YoY/QoQ 포함 HS2 표
    const ov=await api('/api/overview');
    if(version!==routeVersion) return;
    app.replaceChildren();
    if(!ov?.series?.length){
      app.appendChild(el('div',{class:'panel empty'},['저장된 수출입 자료가 없습니다. 데이터 업데이트를 눌러 관세청 자료를 수집하세요.']));
      return;
    }
    if(ov){ renderOverview(ov);
      const data=ov.hs2;
      names.cur=names.levels[0]||{};
      renderTable(data, names);
    }
    window.scrollTo({top:0,behavior:'smooth'});
    return;
  }

  // 상세 (현재 선택된 가장 깊은 코드)
  const prefix=state.path[state.path.length-1];
  const detail=await api('/api/detail?code='+prefix);
  if(version!==routeVersion) return;
  app.replaceChildren();
  if(detail){ renderDetail(detail); }
  else if(STATIC){
    const p=el('div',{class:'panel'});
    p.appendChild(el('h2',{},['📊 HS '+prefix]));
    p.appendChild(el('div',{class:'empty'},['정적 리포트에서는 HS 6자리 상세 차트를 포함하지 않습니다. 서버 모드(python run.py)에서 확인하세요. 아래 하위 품목 표는 사용할 수 있습니다.']));
    app.appendChild(p);
  }
  if(state.path.length<3){
    const level=(state.path.length+1)*2;
    const data=await api('/api/level?code='+encodeURIComponent(prefix)+'&level='+level);
    if(version!==routeVersion) return;
    names.cur=names.levels[state.path.length]||{};
    renderTable(data, names);
  }
  window.scrollTo({top:0,behavior:'smooth'});
}

let _namesCache=null;
async function loadNames(){
  if(_namesCache) return _namesCache;
  const levels=await Promise.all([api('/api/names?level=2'),api('/api/names?level=4'),api('/api/names?level=6')]);
  _namesCache={levels,cur:levels[0]};
  return _namesCache;
}

// ---------- 데이터 업데이트 버튼 ----------
function setupUpdate(){
  const btn=document.getElementById('update-btn');
  const box=document.getElementById('update-status');
  if(!btn) return;
  if(STATIC){ btn.style.display='none'; return; }
  function button(state, label){ window.FinanceUI.update(btn,state,label); }
  function showStatus(cls, html){ box.className='update-status '+(cls||''); box.style.display='flex'; box.innerHTML=html; }
  async function poll(){
    try {
      const st=await api('/api/collect/status');
      const pct = st.total? Math.min(100,Math.round((st.index/st.total)*100)) : (st.phase==='detect'?5:0);
      if(st.running){
        button('running','수집 중...');
        showStatus('', `<div class="bar"><i style="width:${pct}%"></i></div><span class="msg">${esc(st.message||'수집 중...')} (${st.index}/${st.total||'?'})</span>`);
        setTimeout(poll, 900);
      } else if(st.phase==='error'){
        showStatus('err', `<span class="msg">업데이트 실패: ${esc(st.message||st.error)}</span>`);
        button('error','다시 업데이트');
      } else if(st.phase==='done' && st.summary){
        const s=st.summary;
        showStatus('done', `<span class="msg">업데이트 완료 · 기준월 ${esc(s.latest_month)} · ${s.months_fetched}개월 수집 · 총 ${s.total_rows.toLocaleString()}행</span> <button class="ghost" id="reload-btn">결과 새로고침</button>`);
        button('success','데이터 업데이트');
        const rb=document.getElementById('reload-btn'); if(rb) rb.onclick=()=>location.reload();
      } else { button('idle','데이터 업데이트'); }
    } catch(error) {
      showStatus('err', `<span class="msg">${esc(error.message)} 잠시 후 상태를 다시 확인합니다.</span>`);
      setTimeout(poll, 3000);
    }
  }
  btn.onclick=async()=>{
    button('running','수집 중...');
    try {
      await apiPost('/api/collect',{});
      showStatus('', `<div class="bar"><i style="width:3%"></i></div><span class="msg">수집 시작...</span>`);
      poll();
    } catch(error) {
      showStatus('err',`<span class="msg">${esc(error.message)}</span>`);
      button('error','다시 업데이트');
    }
  };
  poll();
}

setupUpdate();
route();
"""


def build_static(conn, meta: dict) -> str:
    """서버 없이 모든 데이터를 임베드한 단일 HTML 문자열 생성.

    모든 시계열을 레벨당 1쿼리로 일괄 계산한다(2/4/6 → 3쿼리).
    관련기업 입력/삭제는 정적 모드에서 비활성화된다.
    """
    from . import db

    latest = meta.get("latest_month") or db.latest_month(conn)
    meta = dict(meta)
    meta["latest_month"] = latest or ""

    embedded: dict = {}
    names = {}
    for lv in (2, 4, 6):
        names[lv] = db.representative_names(conn, lv)
        embedded[f"/api/names?level={lv}"] = names[lv]

    embedded["/api/overview"] = db.overview(conn)
    companies = db.all_companies(conn)

    # 레벨별 전체 시계열(일괄) → 집계표 + 상세 임베드.
    # 상세(시계열)는 용량 문제로 HS2/HS4 까지만 임베드한다.
    # HS6 은 집계표(드릴다운 표)만 제공하며, 상세는 서버 모드에서 확인.
    DETAIL_MAX_LEVEL = 4
    for lv in (2, 4, 6):
        series_map = db.all_series_by_level(conn, lv)
        name_map = names[lv]
        groups: dict[str, list] = {}
        for code, series in series_map.items():
            parent = "" if lv == 2 else code[: lv - 2]
            rows = groups.setdefault(parent, [])
            metrics = db.period_metrics(series, latest)
            if metrics is not None:
                rows.append({"code": code, **metrics})
            if lv <= DETAIL_MAX_LEVEL:
                embedded["/api/detail?code=" + code] = {
                    "prefix": code,
                    "level": lv,
                    "name": name_map.get(code, ""),
                    "series": series,
                    "expYoy": db.compute_yoy(series, "exp_dlr"),
                    "impYoy": db.compute_yoy(series, "imp_dlr"),
                    "qExp": db.compute_quarterly(series, "exp_dlr"),
                    "companies": companies.get(code, []),
                }
        for parent, rows in groups.items():
            rows.sort(key=lambda r: r["exp_dlr"], reverse=True)
            embedded[f"/api/level?code={parent}&level={lv}"] = rows

    return page_html(meta, embedded=embedded)
