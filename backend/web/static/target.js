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

  // Initial pull (single request — no auto-poll)
  pullFromPhone();
})();
