'use strict';
// 정배열 변화: 최근 2개 스냅샷 비교(신규 진입/이탈)를 표시.
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

  async function load() {
    const meta = document.getElementById('meta');
    const message = document.getElementById('message');
    try {
      const r = await fetch('/api/alignment-changes', { cache: 'no-store' });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || '불러오지 못했습니다.');
      if (d.message) {
        message.style.display = 'block';
        message.textContent = d.message;
      }
      if (d.current && d.previous) {
        meta.textContent = `비교 기준: ${d.previous} → ${d.current} · 유지 ${d.kept_count}종목 · 신규 ${d.added.length} · 이탈 ${d.removed.length}`;
      } else if (d.current) {
        meta.textContent = `현재 기준일 ${d.current} (정배열 ${d.kept_count}종목). 비교할 직전 스냅샷이 아직 없습니다.`;
      } else {
        meta.textContent = '';
      }
      fillTable('addedRows', 'addedEmpty', 'addedCount', d.added || []);
      fillTable('removedRows', 'removedEmpty', 'removedCount', d.removed || []);
    } catch (e) {
      message.style.display = 'block';
      message.textContent = e.message;
      message.classList.add('error');
    }
  }

  document.addEventListener('DOMContentLoaded', load);
})();
