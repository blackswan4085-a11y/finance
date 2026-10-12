"""주간 시장 Recap HTML 렌더링. 서버가 이 HTML을 /recap 에서 서빙."""
from __future__ import annotations

import html
from typing import Dict, List, Optional


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


def _group_rows(rows: List[Dict]) -> str:
    out = []
    prev_group = None
    # 그룹별 rowspan 계산
    group_counts: Dict[str, int] = {}
    for r in rows:
        group_counts[r["group"]] = group_counts.get(r["group"], 0) + 1

    for r in rows:
        tds = []
        if r["group"] != prev_group:
            tds.append(f'<td class="grp" rowspan="{group_counts[r["group"]]}">'
                       f'{html.escape(r["group"])}</td>')
            prev_group = r["group"]
        name = html.escape(r["name"])
        date = html.escape(str(r.get("date", "-")))
        tds.append(f'<td class="name">{name}<span class="dt">{date}</span></td>')
        tds.append(f'<td class="price">{_fmt_price(r.get("price"))}</td>')
        tds.append(_pct_cell(r.get("chg_1w")))
        tds.append(_pct_cell(r.get("chg_1m")))
        tds.append(_pct_cell(r.get("chg_3m")))
        tds.append(_pct_cell(r.get("chg_ytd")))
        tds.append(f'<td class="spark-cell">{r.get("spark", "")}</td>')
        tds.append(_pct_cell(r.get("from_52w_high")))
        out.append("<tr>" + "".join(tds) + "</tr>")
    return "\n".join(out)


def render_recap_html(payload: Optional[Dict], server_mode: bool = True) -> str:
    rows = payload.get("rows", []) if payload else []
    commodities = payload.get("commodities", []) if payload else []
    commentary = payload.get("commentary", {}) if payload else {}
    generated_at = payload.get("generated_at", "아직 생성되지 않음") if payload else "아직 생성되지 않음"

    table_body = _group_rows(rows) if rows else (
        '<tr><td colspan="9" class="empty">아직 데이터가 없습니다. '
        '[업데이트] 버튼을 눌러 생성하세요.</td></tr>'
    )
    commodity_body = _group_rows(commodities) if commodities else (
        '<tr><td colspan="9" class="empty">아직 원자재 데이터가 없습니다. '
        '[업데이트] 버튼을 눌러 생성하세요.</td></tr>'
    )

    comm_text = html.escape(commentary.get("text", "") or "")
    comm_ok = commentary.get("ok", False)
    comm_paras = "".join(f"<p>{p}</p>" for p in comm_text.split("\n") if p.strip()) or \
        "<p class='muted'>아직 코멘터리가 없습니다. [업데이트]를 눌러 생성하세요.</p>"
    comm_badge = "" if comm_ok else '<span class="warn-badge">생성 실패/미생성</span>'

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
  .topbar {{ display:flex; align-items:center; gap:12px; margin-bottom:16px; }}
  .topbar a {{ color:var(--muted); text-decoration:none; font-size:13px; }}
  .topbar a:hover {{ color:var(--txt); }}
  h1 {{ font-size:20px; margin:0; letter-spacing:-.5px; }}
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
  td.grp {{ text-align:center; color:var(--muted); font-weight:700;
            border-right:1px solid var(--line); background:var(--panel2);
            vertical-align:middle; width:46px; }}
  td.name {{ text-align:left; font-weight:600; }}
  td.name .dt {{ color:var(--muted); font-weight:400; font-size:11px; margin-left:6px; }}
  td.price {{ font-variant-numeric:tabular-nums; }}
  td.pct {{ font-variant-numeric:tabular-nums; font-weight:600; }}
  td.pct.up {{ color:var(--up); }}
  td.pct.down {{ color:var(--down); }}
  td.pct.na {{ color:var(--muted); }}
  td.spark-cell {{ text-align:center; width:130px; }}
  .spark {{ vertical-align:middle; }}
  td.empty {{ text-align:center; color:var(--muted); padding:30px; }}
  .cmt {{ padding:16px 18px; line-height:1.75; }}
  .cmt .cmt-title {{ font-weight:700; color:#8ab4ff; margin-bottom:8px; }}
  .cmt p {{ margin:0 0 12px; color:#d4dcea; }}
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
</style>
</head><body>
<div class="wrap">
  <div class="topbar">
    <a href="/">← 스크리너로</a>
    <h1>1. 지난주 시장 Recap</h1>
  </div>

  <div class="section">
    <div class="section-head">
      <span>1-1. 주요 지수 한눈에</span>
      <span class="controls">
        <span id="status">생성: {html.escape(generated_at)}</span>
        <button class="btn" id="refreshBtn" onclick="refresh(true)">🔄 업데이트</button>
        <button class="btn ghost" id="dataBtn" onclick="refresh(false)"
                title="코멘터리 없이 지수 데이터만 새로고침">데이터만</button>
      </span>
    </div>
    <table>
      <thead><tr>
        <th></th><th style="text-align:left">지수</th><th>종가</th>
        <th>1W</th><th>1M</th><th>3M</th><th>YTD</th>
        <th>추이(60일)</th><th>52H대비</th>
      </tr></thead>
      <tbody id="tbody">
{table_body}
      </tbody>
    </table>
  </div>

  <div class="section">
    <div class="section-head"><span>1-2. 주요 원자재</span></div>
    <table>
      <thead><tr>
        <th></th><th style="text-align:left">품목</th><th>가격</th>
        <th>1W</th><th>1M</th><th>3M</th><th>YTD</th>
        <th>추이(60일)</th><th>52H대비</th>
      </tr></thead>
      <tbody id="tbody-cmdty">
{commodity_body}
      </tbody>
    </table>
  </div>

  <div class="section">
    <div class="section-head"><span>📝 Editor's Comment{comm_badge}</span></div>
    <div class="cmt" id="cmt">
      <div class="cmt-title">지난주 시장 코멘터리</div>
      {comm_paras}
    </div>
  </div>
</div>

<script>
async function refresh(withCommentary) {{
  const btn = document.getElementById('refreshBtn');
  const btn2 = document.getElementById('dataBtn');
  const status = document.getElementById('status');
  btn.disabled = true; btn2.disabled = true;
  status.innerHTML = '<span class="spin"></span>' +
    (withCommentary ? '지수 수집 + 코멘터리 생성 중… (최대 수십 초)' : '지수 데이터 수집 중…');
  try {{
    const res = await fetch('/api/recap/refresh', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{ commentary: !!withCommentary }})
    }});
    if (!res.ok) throw new Error('HTTP ' + res.status);
    // 서버가 새 HTML 조각 대신 전체를 다시 그리도록 페이지 리로드
    location.reload();
  }} catch (e) {{
    status.textContent = '실패: ' + e.message;
    btn.disabled = false; btn2.disabled = false;
  }}
}}
</script>
</body></html>"""
