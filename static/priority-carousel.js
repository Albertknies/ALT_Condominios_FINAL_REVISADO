(() => {
  const root = document.getElementById('priorityCarousel');
  if (!root) return;
  const slides = Array.from(root.querySelectorAll('[data-slide]'));
  const tabs = Array.from(root.querySelectorAll('[data-slide-index]'));
  const status = root.querySelector('#carouselStatus');
  let current = 0;
  const show = index => {
    current = (index + slides.length) % slides.length;
    slides.forEach((slide, i) => { slide.hidden = i !== current; });
    tabs.forEach((tab, i) => { tab.setAttribute('aria-selected', String(i === current)); });
    status.textContent = `${current + 1} de ${slides.length}: ${tabs[current].textContent}`;
  };
  root.querySelectorAll('[data-slide-step]').forEach(button => button.addEventListener('click', () => show(current + Number(button.dataset.slideStep))));
  tabs.forEach((tab, i) => {
    tab.addEventListener('click', () => show(i));
    tab.addEventListener('keydown', event => {
      if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
        event.preventDefault();
        show(current + (event.key === 'ArrowRight' ? 1 : -1));
        tabs[current].focus();
      }
    });
  });
  let touchStart = null;
  root.addEventListener('touchstart', event => { touchStart = event.touches.length === 1 ? { x: event.touches[0].clientX, y: event.touches[0].clientY } : null; }, { passive: true });
  root.addEventListener('touchend', event => {
    if (!touchStart || !event.changedTouches.length) return;
    const dx = event.changedTouches[0].clientX - touchStart.x;
    const dy = event.changedTouches[0].clientY - touchStart.y;
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) show(current + (dx < 0 ? 1 : -1));
    touchStart = null;
  }, { passive: true });
})();
