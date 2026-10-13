(() => {
  const toggle = document.getElementById('menuToggle');
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.querySelector('.alt-menu-backdrop');
  const nav = document.getElementById('altNavigation');
  if (!toggle || !sidebar || !backdrop || !nav) return;
  const setOpen = open => {
    document.body.classList.toggle('menu-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    backdrop.hidden = !open;
  };
  toggle.addEventListener('click', () => setOpen(!document.body.classList.contains('menu-open')));
  backdrop.addEventListener('click', () => { setOpen(false); toggle.focus(); });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && document.body.classList.contains('menu-open')) {
      setOpen(false); toggle.focus();
    }
  });
  nav.querySelectorAll('a').forEach(link => link.addEventListener('click', () => setOpen(false)));
  const desktop = window.matchMedia('(min-width: 901px)');
  desktop.addEventListener('change', () => setOpen(false));
  try { nav.scrollTop = Number(sessionStorage.getItem('alt-menu-scroll') || 0); } catch (_) {}
  nav.addEventListener('scroll', () => {
    try { sessionStorage.setItem('alt-menu-scroll', String(nav.scrollTop)); } catch (_) {}
  }, { passive: true });
})();
(() => {
  const nav = document.getElementById('altNavigation');
  const search = document.getElementById('altMenuSearch');
  const empty = document.getElementById('altNavEmpty');
  const collapse = document.getElementById('altCollapse');
  if (!nav || !search || !empty || !collapse) return;
  const links = Array.from(nav.querySelectorAll('.side-link'));
  const normalize = text => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  search.addEventListener('input', () => {
    const term = normalize(search.value.trim());
    let count = 0;
    links.forEach(link => { link.hidden = !normalize(link.textContent).includes(term); if (!link.hidden) count++; });
    nav.querySelectorAll('.nav-section').forEach(section => { section.hidden = Boolean(term); });
    empty.hidden = count > 0;
  });
  const setCompact = compact => {
    document.body.classList.toggle('alt-menu-compact', compact);
    collapse.setAttribute('aria-expanded', String(!compact));
    collapse.setAttribute('aria-label', compact ? 'Expandir menu' : 'Recolher menu');
    collapse.textContent = compact ? '›' : '‹';
    links.forEach(link => { if (compact) link.setAttribute('title', link.textContent.trim()); else link.removeAttribute('title'); });
  };
  try { setCompact(localStorage.getItem('alt-menu-compact') === 'true'); } catch (_) {}
  collapse.addEventListener('click', () => {
    const compact = !document.body.classList.contains('alt-menu-compact');
    setCompact(compact);
    try { localStorage.setItem('alt-menu-compact', String(compact)); } catch (_) {}
  });
})();
