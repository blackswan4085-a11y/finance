/* Editable financial tables. Pasted cells are data; formulas are never evaluated. */
((root) => {
  'use strict';
  function numeric(value) {
    if (value == null) return null;
    let text = String(value).trim().replaceAll('−', '-');
    if (['', '-', '—', 'N/A', 'NA'].includes(text.toUpperCase())) return null;
    if (/^\(.*\)$/.test(text)) text = '-' + text.slice(1, -1).trim();
    if (!/^[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(text)) throw Error('숫자 형식을 확인해 주세요.');
    const result = Number(text.replaceAll(',', ''));
    if (!Number.isFinite(result)) throw Error('유효한 숫자를 입력해 주세요.');
    return result;
  }
  function matrix(text) {
    const rows = text.replaceAll('\r\n', '\n').replaceAll('\r', '\n').split('\n').map(row => row.split('\t'));
    while (rows.length && rows.at(-1).every(value => !value.trim())) rows.pop();
    if (rows.length && /^(회계연도|연도|year|fiscal year)$/i.test(rows[0][0].trim())) rows.shift();
    return rows;
  }
  function pasteRows(existing, pasted, rowIndex, columnIndex, keys) {
    if (rowIndex + pasted.length > 100 || pasted.some(row => columnIndex + row.length > keys.length)) {
      throw Error('표의 항목 순서를 확인해 주세요. 최대 100개 기간까지 붙여 넣을 수 있습니다.');
    }
    const rows = existing.map(row => ({...row}));
    pasted.forEach((values, offset) => {
      const index = rowIndex + offset;
      while (rows.length <= index) rows.push(Object.fromEntries(keys.map(key => [key, ''])));
      values.forEach((value, column) => { rows[index][keys[columnIndex + column]] = value.trim(); });
    });
    return rows;
  }
  const columns = {quarters: ['year', 'quarter', 'revenue', 'operatingIncome', 'eps'], annuals: ['year', 'revenue', 'operatingIncome']};
  const labels = {year: '회계연도', quarter: '분기', revenue: '매출', operatingIncome: '영업이익', eps: 'EPS'};
  const metaIds = ['financialName', 'financialCurrency', 'financialBasis', 'fiscalMonth', 'periodStart', 'periodEnd'];

  function create(onChange, onError) {
    const $ = id => document.getElementById(id);
    let project, locked = false;
    function readRows(kind) {
      const table = $(kind + 'Body').closest('table');
      return [...table.querySelectorAll('[data-period-header]')].map((_, index) => Object.fromEntries(
        columns[kind].map(key => [key, table.querySelector(`input[data-period="${index}"][data-key="${key}"]`).value])));
    }
    function drawRows(kind, rows) {
      const body = $(kind + 'Body'); body.replaceChildren();
      const table = body.closest('table');
      table.classList.add('period-table');
      table.style.minWidth = (100 + rows.length * 140) + 'px';
      const header = document.createElement('tr'), corner = document.createElement('th');
      corner.scope = 'col'; corner.textContent = '항목 / 기간'; header.append(corner);
      function cellInput(key, index) {
        const input = document.createElement('input');
        input.type = 'text'; input.inputMode = key === 'year' || key === 'quarter' ? 'numeric' : 'decimal';
        input.value = rows[index][key] ?? ''; input.dataset.key = key; input.dataset.period = index; input.disabled = locked;
        input.setAttribute('aria-label', `${kind === 'quarters' ? '분기' : '연간'} 실적 ${index + 1}열 ${labels[key]}`);
        input.autocomplete = 'off'; input.spellcheck = false;
        input.placeholder = key === 'year' ? '2026' : key === 'quarter' ? 'Q3' : '미제공';
        return input;
      }
      rows.forEach((row, index) => {
        const th = document.createElement('th'), heading = document.createElement('div');
        th.scope = 'col'; th.dataset.periodHeader = index; heading.className = 'period-heading';
        for (const key of kind === 'quarters' ? ['year', 'quarter'] : ['year']) {
          const label = document.createElement('label'); label.className = 'period-field';
          label.append(cellInput(key, index), document.createTextNode(key === 'year' ? '년' : '분기'));
          heading.append(label);
        }
        th.append(heading); header.append(th);
      });
      table.tHead.replaceChildren(header);
      columns[kind].filter(key => key !== 'year' && key !== 'quarter').forEach(key => {
        const tr = document.createElement('tr'), label = document.createElement('th');
        label.scope = 'row'; label.textContent = labels[key]; tr.append(label);
        rows.forEach((_, index) => {
          const td = document.createElement('td'); td.append(cellInput(key, index)); tr.append(td);
        });
        body.append(tr);
      });
    }
    function defaults(kind) {
      return Array.from({length: kind === 'quarters' ? 8 : 5}, (_, index) => {
        if (kind === 'quarters') {
          const serial = project.year * 4 + project.quarter - 1 - (7 - index);
          return {year: Math.floor(serial / 4), quarter: serial % 4 + 1};
        }
        return {year: project.year - (project.quarter === 4 ? 0 : 1) - (4 - index)};
      });
    }
    function render(value) {
      project = value;
      const data = value.financials || {}, company = data.company || {}, period = data.reportPeriod || {};
      $('financialName').value = company.name || value.name || value.ticker;
      $('financialCurrency').value = company.currency || (/^\d{6}$/.test(value.ticker) ? 'KRW' : 'USD');
      $('financialBasis').value = company.basis || value.basis;
      $('fiscalMonth').value = company.fiscalYearEndMonth || 12;
      $('periodStart').value = period.start || ''; $('periodEnd').value = period.end || '';
      $('targetPeriod').textContent = `입력 대상 FY${value.year} Q${value.quarter}`;
      for (const kind of ['quarters', 'annuals']) drawRows(kind, data[kind]?.length ? data[kind] : defaults(kind));
      units();
    }
    function units() {
      $('financialUnit').textContent = `금액: ${$('financialCurrency').value} 백만 · EPS: ${$('financialCurrency').value} / 주 · 공란은 미제공, 실제 0은 0으로 입력`;
    }
    function read() {
      return {company: {name: $('financialName').value, currency: $('financialCurrency').value,
        basis: $('financialBasis').value, fiscalYearEndMonth: $('fiscalMonth').value},
        reportPeriod: {start: $('periodStart').value, end: $('periodEnd').value},
        quarters: readRows('quarters'), annuals: readRows('annuals')};
    }
    function ready() {
      if (!project || !$('periodStart').value || !$('periodEnd').value) return false;
      return readRows('quarters').some(row => String(row.year).replace(/^FY/i, '').trim() === String(project.year)
        && String(row.quarter).replace(/^Q/i, '').replace(/분기$/, '').trim() === String(project.quarter)
        && ['revenue', 'operatingIncome', 'eps'].some(key => { try { return numeric(row[key]) !== null; } catch { return false; } }));
    }
    function setDisabled(value) {
      locked = value;
      [...metaIds.map($), ...$('financialEditor').querySelectorAll('table input, table button, [data-add-financial]')].forEach(el => { el.disabled = value; });
    }
    metaIds.forEach(id => $(id).addEventListener('input', () => { units(); onChange(); }));
    for (const kind of ['quarters', 'annuals']) {
      const body = $(kind + 'Body');
      const grid = body.closest('table');
      grid.addEventListener('input', onChange);
      grid.addEventListener('paste', event => {
        if (locked || !event.target.matches('input')) return;
        const text = event.clipboardData?.getData('text/plain') || '';
        if (!/[\t\r\n]/.test(text)) return;
        event.preventDefault();
        const period = Number(event.target.dataset.period), key = event.target.dataset.key;
        try {
          const pasted = matrix(text);
          const transposed = Array.from({length: Math.max(0, ...pasted.map(row => row.length))}, (_, column) => pasted.map(row => row[column] ?? ''));
          const data = pasteRows(readRows(kind), transposed, period, columns[kind].indexOf(key), columns[kind]);
          drawRows(kind, data); onChange();
          grid.querySelector(`input[data-period="${period}"][data-key="${key}"]`)?.focus();
        } catch (error) { onError(error); }
      });
      $('add' + (kind === 'quarters' ? 'Quarter' : 'Annual')).addEventListener('click', () => {
        const rows = readRows(kind);
        if (rows.length >= 100) { onError(new Error('최대 100개 기간까지 입력할 수 있습니다.')); return; }
        const last = rows.at(-1) || defaults(kind).at(-1);
        const year = Number(String(last.year).replace(/^FY/i, '')) || project.year;
        const next = {year: year + 1};
        if (kind === 'quarters') {
          const quarter = Number(String(last.quarter).replace(/^Q/i, '').replace(/분기$/, '')) || project.quarter;
          next.year = quarter === 4 ? year + 1 : year; next.quarter = quarter === 4 ? 1 : quarter + 1;
        }
        rows.push(next); drawRows(kind, rows); onChange();
        grid.querySelector(`input[data-period="${rows.length - 1}"][data-key="revenue"]`)?.focus();
      });
    }
    return {render, read, ready, setDisabled};
  }
  const api = {numeric, matrix, pasteRows, create};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FinancialTable = api;
})(typeof window === 'undefined' ? globalThis : window);

(() => {
  'use strict';
  if (typeof document === 'undefined') return;
  const $ = id => document.getElementById(id);
  let items = [], current = null, dirty = false, busy = false, pollTimer;
  const fields = ['transcript', 'notes'];
  const node = (tag, text, cls) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (cls) el.className = cls; return el; };

  async function api(path, payload) {
    const response = await fetch('/api/earnings' + path, payload === undefined ? {cache: 'no-store'} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '요청을 처리하지 못했습니다.');
    return data;
  }

  function message(error) { $('pageStatus').textContent = error ? error.message || String(error) : ''; }
  function running() { return current?.job?.state === 'running'; }
  function setBusy(value) { busy = value; controls(); }
  function controls() {
    const unsupported = current && current.financials_editable !== true;
    const locked = busy || running() || unsupported;
    table.setDisabled(Boolean(locked));
    $('financialCompatibility').hidden = !unsupported;
    fields.forEach(id => { $(id).disabled = locked; });
    $('saveInputs').disabled = locked || !dirty;
    $('generateReport').disabled = locked || !table.ready();
    $('newReport').disabled = busy;
    $('generateReport').textContent = running() && current.job.action === 'generate' ? '리포트 생성 중…' : current?.has_report ? '리포트 다시 생성' : '리포트 생성';
    $('saveState').textContent = dirty ? '저장하지 않은 변경사항' : current?.revision ? '자료 저장됨' : current?.imported ? '보관된 자료' : '새 리포트';
    $('saveState').classList.toggle('dirty', dirty);
    $('actionHint').textContent = running() ? '페이지를 이동해도 서버에서 작업을 계속합니다.' : !table.ready() ? '보고 대상 분기의 실적과 실제 보고 기간을 입력해 주세요.' : dirty ? '리포트 생성 시 입력 자료도 함께 저장합니다.' : '확정된 템플릿으로 실적·주가·컨콜을 정리합니다.';
    $('transcriptCount').textContent = $('transcript').value.length.toLocaleString() + '자';
  }

  function renderLibrary() {
    const query = $('reportSearch').value.trim().toLowerCase();
    const shown = items.filter(p => (p.ticker + ' ' + p.name + ' ' + p.id).toLowerCase().includes(query));
    $('reportCount').textContent = items.length;
    const list = $('reportList'); list.replaceChildren();
    for (const item of shown) {
      const button = node('button', undefined, 'report-item'); button.type = 'button';
      button.setAttribute('aria-current', String(item.id === current?.id));
      const top = node('div', undefined, 'report-item-top');
      top.append(node('strong', item.ticker), node('span', `FY${item.year} Q${item.quarter}`, 'item-period'));
      const state = item.job?.state === 'running' ? '처리 중…' : item.job?.state === 'error' ? '작업 확인 필요' : item.report_stale ? '자료 변경 · 재생성 필요' : item.has_report ? '리포트 완성' : item.financials_available ? '실적 입력됨' : '자료 입력 중';
      button.append(top, node('small', item.name), node('span', state, 'item-state' + (item.has_report && !item.report_stale ? ' complete' : '')));
      button.addEventListener('click', () => selectProject(item.id).catch(message)); list.append(button);
    }
    if (!shown.length) list.append(node('p', query ? '검색 결과가 없습니다.' : '새 리포트를 만들어 시작하세요.', 'empty-library'));
  }

  function inputData() {
    return {transcript: $('transcript').value, notes: $('notes').value};
  }

  function setInputs(project) {
    const inputs = project.inputs;
    $('transcript').value = inputs.transcript || '';
    $('notes').value = inputs.notes || '';
    table.render(project);
  }


  function artifact(name) {
    return `/earnings-files/${encodeURIComponent(current.id)}/${current.report_version || 'original'}/${encodeURIComponent(name)}`;
  }
  function renderPreview() {
    $('previewCount').textContent = current.has_report ? '한 페이지' : '';
    $('previewEmpty').hidden = current.has_report; $('previewReady').hidden = !current.has_report;
    $('downloadLinks').replaceChildren(); $('reportImages').replaceChildren();
    if (!current.has_report) return;
    $('reportFreshness').textContent = current.report_stale ? '자료가 변경됐습니다. 다시 생성하면 최신 입력이 반영됩니다.' : current.generated_at ? '생성 ' + current.generated_at.replace('T', ' ') : '보관된 완성본';
    const html = node('a', 'HTML 열기', 'secondary'); html.href = artifact('report.html'); html.target = '_blank'; html.rel = 'noopener'; $('downloadLinks').append(html);
    current.files.forEach((file, i) => {
      const link = node('a', current.files.length > 1 ? `PNG ${i + 1} 저장` : 'PNG 저장', 'secondary');
      link.href = artifact(file); link.download = current.id + '-' + file; $('downloadLinks').append(link);
      const img = document.createElement('img'); img.src = artifact(file); img.alt = `${current.name} FY${current.year} Q${current.quarter} 실적 리포트`; img.loading = 'lazy'; img.width = current.report_width || 2880; img.height = current.report_height || 3880; $('reportImages').append(img);
    });
  }

  function renderProject(setValues = true) {
    $('welcome').hidden = true; $('editor').hidden = false;
    $('reportTicker').textContent = current.ticker;
    $('reportName').textContent = current.name;
    $('reportMeta').textContent = `FY${current.year} Q${current.quarter} · ${current.basis} · ${current.id}`;
    if (setValues) { setInputs(current); dirty = false; }
    const job = current.job || {};
    $('jobStatus').hidden = !job.message; $('jobStatus').textContent = job.message || ''; $('jobStatus').dataset.state = job.state || 'idle';
    renderPreview(); controls(); renderLibrary();
  }

  function tab(panel, focus = false) {
    document.querySelectorAll('.workspace-tabs [role=tab]').forEach(button => {
      const active = button.dataset.panel === panel;
      button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1;
      $(button.dataset.panel).hidden = !active; if (active && focus) button.focus();
    });
  }

  async function save() {
    if (!current || !dirty) return;
    if (current.financials_editable !== true) throw new Error('실적 표 저장 기능을 적용하려면 서버를 재시작해 주세요.');
    const data = await api('/save', {id: current.id, revision: current.revision, inputs: inputData(), financials: table.read()});
    current = data; dirty = false;
    const index = items.findIndex(p => p.id === data.id); if (index >= 0) items[index] = data;
    renderProject(false);
  }

  async function selectProject(id) {
    if (busy || current?.id === id) return;
    setBusy(true); message();
    try {
      await save(); current = await api('/project?id=' + encodeURIComponent(id));
      const url = new URL(location.href); url.searchParams.set('report', id); history.replaceState(null, '', url);
      renderProject(); tab('inputPanel'); schedulePoll();
    } finally { setBusy(false); }
  }

  function schedulePoll() {
    clearTimeout(pollTimer);
    if (items.some(p => p.job?.state === 'running') || running()) pollTimer = setTimeout(poll, 2500);
  }
  async function poll() {
    if (busy) { schedulePoll(); return; }
    try {
      items = (await api('')).items;
      if (running()) {
        const selectedId = current.id, previous = current.job;
        const latest = await api('/project?id=' + encodeURIComponent(selectedId));
        if (current?.id === selectedId && !busy && !dirty) {
          current = latest; renderProject();
          if (previous.action === 'generate' && current.job.state === 'done') tab('previewPanel');
        }
      }
      renderLibrary(); message();
    } catch (error) {
      message(new Error('작업 상태를 확인하지 못했습니다. 연결이 복구되면 다시 확인합니다. ' + error.message));
    } finally { schedulePoll(); }
  }

  async function action(kind) {
    if (!current || busy || running() || current.financials_editable !== true) return;
    setBusy(true); message();
    try {
      await save(); current = await api('/' + kind, {id: current.id, revision: current.revision});
      const index = items.findIndex(p => p.id === current.id); if (index >= 0) items[index] = current;
      renderProject(false); schedulePoll();
    } catch (error) { message(error); }
    finally { setBusy(false); }
  }

  function showCreate() {
    $('createError').textContent = ''; $('createDialog').showModal(); $('newTicker').focus();
  }
  const table = FinancialTable.create(() => { dirty = true; controls(); }, message);
  $('newYear').value = new Date().getFullYear();
  $('newQuarter').value = Math.max(1, Math.ceil((new Date().getMonth() + 1) / 3) - 1);
  $('newReport').addEventListener('click', showCreate); $('welcomeNew').addEventListener('click', showCreate);
  $('closeDialog').addEventListener('click', () => $('createDialog').close());
  $('createForm').addEventListener('submit', async event => {
    event.preventDefault(); if (busy) return; setBusy(true); $('createSubmit').disabled = true; $('createError').textContent = '';
    try {
      await save();
      const data = await api('/create', {ticker: $('newTicker').value.trim().toUpperCase(), year: Number($('newYear').value), quarter: Number($('newQuarter').value), basis: $('newBasis').value});
      items = (await api('')).items; current = data; dirty = false;
      const url = new URL(location.href); url.searchParams.set('report', data.id); history.replaceState(null, '', url);
      renderProject(); tab('inputPanel'); schedulePoll(); $('createDialog').close(); $('newTicker').value = '';
    } catch (error) { $('createError').textContent = error.message; }
    finally { $('createSubmit').disabled = false; setBusy(false); }
  });
  $('reportSearch').addEventListener('input', renderLibrary);
  fields.forEach(id => $(id).addEventListener('input', () => { dirty = true; controls(); }));
  $('saveInputs').addEventListener('click', async () => { if (busy || running()) return; setBusy(true); message(); try { await save(); } catch (error) { message(error); } finally { setBusy(false); } });
  $('generateReport').addEventListener('click', () => action('generate'));
  const tabs = [...document.querySelectorAll('.workspace-tabs [role=tab]')];
  tabs.forEach(button => {
    button.addEventListener('click', () => tab(button.dataset.panel));
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault(); const index = tabs.indexOf(button);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      tab(tabs[next].dataset.panel, true);
    });
  });
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  (async () => {
    try {
      items = (await api('')).items; renderLibrary();
      const requested = new URL(location.href).searchParams.get('report');
      if (requested) await selectProject(requested);
      else if (items.length) await selectProject(items[0].id);
      schedulePoll();
    } catch (error) { message(error); }
  })();
})();
