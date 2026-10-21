(() => {
  const KEY = 'finance-theme';
  let saved; try { saved = localStorage.getItem(KEY); } catch (_) {}
  const media = matchMedia('(prefers-color-scheme: dark)');
  let preference = saved === 'light' || saved === 'dark' ? saved : null;
  function apply(theme) {
    const dark = theme === 'dark';
    document.documentElement.dataset.theme = theme;
    if (document.body) document.body.classList.toggle('dark', dark);
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      button.textContent = dark ? '☀' : '☾';
      button.setAttribute('aria-label', dark ? '라이트 모드로 전환' : '다크 모드로 전환');
      button.title = button.getAttribute('aria-label');
      button.setAttribute('aria-pressed', String(dark));
    });
    window.dispatchEvent(new CustomEvent('finance-theme-change', {detail:{dark}}));
  }
  apply(preference || (media.matches ? 'dark' : 'light'));
  const icon = '<svg class="update-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 6.1A8 8 0 0 1 20 12M4 12a8 8 0 0 0 13.9 5.9"/></svg>';
  function update(button, state, label, message, status) {
    if (!button) return;
    const unavailable = button.dataset.unavailable === 'true';
    button.dataset.state = state;
    button.disabled = unavailable || state === 'running';
    button.setAttribute('aria-busy', String(state === 'running'));
    button.innerHTML = icon;
    const text = document.createElement('span'); text.textContent = label; button.append(text);
    if (status) { status.dataset.state = state; status.textContent = message || ''; }
  }
  function remember(message) { try { sessionStorage.setItem('finance-update-success', message); } catch (_) {} }
  window.FinanceUI = {update, remember, isDark:() => document.documentElement.dataset.theme === 'dark'};
  document.addEventListener('click', event => {
    if (!event.target.closest('[data-theme-toggle]')) return;
    preference = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(KEY, preference); } catch (_) {}
    apply(preference);
  });
  window.addEventListener('storage', event => { if (event.key === KEY) { preference = event.newValue === 'light' || event.newValue === 'dark' ? event.newValue : null; apply(preference || (media.matches ? 'dark' : 'light')); } });
  media.addEventListener('change', () => { if (!preference) apply(media.matches ? 'dark' : 'light'); });
  function ready() {
    apply(document.documentElement.dataset.theme);
    // Finance workspaces share navigation and the saved theme.
    const earnings = ['/', '/index.html', '/earnings'].includes(location.pathname);
    const customs = ['/customs', '/customs/'].includes(location.pathname);
    const usCustoms = ['/us-customs', '/us-customs/'].includes(location.pathname);
    const jpCustoms = ['/jp-customs', '/jp-customs/'].includes(location.pathname);
    const watchlist = ['/watchlist', '/watchlist/'].includes(location.pathname);
    const anyCustoms = customs || usCustoms || jpCustoms;
    const weeklyPages = [['/weekly', '스크리너'], ['/weekly/recap', '시장 Recap'], ['/weekly/industries', '산업 분류'], ['/weekly/sector-etfs', 'ETF 설정']];
    const aliases = {'/recap':'/weekly/recap', '/recap.html':'/weekly/recap', '/industries':'/weekly/industries', '/sector-etfs':'/weekly/sector-etfs', '/sector-classifications':'/weekly/sector-etfs', '/weekly/sector-classifications':'/weekly/sector-etfs', '/weekly/':'/weekly'};
    const active = aliases[location.pathname] || location.pathname;
    let nav = document.querySelector('.finance-nav');
    if (!nav) {
      nav = document.createElement('nav'); nav.className = 'finance-nav'; nav.setAttribute('aria-label', '화면 이동');
      const actions = document.querySelector('.topbar-actions');
      if (actions) actions.prepend(nav);
      else {
        const header = document.createElement('header'); header.className = 'finance-header workspace-bar';
        const brand = document.createElement('a'); brand.className = 'finance-brand'; brand.href = '/';
        brand.innerHTML = '<span class="brand-mark" aria-hidden="true">▥</span><h1>Finance</h1>';
        header.append(brand, nav); document.body.prepend(header);
      }
    }
    nav.replaceChildren();
    for (const [href, label, selected] of [['/', '실적 리포트', earnings], ['/weekly', '위클리', !earnings && !anyCustoms && !watchlist], ['/watchlist', '관심종목', watchlist], ['/customs', '수출입(한국)', customs], ['/us-customs', '수출입(미국)', usCustoms], ['/jp-customs', '수출입(일본)', jpCustoms]]) {
      const link = document.createElement('a'); link.href = href; link.className = 'navbtn'; link.textContent = label;
      if (selected) link.setAttribute('aria-current', 'page'); nav.append(link);
    }
    if (!earnings && !anyCustoms && !watchlist && !document.querySelector('.topbar-actions')) {
      const subnav = document.createElement('nav'); subnav.className = 'weekly-subnav'; subnav.setAttribute('aria-label', '위클리 메뉴');
      const label = document.createElement('span'); label.className = 'section-label'; label.textContent = 'WEEKLY'; subnav.append(label);
      for (const [href, text] of weeklyPages) {
        const link = document.createElement('a'); link.href = href; link.className = 'navbtn'; link.textContent = text;
        if (href === active) link.setAttribute('aria-current', 'page'); subnav.append(link);
      }
      const header = document.querySelector('.finance-header'); header?.after(subnav);
    }
    document.querySelectorAll('.update-button').forEach(button => { if (!button.dataset.state) update(button, 'idle', button.textContent.trim()); });
    document.querySelectorAll('.chip').forEach(button => {
      button.setAttribute('aria-pressed', String(button.classList.contains('active')));
      new MutationObserver(() => button.setAttribute('aria-pressed', String(button.classList.contains('active')))).observe(button, {attributes:true,attributeFilter:['class']});
    });
    let message; try { message = sessionStorage.getItem('finance-update-success'); sessionStorage.removeItem('finance-update-success'); } catch (_) {}
    if (message) { const toast = document.createElement('div'); toast.className = 'ui-toast'; toast.setAttribute('role', 'status'); toast.textContent = '✓ ' + message; document.body.append(toast); setTimeout(() => toast.remove(), 6000); }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready); else ready();
})();
