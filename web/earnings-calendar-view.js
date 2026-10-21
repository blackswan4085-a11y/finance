'use strict';
// 미국 실적 캘린더: 캐시 로드/렌더 + 나스닥 수집 + 관심종목 필터.
(function () {
  let allRows = [];        // 캐시의 전체 행
  let watchSymbols = null; // 관심종목 중 미국 심볼 Set (lazy 로드)

  function esc(v) {
    return String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function showMessage(text, isError) {
    const box = document.getElementById('message');
    if (!text) { box.style.display = 'none'; return; }
    box.style.display = 'block'; box.textContent = text;
    box.classList.toggle('error', !!isError);
  }

  async function watchlistSymbols() {
    if (watchSymbols) return watchSymbols;
    watchSymbols = new Set();
    try {
      const r = await fetch('/api/watchlist', { cache: 'no-store' });
      const items = await r.json();
      if (Array.isArray(items)) {
        for (const it of items) {
          if (it.country === 'US') watchSymbols.add(String(it.symbol).toUpperCase());
        }
      }
    } catch (_) { /* 관심종목 로드 실패 시 전체 표시 */ }
    return watchSymbols;
  }

  async function render() {
    const onlyWatch = document.getElementById('onlyWatch').checked;
    let rows = allRows;
    if (onlyWatch) {
      const set = await watchlistSymbols();
      rows = rows.filter(r => set.has(String(r.symbol).toUpperCase()));
    }
    const tbody = document.getElementById('rows');
    const empty = document.getElementById('empty');
    tbody.replaceChildren();
    empty.style.display = rows.length ? 'none' : 'block';
    let lastDate = '';
    for (const r of rows) {
      if (r.date !== lastDate) {
        const sep = document.createElement('tr');
        sep.className = 'date-group';
        sep.innerHTML = `<td colspan="7">${esc(r.date)}</td>`;
        tbody.append(sep);
        lastDate = r.date;
      }
      const tr = document.createElement('tr');
      tr.innerHTML =
        `<td>${esc(r.date)}</td><td class="sym">${esc(r.symbol)}</td><td>${esc(r.name)}</td>` +
        `<td>${esc(r.time)}</td><td>${esc(r.epsForecast)}</td><td>${esc(r.lastYearEPS)}</td><td>${esc(r.marketCap)}</td>`;
      tbody.append(tr);
    }
  }

  function setMeta(data) {
    const meta = document.getElementById('meta');
    if (data && data.collected_at) {
      meta.textContent = `수집 범위 ${data.from} ~ ${data.to} · 수집 시각 ${data.collected_at} · 총 ${data.rows.length}건`;
    } else {
      meta.textContent = '아직 수집된 데이터가 없습니다.';
    }
  }

  async function load() {
    try {
      const r = await fetch('/api/earnings-calendar', { cache: 'no-store' });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || '불러오지 못했습니다.');
      allRows = data.rows || [];
      setMeta(data);
      await render();
    } catch (e) { showMessage(e.message, true); }
  }

  async function refresh() {
    const btn = document.getElementById('refreshBtn');
    const from = document.getElementById('fromDate').value;
    const days = parseInt(document.getElementById('days').value, 10) || 7;
    btn.disabled = true;
    showMessage('나스닥에서 실적 일정을 수집하는 중…');
    try {
      const r = await fetch('/api/earnings-calendar/refresh', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ from, days }),
      });
      const data = await r.json();
      if (!r.ok || data.ok === false) throw new Error(data.error || '수집에 실패했습니다.');
      allRows = data.rows || [];
      setMeta(data);
      showMessage('');
      await render();
    } catch (e) { showMessage(e.message, true); }
    finally { btn.disabled = false; }
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('fromDate').value = new Date().toISOString().slice(0, 10);
    document.getElementById('refreshBtn').addEventListener('click', refresh);
    document.getElementById('onlyWatch').addEventListener('change', render);
    load();
  });
})();
