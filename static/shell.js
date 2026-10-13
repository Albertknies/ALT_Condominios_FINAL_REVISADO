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
