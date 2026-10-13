(() => {
  const allowed = new Set(['validPpci', 'cxData', 'fimMandato', 'recarga', 'segData', 'dedData']);
  const field = new URLSearchParams(window.location.search).get('item');
  if (!allowed.has(field)) return;
  const input = document.getElementById(field);
  if (!input) return;
  const block = input.closest('.document-item') || input.closest('section') || input.closest('.field');
  if (!block) return;
  block.classList.add('alt-deadline-focus');
  const note = document.createElement('div');
  note.className = 'alt-deadline-notice';
  note.setAttribute('role', 'status');
  note.textContent = 'Atualize este item e clique em “Salvar atualização” para registrar a alteração.';
  block.prepend(note);
  requestAnimationFrame(() => {
    block.scrollIntoView({ behavior: 'instant', block: 'start' });
    if (input.getClientRects().length) input.focus({ preventScroll: true });
  });
})();
