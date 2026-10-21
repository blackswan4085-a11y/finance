'use strict';
// 관심종목 화면: 목록 로드/렌더 + 추가/삭제. 저장은 서버의 watchlist.json.
(function () {
  const MARKET_LABEL = { KR: '한국', US: '미국' };

  function esc(v) {
    return String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function showMessage(text, isError) {
    const box = document.getElementById('message');
    if (!text) { box.style.display = 'none'; return; }
    box.style.display = 'block';
    box.textContent = text;
    box.classList.toggle('error', !!isError);
  }

  function render(items) {
    const rows = document.getElementById('rows');
    const empty = document.getElementById('empty');
    rows.replaceChildren();
    empty.style.display = items.length ? 'none' : 'block';
    for (const it of items) {
      const tr = document.createElement('tr');
      const market = esc(it.market || MARKET_LABEL[it.country] || it.country || '');
      tr.innerHTML =
        `<td>${esc(it.name)}</td><td>${esc(it.symbol)}</td><td>${market}</td>` +
        `<td><button class="del" type="button" aria-label="삭제">삭제</button></td>`;
      tr.querySelector('.del').addEventListener('click', () => remove(it.symbol, it.country));
      rows.append(tr);
    }
  }

  async function load() {
    try {
      const r = await fetch('/api/watchlist', { cache: 'no-store' });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || '목록을 불러오지 못했습니다.');
      render(data);
    } catch (e) {
      showMessage(e.message, true);
    }
  }

  async function add(value) {
    if (!value.trim()) return;
    try {
      const r = await fetch('/api/watchlist/add', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: value.trim() }),
      });
      const data = await r.json();
      if (!r.ok || data.ok === false) throw new Error(data.error || '추가하지 못했습니다.');
      showMessage('');
      document.getElementById('addInput').value = '';
      render(data.items);
    } catch (e) {
      showMessage(e.message, true);
    }
  }

  async function remove(symbol, country) {
    try {
      const r = await fetch('/api/watchlist/remove', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, country }),
      });
      const data = await r.json();
      if (!r.ok || data.ok === false) throw new Error(data.error || '삭제하지 못했습니다.');
      render(data.items);
    } catch (e) {
      showMessage(e.message, true);
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('addForm').addEventListener('submit', e => {
      e.preventDefault();
      add(document.getElementById('addInput').value);
    });
    load();
  });
})();
