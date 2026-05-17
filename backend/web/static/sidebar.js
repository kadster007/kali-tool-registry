// Layout: left sidebar (vertical drag), bottom terminal (horizontal drag).
// All values persisted in localStorage. No auto-refresh of any panel.
window.shadowops = window.shadowops || {};

(function () {
  const layout = document.getElementById('layout');
  if (!layout) return;
  const left   = document.getElementById('sidebar-left');
  const middle = document.getElementById('middle');
  const term   = document.getElementById('terminal-panel');
  const rLeft  = document.getElementById('resizer-left');
  const rTerm  = document.getElementById('resizer-term');
  const btnL   = document.getElementById('toggle-left');
  const btnT   = document.getElementById('toggle-term');

  const LS_KEY = 'shadowops.layout.v2';
  const state = JSON.parse(localStorage.getItem(LS_KEY) || '{}');

  function save() { localStorage.setItem(LS_KEY, JSON.stringify(state)); }
  function apply() {
    if (state.leftPx)  layout.style.setProperty('--left-w',  state.leftPx  + 'px');
    if (state.rightPx) layout.style.setProperty('--right-w', state.rightPx + 'px');
    if (state.termPx)  layout.style.setProperty('--term-h',  state.termPx  + 'px');
    layout.classList.toggle('term-collapsed', !!state.termCollapsed);
  }
  apply();

  btnL?.addEventListener('click', () => { state.leftCollapsed = !state.leftCollapsed; apply(); save(); requestFit(); });
  btnT?.addEventListener('click', () => { state.termCollapsed = !state.termCollapsed; apply(); save(); requestFit(); });

  function requestFit() {
    if (window.shadowops.terminalFit) window.shadowops.terminalFit();
  }

  function attachDrag(handle, axis, sizeKey, minPx, maxPx, getNewSize) {
    if (!handle) return;
    handle.addEventListener('mousedown', start);
    handle.addEventListener('touchstart', start, { passive: false });
    handle.addEventListener('dblclick', () => { delete state[sizeKey]; layout.style.removeProperty(axis === 'x' ? '--left-w' : '--term-h'); save(); requestFit(); });

    function start(e) {
      e.preventDefault();
      const move = (ev) => {
        const point = (ev.touches ? ev.touches[0] : ev);
        const layoutRect = layout.getBoundingClientRect();
        const px = Math.max(minPx, Math.min(maxPx, getNewSize(point, layoutRect)));
        state[sizeKey] = px;
        if (axis === 'x')       layout.style.setProperty('--left-w', px + 'px');
        else if (axis === 'x-right') layout.style.setProperty('--right-w', px + 'px');
        else                    layout.style.setProperty('--term-h', px + 'px');
        requestFit();
      };
      const end = () => {
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', end);
        document.removeEventListener('touchmove', move);
        document.removeEventListener('touchend', end);
        document.body.classList.remove('dragging-x', 'dragging-y');
        save();
        requestFit();
      };
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', end);
      document.addEventListener('touchmove', move, { passive: false });
      document.addEventListener('touchend', end);
      document.body.classList.add(axis === 'x' ? 'dragging-x' : 'dragging-y');
    }
  }

  // Left sidebar drag — track X
  attachDrag(rLeft, 'x', 'leftPx', 180, 520,
    (pt, rect) => pt.clientX - rect.left);

  // Right sidebar drag — track X from the right edge
  const rRight = document.getElementById('resizer-right');
  attachDrag(rRight, 'x-right', 'rightPx', 180, 520,
    (pt, rect) => rect.right - pt.clientX);

  // Terminal drag — track Y (bottom of middle)
  attachDrag(rTerm, 'y', 'termPx', 120, 700,
    (pt, rect) => rect.bottom - pt.clientY);

  // Update kadx / phone (footer shortcuts)
  function showUpdate(html, hold=8000) {
    const el = document.getElementById('update-result');
    if (!el) return;
    el.innerHTML = html;
    el.style.display = 'block';
    if (hold) setTimeout(() => { el.style.display = 'none'; }, hold);
  }
  shadowops.updateKadx = async function(ev) {
    ev?.preventDefault();
    showUpdate('updating kadx…', 0);
    try {
      const r = await fetch('/api/update/kadx', { method: 'POST' });
      const d = await r.json();
      showUpdate((d.ok ? '✓ kadx updated · restarting' : '✗ kadx update failed') +
                 '<pre class="terminal-static" style="max-height:14em">' +
                 (d.output || '').replace(/[<&]/g, c => ({'<':'&lt;','&':'&amp;'}[c])) + '</pre>',
                 d.ok ? 15000 : 0);
    } catch (e) { showUpdate('✗ error: ' + e.message, 0); }
  };
  shadowops.updatePhone = async function(ev) {
    ev?.preventDefault();
    showUpdate('updating phone via tunnel…', 0);
    try {
      const r = await fetch('/api/update/phone', { method: 'POST' });
      const d = await r.json();
      showUpdate((d.ok ? '✓ phone updated' : '✗ phone update failed') +
                 '<pre class="terminal-static" style="max-height:14em">' +
                 (d.output || '').replace(/[<&]/g, c => ({'<':'&lt;','&':'&amp;'}[c])) + '</pre>',
                 d.ok ? 12000 : 0);
    } catch (e) { showUpdate('✗ error: ' + e.message, 0); }
  };

  // Show pivot action results compactly
  document.body.addEventListener('htmx:afterRequest', (e) => {
    const cfg = e.detail.requestConfig || {};
    if (!cfg.path) return;
    if (cfg.path.startsWith('/api/pivot/') && cfg.verb === 'post') {
      const target = document.getElementById('pivot-action-result');
      let body = null;
      try { body = JSON.parse(e.detail.xhr.responseText); } catch (_) {}
      const ok = e.detail.successful && body && body.ok !== false;
      if (target) target.textContent = ok
        ? '✓ ' + (body?.output?.split('\n').slice(-3).join(' ').trim() || 'ok')
        : '⚠ ' + (body?.output || 'failed');
      // Manually refresh the consolidated status panel (no auto-refresh elsewhere)
      htmx.ajax('GET', '/api/status_panel',
                { target: '#status-panel', swap: 'innerHTML' });
    }
  });
})();
