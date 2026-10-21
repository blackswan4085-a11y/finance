'use strict';
// 정배열 변화: 최근 2개 스냅샷 비교(신규 진입/이탈)를 표시.
// 스냅샷이 부족하면 '지난 데이터로 비교 생성'(backfill)으로 과거 2주를 즉석 계산.
(function () {
  const MKT = { KR: '한국', US: '미국' };

  function esc(v) {
    return String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function fillTable(bodyId, emptyId, countId, rows) {
    const body = document.getElementById(bodyId);
    const empty = document.getElementById(emptyId);
    const count = document.getElementById(countId);
    body.replaceChildren();
    count.textContent = rows.length ? `(${rows.length})` : '';
    empty.style.display = rows.length ? 'none' : 'block';
    for (const r of rows) {
      const tr = document.createElement('tr');
      const market = esc(r.market || MKT[r.country] || r.country || '');
      tr.innerHTML = `<td class="sym">${esc(r.symbol)}</td><td>${esc(r.name)}</td><td>${market}</td>`;
      body.append(tr);
    }
  }

  function render(d) {
    const meta = document.getElementById('meta');
    const message = document.getElementById('message');
    const btn = document.getElementById('backfillBtn');
    message.classList.remove('error');
    btn.style.display = d.can_backfill ? 'inline-block' : 'none';
    if (d.message) { message.style.display = 'block'; message.textContent = d.message; }
    else { message.style.display = 'none'; }
    if (d.current && d.previous) {
      meta.textContent = `비교 기준: ${d.previous} → ${d.current} · 유지 ${d.kept_count}종목 · 신규 ${d.added.length} · 이탈 ${d.removed.length}`;
    } else if (d.current) {
      meta.textContent = `현재 기준일 ${d.current} (정배열 ${d.kept_count}종목).`;
    } else {
      meta.textContent = '';
    }
    fillTable('addedRows', 'addedEmpty', 'addedCount', d.added || []);
    fillTable('removedRows', 'removedEmpty', 'removedCount', d.removed || []);
  }

  function showError(msg) {
    const message = document.getElementById('message');
    message.style.display = 'block';
    message.textContent = msg;
    message.classList.add('error');
  }

  async function load() {
    try {
      const r = await fetch('/api/alignment-changes', { cache: 'no-store' });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || '불러오지 못했습니다.');
      render(d);
    } catch (e) { showError(e.message); }
  }

  async function backfill() {
    const btn = document.getElementById('backfillBtn');
    const message = document.getElementById('message');
    btn.disabled = true;
    message.classList.remove('error');
    message.style.display = 'block';
    message.textContent = '과거 2주 기준으로 정배열을 재계산하는 중입니다. 전체 종목 스캔이라 수십 초~수 분 걸릴 수 있습니다…';
    try {
      const r = await fetch('/api/alignment-changes/backfill', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      });
      const d = await r.json();
      if (!r.ok || d.ok === false) throw new Error(d.error || '생성에 실패했습니다.');
      render(d);
    } catch (e) { showError(e.message); }
    finally { btn.disabled = false; }
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('backfillBtn').addEventListener('click', backfill);
    load();
  });
})();
