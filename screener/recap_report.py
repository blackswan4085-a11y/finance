"""주간 시장 Recap HTML 렌더링. 서버가 이 HTML을 /recap 에서 서빙."""
from __future__ import annotations

import html
from typing import Dict, List, Optional

from .weekly import previous_week_friday
from .ui import shared_ui


def _fmt_price(v: Optional[float]) -> str:
    if v is None:
        return "-"
    return f"{v:,.2f}"


def _pct_cell(v: Optional[float]) -> str:
    """등락률 셀: 상승=빨강, 하락=파랑(한국식), N/A=회색."""
    if v is None:
        return '<td class="pct na">-</td>'
    cls = "up" if v >= 0 else "down"
    return f'<td class="pct {cls}">{v:+.1f}%</td>'


# 그룹 아이콘(국기/상징) — 어떤 국가/카테고리인지 즉시 인지하도록
GROUP_ICON = {
    "한국": "🇰🇷", "미국": "🇺🇸", "일본": "🇯🇵", "중화권": "🇨🇳", "인도": "🇮🇳",
    "독일": "🇩🇪", "영국": "🇬🇧", "프랑스": "🇫🇷", "중국": "🇨🇳",
    "유럽": "🇪🇺", "북미": "🇨🇦", "아시아": "🌏", "글로벌": "🌐", "지수": "📊",
    "원화": "🇰🇷", "귀금속": "🥇", "산업금속": "🔩", "에너지": "🛢️", "농산물": "🌾",
}


def _grp_cell(group: str, rowspan: int) -> str:
    icon = GROUP_ICON.get(group, "")
    label = f"{icon} {html.escape(group)}" if icon else html.escape(group)
    return (f'<td class="grp" rowspan="{rowspan}">'
            f'<span class="glabel">{label}</span></td>')


def _group_rows(rows: List[Dict]) -> str:
    out = []
    prev_group = None
    group_counts: Dict[str, int] = {}
    for r in rows:
        group_counts[r["group"]] = group_counts.get(r["group"], 0) + 1

    for r in rows:
        tds = []
        is_start = r["group"] != prev_group
        if is_start:
            tds.append(_grp_cell(r["group"], group_counts[r["group"]]))
            prev_group = r["group"]
        name = html.escape(r["name"])
        date = html.escape("업데이트 필요" if r.get("pending") else "조회 실패" if r.get("error") else str(r.get("date", "-")))
        tds.append(f'<td class="name">{name}<span class="dt">{date}</span></td>')
        tds.append(f'<td class="price">{_fmt_price(r.get("price"))}</td>')
        tds.append(_pct_cell(r.get("chg_1w")).replace('class="pct ', 'class="pct weekly '))
        tds.append(_pct_cell(r.get("chg_1m")))
        tds.append(_pct_cell(r.get("chg_3m")))
        tds.append(_pct_cell(r.get("chg_ytd")))
        tds.append(f'<td class="spark-cell">{r.get("spark", "")}</td>')
        tds.append(_pct_cell(r.get("from_52w_high")))
        tr_cls = ' class="grp-start"' if is_start else ""
        out.append(f"<tr{tr_cls}>" + "".join(tds) + "</tr>")
    return "\n".join(out)


def _delta_cell(v: Optional[float], unit: str) -> str:
    """금리(bp)/환율(%) 등락 셀."""
    if v is None:
        return '<td class="pct na">-</td>'
    cls = "up" if v >= 0 else "down"
    txt = f"{v:+.0f}bp" if unit == "bp" else f"{v:+.2f}%"
    return f'<td class="pct {cls}">{txt}</td>'


def _ratefx_rows(rows: List[Dict], val_fmt: str) -> str:
    """금리/환율 표 본문. val_fmt: 가격 소수 자리수 포맷(예: '{:.3f}')."""
    out = []
    prev_group = None
    group_counts: Dict[str, int] = {}
    for r in rows:
        group_counts[r["group"]] = group_counts.get(r["group"], 0) + 1
    for r in rows:
        tds = []
        is_start = r["group"] != prev_group
        if is_start:
            tds.append(_grp_cell(r["group"], group_counts[r["group"]]))
            prev_group = r["group"]
        unit = r.get("unit", "")
        name = html.escape(r["name"])
        date = html.escape("업데이트 필요" if r.get("pending") else "조회 실패" if r.get("error") else str(r.get("date", "-")))
        tds.append(f'<td class="name">{name}<span class="dt">{date}</span></td>')
        price = r.get("price")
        pstr = val_fmt.format(price) if price is not None else "-"
        tds.append(f'<td class="price">{pstr}</td>')
        tds.append(_delta_cell(r.get("chg_1w"), unit).replace('class="pct ', 'class="pct weekly '))
        tds.append(_delta_cell(r.get("chg_1m"), unit))
        tds.append(_delta_cell(r.get("chg_3m"), unit))
        tds.append(f'<td class="spark-cell">{r.get("spark", "")}</td>')
        tr_cls = ' class="grp-start"' if is_start else ""
        out.append(f"<tr{tr_cls}>" + "".join(tds) + "</tr>")
    return "\n".join(out)


def _commentary_block(commentary: Dict, title: str) -> str:
    """분야별 AI 코멘터리 박스 HTML."""
    text = html.escape((commentary or {}).get("text", "") or "")
    ok = (commentary or {}).get("ok", False)
    paras = "".join(f"<p>{p}</p>" for p in text.split("\n") if p.strip()) or \
        "<p class='muted'>아직 코멘터리가 없습니다. [업데이트]를 눌러 생성하세요.</p>"
    badge = "" if ok else '<span class="warn-badge">미생성</span>'
    return (
        f'<div class="cmt">'
        f'<div class="cmt-title">{html.escape(title)}{badge}</div>'
        f'<div class="cmt-body" tabindex="0" role="region" aria-label="{html.escape(title)}">{paras}</div></div>'
    )



def _overview_card(title: str, panel: str, rows: List[Dict], symbols: List[str]) -> str:
    """대표 지표만 보여주는 종합 화면 카드. 전체 목록은 분야 탭에서 표시."""
    by_symbol = {row.get("symbol"): row for row in rows}
    selected = [by_symbol[symbol] for symbol in symbols if symbol in by_symbol]
    body = []
    for row in selected:
        date = ("업데이트 필요" if row.get("pending") else "조회 실패" if row.get("error")
                else str(row.get("date", "-")))
        name = html.escape(row.get("name", ""))
        cells = (f'<td class="name">{name}<span class="dt">{html.escape(date)}</span></td>'
                 + _delta_cell(row.get("chg_1w"), row.get("unit", "%")).replace(
                     'class="pct ', 'class="pct weekly ')
                 + _delta_cell(row.get("chg_1m"), row.get("unit", "%")))
        body.append(f"<tr>{cells}</tr>")
    if not body:
        body.append('<tr><td colspan="3" class="empty">업데이트로 데이터를 수집하세요.</td></tr>')
    return (f'<div class="overview-card"><a class="overview-card-title" href="#{panel}">'
            f'{html.escape(title)}<span>전체 보기 →</span></a>'
            '<table><thead><tr><th style="text-align:left">대표 지표</th>'
            '<th class="weekly">1W</th><th>1M</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def render_recap_html(payload: Optional[Dict], server_mode: bool = True) -> str:
    rows = payload.get("rows", []) if payload else []
    commodities = payload.get("commodities", []) if payload else []
    rates = payload.get("rates", []) if payload else []
    fx = payload.get("fx", []) if payload else []
    comm_overview = payload.get("commentary_overview", {}) if payload else {}
    comm_index = payload.get("commentary_index", {}) if payload else {}
    comm_cmdty = payload.get("commentary_commodity", {}) if payload else {}
    comm_ratefx = payload.get("commentary_ratefx", {}) if payload else {}
    generated_at = payload.get("generated_at", "아직 생성되지 않음") if payload else "아직 생성되지 않음"
    result_asof = payload.get("asof_date", "미기록") if payload else "없음"
    target_asof = previous_week_friday().isoformat()
    catalog_warning = html.escape(payload.get("catalog_warning", "")) if payload else ""

    table_body = _group_rows(rows) if rows else (
        '<tr><td colspan="9" class="empty">아직 데이터가 없습니다. '
        '[업데이트] 버튼을 눌러 생성하세요.</td></tr>'
    )
    commodity_body = _group_rows(commodities) if commodities else (
        '<tr><td colspan="9" class="empty">아직 원자재 데이터가 없습니다. '
        '[업데이트] 버튼을 눌러 생성하세요.</td></tr>'
    )
    rates_body = _ratefx_rows(rates, "{:.3f}") if rates else (
        '<tr><td colspan="7" class="empty">아직 금리 데이터가 없습니다.</td></tr>'
    )
    fx_body = _ratefx_rows(fx, "{:,.2f}") if fx else (
        '<tr><td colspan="7" class="empty">아직 환율 데이터가 없습니다.</td></tr>'
    )

    cmt_overview = _commentary_block(comm_overview, "종합 AI 코멘터리")
    overview_cards = "".join([
        _overview_card("주식 지수 · %", "indices", rows,
                       ["^KS11", "^KQ11", "^GSPC", "^IXIC", "^RUT", "^STOXX50E"]),
        _overview_card("원자재 · %", "commodities", commodities,
                       ["GC=F", "SI=F", "HG=F", "CL=F", "NG=F", "ZW=F"]),
        _overview_card("국채 금리 · bp", "ratefx", rates,
                       ["US2YT=RR", "US10YT=RR", "KR2YT=RR", "KR10YT=RR",
                        "DE10YT=RR", "JP10YT=RR"]),
        _overview_card("환율 · %", "ratefx", fx,
                       [".DXY", "FX_USDKRW", "FX_JPYKRW", "FX_EURKRW", "FX_CNYKRW"]),
    ])
    cmt_index = _commentary_block(comm_index, "지수 AI 코멘터리")
    cmt_cmdty = _commentary_block(comm_cmdty, "원자재 AI 코멘터리")
    cmt_ratefx = _commentary_block(comm_ratefx, "금리·환율 AI 코멘터리")

    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>지난주 시장 Recap</title>
<style>
  :root {{ --bg:#0b1220; --panel:#131c2e; --panel2:#0f1726; --line:#243049;
           --txt:#e6edf7; --muted:#8b98ad; --up:#e5484d; --down:#3b82f6; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--txt);
          font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",sans-serif;
          font-size:14px; }}
  .wrap {{ max-width:980px; margin:0 auto; padding:24px 16px 60px; }}
  .topbar {{ display:flex; align-items:center; justify-content:space-between;
             gap:12px; margin-bottom:16px; }}
  h1 {{ font-size:20px; margin:0; letter-spacing:-.5px; }}
  .navbtn {{ background:#2563eb; color:#fff; text-decoration:none; border-radius:8px;
             padding:9px 16px; font-size:13px; font-weight:600; white-space:nowrap; }}
  .navbtn:hover {{ background:#1d4ed8; }}
  .section {{ background:var(--panel); border:1px solid var(--line);
              border-radius:12px; overflow:hidden; margin-bottom:20px; }}
  .section-head {{ background:#1b2740; padding:11px 16px; font-weight:700;
                   font-size:14px; border-bottom:1px solid var(--line);
                   display:flex; align-items:center; justify-content:space-between; }}
  .meta {{ font-size:12px; color:var(--muted); font-weight:400; }}
  table {{ width:100%; border-collapse:collapse; }}
  th, td {{ padding:9px 10px; text-align:right; border-bottom:1px solid var(--panel2);
            white-space:nowrap; }}
  thead th {{ color:var(--muted); font-weight:600; font-size:12px;
              background:var(--panel2); position:sticky; top:0; }}
  /* 그룹 셀: 국가/카테고리를 세로쓰기+강조색으로 명확히 구분 */
  td.grp {{ text-align:center; color:#cdd8ea; font-weight:800; font-size:13px;
            border-right:3px solid #3b4a66; background:#1b2740;
            vertical-align:middle; width:40px; letter-spacing:1px;
            border-bottom:2px solid var(--line) !important; }}
  td.grp .glabel {{ writing-mode:vertical-rl; text-orientation:upright;
            display:inline-block; padding:4px 0; }}
  /* 그룹의 첫 행 위쪽에 굵은 구분선 → 그룹 경계가 또렷 */
  tr.grp-start td {{ border-top:2px solid #32415c; }}
  td.name {{ text-align:left; font-weight:600; }}
  td.name .flag {{ margin-right:6px; }}
  td.name .dt {{ color:var(--muted); font-weight:400; font-size:11px; margin-left:6px; }}
  td.price {{ font-variant-numeric:tabular-nums; }}
  td.pct {{ font-variant-numeric:tabular-nums; font-weight:600; }}
  td.pct.up {{ color:var(--up); }}
  td.pct.down {{ color:var(--down); }}
  td.pct.na {{ color:var(--muted); }}
  td.spark-cell {{ text-align:center; width:130px; }}
  .spark {{ vertical-align:middle; }}
  td.empty {{ text-align:center; color:var(--muted); padding:30px; }}
  .cmt {{ padding:14px 18px 16px; line-height:1.7; background:#0f1a2e;
          border-top:1px solid var(--line); }}
  .cmt .cmt-title {{ font-weight:700; color:#8ab4ff; margin-bottom:8px; font-size:13px; }}
  .cmt p {{ margin:0 0 10px; color:#d4dcea; }}
  .cmt p:last-child {{ margin-bottom:0; }}
  .cmt p.muted {{ color:var(--muted); }}
  .btn {{ background:#2563eb; color:#fff; border:none; border-radius:8px;
          padding:8px 16px; font-size:13px; font-weight:600; cursor:pointer; }}
  .btn:hover {{ background:#1d4ed8; }}
  .btn:disabled {{ opacity:.6; cursor:not-allowed; }}
  .btn.ghost {{ background:transparent; border:1px solid var(--line); color:var(--muted); }}
  .controls {{ display:flex; gap:8px; align-items:center; }}
  .warn-badge {{ background:#5a2b2b; color:#ffb4b4; font-size:11px;
                 padding:2px 8px; border-radius:10px; margin-left:8px; }}
  #status {{ font-size:12px; color:var(--muted); }}
  .spin {{ display:inline-block; width:12px; height:12px; border:2px solid #ffffff55;
           border-top-color:#fff; border-radius:50%; animation:sp .7s linear infinite;
           vertical-align:-1px; margin-right:6px; }}
  @keyframes sp {{ to {{ transform:rotate(360deg); }} }}

  .wrap {{ max-width:1580px; height:100vh; height:100svh; min-height:480px; padding:16px 20px; display:flex; flex-direction:column; gap:12px; }}
  .page-header {{ flex:none; }}
  .topbar {{ margin:0; min-height:36px; }}
  .controls {{ flex-wrap:wrap; justify-content:flex-end; }}
  h1 {{ white-space:nowrap; }}
  .navbtn {{ padding:8px 12px; font-size:12px; background:var(--panel2); border:1px solid var(--line); color:#a5bbdb; }}
  .btn {{ padding:8px 12px; font-size:12px; }}
  #status {{ display:block; margin-top:6px; font-size:11px; line-height:1.5; }}
  .recap-tabs {{ display:flex; gap:6px; flex:none; border-bottom:1px solid var(--line); padding-bottom:8px; }}
  .recap-tab {{ display:flex; align-items:center; gap:8px; min-height:34px; border:1px solid transparent; border-radius:7px; padding:6px 15px; background:transparent; color:#91a2bb; font:inherit; font-weight:650; cursor:pointer; }}
  .recap-tab:hover {{ background:#16233a; color:#e6edf7; }}
  .recap-tab[aria-selected="true"] {{ background:#1b3153; color:#bcd5ff; border-color:#345685; }}
  .tab-count {{ font-size:10px; font-weight:500; color:#91a2bb; }}
  .recap-panels {{ flex:1; min-height:0; display:grid; }}
  .section {{ min-width:0; min-height:0; height:100%; margin:0; display:flex; flex-direction:column; }}
  .section-head {{ min-height:43px; flex:none; padding:10px 14px; background:#18243a; gap:12px; }}
  h2 {{ margin:0; font-size:14px; font-weight:700; }}
  .meta {{ font-size:11px; text-align:right; }}
  .section-body {{ display:grid; grid-template-columns:minmax(0,1fr) clamp(260px,27vw,380px); flex:1; min-height:0; gap:14px; padding:12px; }}
  .table-scroll {{ min-width:0; min-height:0; overflow:auto; border:1px solid var(--line); border-radius:8px; background:var(--panel2); scrollbar-width:thin; scrollbar-color:#415373 var(--panel2); }}
  table {{ min-width:630px; border-collapse:separate; border-spacing:0; font-size:12px; }}
  th,td {{ height:28px; padding:4px 6px; line-height:19px; border-bottom:1px solid #1c2940; }}
  thead th {{ height:30px; z-index:2; font-size:10px; background:#111c30; }}
  tbody tr:last-child td {{ border-bottom:0; }}
  tbody tr:hover td:not(.grp) {{ background:#17273f; }}
  td.grp {{ width:68px; padding:4px 6px; border-right:2px solid #354969; font-size:11px; letter-spacing:0; background:#1b2940; border-bottom:1px solid #354969!important; }}
  td.grp .glabel {{ writing-mode:horizontal-tb; text-orientation:mixed; padding:0; white-space:nowrap; }}
  tr.grp-start td {{ border-top:1px solid #354969; }}
  td.name .dt {{ margin-left:4px; font-size:9px; color:#788ca8; }}
  .weekly {{ background:#16243a; }}
  td.spark-cell {{ width:94px; padding:3px 6px; }}
  .spark {{ display:block; width:82px; height:20px; margin:0 auto; }}
  td.empty {{ white-space:normal; padding:32px 16px; }}
  .data-block th,.data-block td {{ height:24px; padding:2px 6px; font-size:12px; }}
  .data-block thead th {{ height:26px; font-size:10px; }}
  .data-block .spark {{ height:18px; }}
  .catalog-warning {{ color:#d5b678; font-size:11px; display:block; margin-top:3px; }}
  .catalog-warning:empty {{ display:none; }}
  .data-block+.data-block {{ border-top:1px solid #354969; }}
  .data-block-title {{ margin:0; padding:7px 12px; color:#bfcee5; font-size:12px; background:#142137; }}
  .cmt {{ display:flex; flex-direction:column; min-width:0; min-height:0; padding:0; margin:0; background:#0e192c; border:1px solid #2c3f5b; border-radius:8px; overflow:hidden; }}
  .cmt .cmt-title {{ flex:none; margin:0; padding:11px 14px; border-bottom:1px solid #263952; font-size:12px; }}
  .cmt-body {{ flex:1; min-height:0; overflow:auto; padding:13px 14px; font-size:12px; line-height:1.8; scrollbar-width:thin; scrollbar-color:#415373 #0e192c; overflow-wrap:anywhere; }}
  .cmt p {{ margin:0 0 13px; color:#c8d5e8; }}
  .warn-badge {{ font-size:10px; padding:1px 6px; border-radius:4px; }}
  [hidden] {{ display:none!important; }}
  button:focus-visible,a:focus-visible,[tabindex]:focus-visible {{ outline:2px solid #79a9ff; outline-offset:3px; }}
  @media(min-width:1250px) {{ th,td {{ height:28px; padding:4px 8px; }} table {{ font-size:13px; }} .cmt-body {{ font-size:13px; }} .spark {{ width:100px; }} td.spark-cell {{ width:116px; }} }}
  @media(max-width:899px) {{ .wrap {{ padding:12px; gap:10px; }} .section-body {{ grid-template-columns:minmax(0,1fr); grid-template-rows:minmax(0,1fr) minmax(140px,30%); gap:10px; padding:10px; }} .cmt .cmt-title {{ padding:8px 12px; }} .cmt-body {{ padding:10px 12px; }} }}
  @media(max-width:600px) {{ .wrap {{ padding:10px 8px; }} .topbar {{ align-items:flex-start; flex-wrap:wrap; gap:8px; }} h1 {{ font-size:18px; }} .controls {{ gap:6px; }} .navbtn,.btn {{ padding:6px 9px; font-size:11px; }} .recap-tabs {{ gap:4px; }} .recap-tab {{ flex:1; justify-content:center; padding:6px 7px; font-size:12px; }} .section-head {{ padding:9px 11px; }} .section-head .meta {{ max-width:50%; font-size:10px; }} .section-body {{ padding:8px; }} }}
  @media(max-height:720px) and (min-width:900px) {{ .wrap {{ padding-top:10px; padding-bottom:10px; gap:8px; }} th,td {{ height:24px; padding-top:2px; padding-bottom:2px; }} thead th {{ height:26px; }} .spark {{ height:18px; }} .cmt-body {{ line-height:1.7; font-size:12px; }} }}


  .overview-body {{ grid-template-columns:minmax(0,1fr) minmax(430px,1.05fr); }}
  .overview-body .cmt-title {{ font-size:14px; padding:14px 18px; }}
  .overview-body .cmt-body {{ font-size:14px; line-height:1.95; padding:18px; }}
  .overview-body .cmt p {{ margin-bottom:20px; }}
  .overview-summary {{ min-width:0; min-height:0; overflow:auto; scrollbar-width:thin; }}
  .overview-note {{ margin:0 0 10px; font-size:11px; color:var(--muted); line-height:1.6; }}
  .overview-cards {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }}
  .overview-card {{ min-width:0; border:1px solid var(--line); border-radius:8px; overflow:hidden; background:var(--panel2); align-self:start; }}
  .overview-card-title {{ display:flex; align-items:center; justify-content:space-between; gap:4px; padding:10px; color:#c4d7f4; text-decoration:none; background:#182740; font-size:12px; font-weight:650; }}
  .overview-card-title:hover {{ background:#203554; }}
  .overview-card-title span {{ font-size:9px; color:#829cbc; font-weight:400; }}
  .overview-card table {{ min-width:0; table-layout:fixed; font-size:11px; }}
  .overview-card th,.overview-card td {{ height:29px; padding:4px; font-size:11px; }}
  .overview-card thead th {{ height:26px; font-size:10px; position:static; }}
  .overview-card th:first-child {{ width:48%; }}
  .overview-card .name {{ white-space:normal; line-height:1.3; font-weight:500; padding-left:8px; }}
  .overview-card .dt {{ display:block; margin:2px 0 0; font-size:8px; }}
  .overview-card .empty {{ padding:20px 8px; }}
  @media(max-width:1100px) and (min-width:900px) {{ .overview-body {{ grid-template-columns:minmax(0,1fr) 430px; }} .overview-body .cmt-body {{ font-size:13px; padding:14px; }} }}
  @media(max-width:899px) {{ .overview-body {{ grid-template-columns:minmax(0,1fr); grid-template-rows:minmax(0,1fr) minmax(160px,35%); }} .overview-body .cmt-body {{ font-size:13px; padding:12px; }} }}
  @media(max-width:600px) {{ .tab-count {{ display:none; }} .overview-card-title {{ font-size:11px; padding:8px; }} .overview-card-title span {{ font-size:8px; }} .overview-cards {{ gap:6px; }} .overview-card th,.overview-card td {{ font-size:10px; }} }}

</style>
{shared_ui()}
</head><body class="finance-recap">

<div class="wrap">
  <header class="page-header">
    <div class="finance-header">
      <div class="finance-brand"><span class="brand-mark" aria-hidden="true">▥</span><h1>지난주 시장 Recap</h1></div>
      <div class="header-actions">
        <nav class="finance-nav" aria-label="화면 이동"><a class="navbtn" href="/weekly">스크리너</a><a class="navbtn" href="/recap" aria-current="page">시장 Recap</a><a class="navbtn" href="/industries">산업 분류</a></nav>
        <div class="update-group">
          <button class="update-button" type="button" id="refreshBtn" data-unavailable="{str(not server_mode).lower()}" aria-describedby="status" onclick="refresh(true)" {"" if server_mode else "disabled"}>Recap 업데이트</button>
          <button class="btn ghost" type="button" id="dataBtn" onclick="refresh(false)" title="AI 코멘터리 없이 시세 데이터만 업데이트" {"" if server_mode else "disabled"}>시세만 업데이트</button>
        </div>
        <button class="theme-toggle" type="button" data-theme-toggle aria-label="테마 변경">☾</button>
      </div>
    </div>
    <div class="update-notice"><span class="update-scope">주간 Recap · {target_asof} 기준</span><span>표시 결과 {html.escape(result_asof)} · 생성 {html.escape(generated_at)}</span><span id="status" class="update-status" role="status" aria-live="polite"></span></div>
    <span class="catalog-warning">{catalog_warning}</span>
  </header>
  <nav class="recap-tabs" role="tablist" aria-label="시장 Recap 분야">
    <button class="recap-tab" id="tab-overview" type="button" role="tab" aria-selected="true" aria-controls="panel-overview" data-panel="overview">종합</button>
    <button class="recap-tab" id="tab-indices" type="button" role="tab" aria-selected="false" tabindex="-1" aria-controls="panel-indices" data-panel="indices">지수 <span class="tab-count">{len(rows)}</span></button>
    <button class="recap-tab" id="tab-commodities" type="button" role="tab" aria-selected="false" aria-controls="panel-commodities" tabindex="-1" data-panel="commodities">원자재 <span class="tab-count">{len(commodities)}</span></button>
    <button class="recap-tab" id="tab-ratefx" type="button" role="tab" aria-selected="false" aria-controls="panel-ratefx" tabindex="-1" data-panel="ratefx">금리·환율 <span class="tab-count">{len(rates) + len(fx)}</span></button>
  </nav>
  <main class="recap-panels">
    <section class="section" id="panel-overview" role="tabpanel" aria-labelledby="tab-overview">
      <div class="section-head"><h2>주간 시장 종합</h2><span class="meta">주식·원자재·금리·환율을 연결한 시장 해석</span></div>
      <div class="section-body overview-body">
        {cmt_overview}
        <div class="overview-summary" tabindex="0" role="region" aria-label="종합 대표 지표">
          <p class="overview-note">대표 지표의 주간·월간 변화입니다. 각 분야의 전체 데이터는 위 탭에서 확인하세요.</p>
          <div class="overview-cards">{overview_cards}</div>
        </div>
      </div>
    </section>
    <section class="section" id="panel-indices" role="tabpanel" aria-labelledby="tab-indices" hidden>
      <div class="section-head"><h2>주요 지수</h2><span class="meta">등락률 % · 최근 60일 추이</span></div>
      <div class="section-body">
        <div class="table-scroll" tabindex="0" role="region" aria-label="주요 지수 시세">
          <table><thead><tr><th>국가</th><th style="text-align:left">지수</th><th>종가</th><th class="weekly">1W</th><th>1M</th><th>3M</th><th>YTD</th><th>추이(60일)</th><th>52H대비</th></tr></thead><tbody id="tbody">{table_body}</tbody></table>
        </div>
        {cmt_index}
      </div>
    </section>
    <section class="section" id="panel-commodities" role="tabpanel" aria-labelledby="tab-commodities" hidden>
      <div class="section-head"><h2>주요 원자재</h2><span class="meta">등락률 % · 최근 60일 추이</span></div>
      <div class="section-body">
        <div class="table-scroll" tabindex="0" role="region" aria-label="원자재 시세">
          <table><thead><tr><th>분류</th><th style="text-align:left">품목</th><th>가격</th><th class="weekly">1W</th><th>1M</th><th>3M</th><th>YTD</th><th>추이(60일)</th><th>52H대비</th></tr></thead><tbody id="tbody-cmdty">{commodity_body}</tbody></table>
        </div>
        {cmt_cmdty}
      </div>
    </section>
    <section class="section" id="panel-ratefx" role="tabpanel" aria-labelledby="tab-ratefx" hidden>
      <div class="section-head"><h2>국채 금리·환율</h2><span class="meta">금리 bp · 환율 % · 네이버 금융</span></div>
      <div class="section-body">
        <div class="table-scroll" tabindex="0" role="region" aria-label="국채 금리와 환율 시세">
          <div class="data-block"><h3 class="data-block-title">국채 금리 (%)</h3><table><thead><tr><th>국가</th><th style="text-align:left">국채</th><th>금리</th><th class="weekly">1W</th><th>1M</th><th>3M</th><th>추이(60일)</th></tr></thead><tbody id="tbody-rates">{rates_body}</tbody></table></div>
          <div class="data-block"><h3 class="data-block-title">환율</h3><table><thead><tr><th>분류</th><th style="text-align:left">환율</th><th>현재가</th><th class="weekly">1W</th><th>1M</th><th>3M</th><th>추이(60일)</th></tr></thead><tbody id="tbody-fx">{fx_body}</tbody></table></div>
        </div>
        {cmt_ratefx}
      </div>
    </section>
  </main>
</div>

<script>

const recapTabs = Array.from(document.querySelectorAll('.recap-tab'));
function showRecapPanel(name, focus = false) {{
  const chosen = recapTabs.find(tab => tab.dataset.panel === name) || recapTabs[0];
  for (const tab of recapTabs) {{
    const active = tab === chosen;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    document.getElementById(tab.getAttribute('aria-controls')).hidden = !active;
  }}
  if (focus) chosen.focus();
}}
for (const [index, tab] of recapTabs.entries()) {{
  tab.addEventListener('click', () => {{ showRecapPanel(tab.dataset.panel); history.replaceState(null, '', '#' + tab.dataset.panel); }});
  tab.addEventListener('keydown', event => {{
    let target;
    if (event.key === 'ArrowRight') target = (index + 1) % recapTabs.length;
    if (event.key === 'ArrowLeft') target = (index + recapTabs.length - 1) % recapTabs.length;
    if (event.key === 'Home') target = 0;
    if (event.key === 'End') target = recapTabs.length - 1;
    if (target === undefined) return;
    event.preventDefault();
    showRecapPanel(recapTabs[target].dataset.panel, true);
    history.replaceState(null, '', '#' + recapTabs[target].dataset.panel);
  }});
}}
showRecapPanel(location.hash.slice(1));
window.addEventListener('hashchange', () => showRecapPanel(location.hash.slice(1)));

async function refresh(withCommentary) {{
  const btn = document.getElementById('refreshBtn');
  const btn2 = document.getElementById('dataBtn');
  const status = document.getElementById('status');
  if (btn.disabled || btn2.disabled) return;
  FinanceUI.update(btn, 'running', withCommentary ? 'Recap 생성 중…' : '시세 수집 중…',
    withCommentary ? '시세 수집과 AI 코멘터리 4종 생성 중 · 몇 분 걸릴 수 있습니다.' : '시세 데이터만 수집하고 있습니다.', status);
  btn2.disabled = true;
  try {{
    const res = await fetch('/api/recap/refresh', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{commentary:!!withCommentary}})
    }});
    const result = await res.json();
    if (!res.ok || !result.ok) throw new Error(result.error || 'HTTP ' + res.status);
    FinanceUI.remember(withCommentary && !result.commentary_ok ? '시세 업데이트 완료 · 일부 AI 코멘터리는 생성되지 않았습니다.' : 'Recap 업데이트 완료');
    location.reload();
  }} catch (e) {{
    FinanceUI.update(btn, 'error', '다시 업데이트', '업데이트 실패 · ' + e.message, status);
    btn2.disabled = false;
  }}
}}
</script>
</body></html>"""
