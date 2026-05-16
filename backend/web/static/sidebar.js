// Drag-resizable sidebars + collapse toggles.
// Persists widths + collapsed state in localStorage.

(function () {
  const layout = document.getElementById('layout');
  const left = document.getElementById('sidebar-left');
  const right = document.getElementById('sidebar-right');
  const rLeft = document.getElementById('resizer-left');
  const rRight = document.getElementById('resizer-right');
  const btnL = document.getElementById('toggle-left');
  const btnR = document.getElementById('toggle-right');

  if (!layout) return;

  // --- restore state from localStorage --------------------------------------
  const LS_KEY = 'shadowops.layout.v1';
  const state = JSON.parse(localStorage.getItem(LS_KEY) || '{}');
  function applyState() {
    if (state.leftPx)  layout.style.setProperty('--left-w',  state.leftPx + 'px');
    if (state.rightPx) layout.style.setProperty('--right-w', state.rightPx + 'px');
    layout.classList.toggle('left-collapsed',  !!state.leftCollapsed);
    layout.classList.toggle('right-collapsed', !!state.rightCollapsed);
  }
  function save() { localStorage.setItem(LS_KEY, JSON.stringify(state)); }
  applyState();

  // --- collapse toggles -----------------------------------------------------
  btnL?.addEventListener('click', () => {
    state.leftCollapsed = !state.leftCollapsed;
    applyState(); save();
  });
  btnR?.addEventListener('click', () => {
    state.rightCollapsed = !state.rightCollapsed;
    applyState(); save();
  });

  // --- drag to resize -------------------------------------------------------
  function attachDrag(handle, side) {
    if (!handle) return;
    handle.addEventListener('mousedown', startDrag);
    handle.addEventListener('touchstart', startDrag, { passive: false });

    function startDrag(e) {
      e.preventDefault();
      const move = (ev) => {
        const x = (ev.touches ? ev.touches[0].clientX : ev.clientX);
        const layoutRect = layout.getBoundingClientRect();
        let newW;
        if (side === 'left') {
          newW = Math.max(140, Math.min(500, x - layoutRect.left));
          layout.style.setProperty('--left-w', newW + 'px');
          state.leftPx = newW;
        } else {
          newW = Math.max(140, Math.min(500, layoutRect.right - x));
          layout.style.setProperty('--right-w', newW + 'px');
          state.rightPx = newW;
        }
      };
      const end = () => {
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', end);
        document.removeEventListener('touchmove', move);
        document.removeEventListener('touchend', end);
        document.body.classList.remove('dragging');
        save();
      };
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', end);
      document.addEventListener('touchmove', move, { passive: false });
      document.addEventListener('touchend', end);
      document.body.classList.add('dragging');
    }
  }
  attachDrag(rLeft,  'left');
  attachDrag(rRight, 'right');

  // --- htmx pivot-action toast feedback ------------------------------------
  document.body.addEventListener('htmx:afterRequest', (e) => {
    const path = (e.detail.requestConfig?.path) || '';
    if (!path.startsWith('/api/pivot/')) return;
    const target = document.getElementById('start-result');
    let body = '';
    try { body = JSON.parse(e.detail.xhr.responseText); } catch (_) {}
    let msg = '';
    if (e.detail.successful) {
      msg = (body && body.ok) ? '✓ Action completed' : '⚠ Action returned: ' + (body?.output || '?');
    } else {
      msg = '✗ Action failed (' + e.detail.xhr.status + ')';
    }
    if (target) target.textContent = msg;
    // Trigger an immediate refresh of the left panel after a pivot action
    setTimeout(() => htmx.trigger('#sidebar-left', 'refresh'), 1500);
  });
  htmx.on('#sidebar-left', 'refresh', () => {
    htmx.ajax('GET', '/api/left_panel', { target: '#sidebar-left', swap: 'innerHTML' });
  });
})();
