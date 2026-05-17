// Target / ports widget — auto-fills from /api/phone_info, used by preset runner.
window.shadowops = window.shadowops || {};

(function () {
  const tIn = document.getElementById('target-input');
  const pIn = document.getElementById('ports-input');
  const hint = document.getElementById('target-hint');
  const btn = document.getElementById('target-from-phone');
  if (!tIn) return;

  function setHint(msg, cls = 'small') {
    if (!hint) return;
    hint.className = 'target-hint hint ' + cls;
    hint.textContent = msg;
  }

  async function pullFromPhone() {
    setHint('checking Fold 6…');
    try {
      const r = await fetch('/api/phone_info?force=1', { cache: 'no-store' });
      const info = await r.json();
      if (!info.reachable) {
        setHint('Fold 6 unreachable — fill target manually (the pivot tunnel must be up with -R 8022 for auto-fill).');
        return;
      }
      if (info.subnet) {
        // Only auto-overwrite if user hasn't typed something
        if (!tIn.value.trim() || tIn.dataset.fromPhone === '1') {
          tIn.value = info.subnet;
          tIn.dataset.fromPhone = '1';
        }
        setHint(`Fold 6: ${info.connection} · ${info.ssid || ''} · phone IP ${info.ip}`);
      } else {
        setHint(`Fold 6: ${info.connection} — no subnet (cellular or unknown)`);
      }
    } catch (e) {
      setHint('error fetching phone info — ' + e.message);
    }
  }

  // User-typed values shouldn't get overwritten on the next refresh
  tIn.addEventListener('input', () => { delete tIn.dataset.fromPhone; });

  btn?.addEventListener('click', pullFromPhone);

  // Edit toggle: make Target / Ports inputs writable on demand only.
  // Default state is readonly + inputmode=none, which on mobile keeps the
  // soft keyboard down even when the field is tapped.
  const editBtn = document.getElementById('target-edit');
  function setEditable(on) {
    [tIn, pIn].forEach(el => {
      if (!el) return;
      if (on) {
        el.removeAttribute('readonly');
        el.removeAttribute('inputmode');
      } else {
        el.setAttribute('readonly', '');
        el.setAttribute('inputmode', 'none');
        el.blur();
      }
    });
    if (editBtn) editBtn.textContent = on ? '✓ Lock' : '✏ Edit';
  }
  editBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    const editing = !tIn.hasAttribute('readonly');
    setEditable(!editing);
    if (!editing) tIn.focus();
  });
  // Auto-lock when user taps away from the inputs (so the keyboard stays
  // closed during subsequent preset clicks)
  document.addEventListener('click', (e) => {
    if (tIn.hasAttribute('readonly')) return;  // already locked
    if (e.target === tIn || e.target === pIn || e.target === editBtn) return;
    setEditable(false);
  });

  // Initial pull (single request — no auto-poll)
  pullFromPhone();
})();
