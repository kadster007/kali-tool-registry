// User preferences — stored in localStorage, applied client-side.
// Settings panel: ⚙ in header opens it.
window.shadowops = window.shadowops || {};

const IS_MOBILE = /android|iphone|ipad|mobile/i.test(navigator.userAgent || '');
const PREFS_KEY = 'shadowops.prefs.v1';

const DEFAULTS = {
  autoFocusTerminal: !IS_MOBILE,        // mobile: off (no keyboard popup); desktop: on
  showKeyboardHelper: IS_MOBILE,        // mobile: on; desktop: off
  targetEditable: !IS_MOBILE,           // mobile: locked; desktop: editable
  hostsLiveOnly: true,                  // default: hide hosts not in 'up' state
};

function loadPrefs() {
  try {
    const stored = JSON.parse(localStorage.getItem(PREFS_KEY) || '{}');
    return Object.assign({}, DEFAULTS, stored);
  } catch (_) { return Object.assign({}, DEFAULTS); }
}

function savePrefs(p) {
  localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  shadowops.prefs = p;
  applyPrefs();
}

shadowops.prefs = loadPrefs();

function applyPrefs() {
  const p = shadowops.prefs;
  // Toggle helper bar visibility
  const helper = document.getElementById('terminal-keys');
  if (helper) helper.style.display = p.showKeyboardHelper ? '' : 'none';
  // Target inputs editable / readonly
  document.querySelectorAll('#target-input, #ports-input').forEach(el => {
    if (p.targetEditable) {
      el.removeAttribute('readonly');
      el.removeAttribute('inputmode');
    } else {
      el.setAttribute('readonly', '');
      el.setAttribute('inputmode', 'none');
    }
  });
  // Hosts live-only filter — toggle CSS class on the table
  document.querySelectorAll('table.host-table').forEach(t => {
    t.classList.toggle('hide-down', p.hostsLiveOnly);
  });
}

shadowops.applyPrefs = applyPrefs;

function buildSettingsPanel() {
  const wrap = document.createElement('div');
  wrap.id = 'settings-overlay';
  wrap.innerHTML = `
    <div class="settings-card">
      <div class="settings-head">
        <h3>Settings</h3>
        <button class="icon-btn-sm" id="settings-close">✕</button>
      </div>
      <div class="settings-body">
        <label class="setting-row">
          <input type="checkbox" id="opt-auto-focus" ${shadowops.prefs.autoFocusTerminal ? 'checked' : ''}>
          <span>
            <strong>Auto-focus terminal</strong>
            <span class="hint small">On mobile, this opens the soft keyboard whenever the terminal connects or runs a preset. Off by default on phones.</span>
          </span>
        </label>
        <label class="setting-row">
          <input type="checkbox" id="opt-kbd-helper" ${shadowops.prefs.showKeyboardHelper ? 'checked' : ''}>
          <span>
            <strong>Keyboard helper bar</strong>
            <span class="hint small">Tab / arrows / Ctrl chords above the terminal. Useful on mobile.</span>
          </span>
        </label>
        <label class="setting-row">
          <input type="checkbox" id="opt-target-editable" ${shadowops.prefs.targetEditable ? 'checked' : ''}>
          <span>
            <strong>Target / Ports inputs editable by default</strong>
            <span class="hint small">If off, the inputs are locked until you tap ✏ Edit. On mobile, keeping these locked prevents the soft keyboard from auto-popping.</span>
          </span>
        </label>
        <label class="setting-row">
          <input type="checkbox" id="opt-hosts-live" ${shadowops.prefs.hostsLiveOnly ? 'checked' : ''}>
          <span>
            <strong>Hide non-live hosts on /hosts</strong>
            <span class="hint small">arp-scan-style scans return 256 entries for a /24 even if 250 are dead. This hides the dead ones.</span>
          </span>
        </label>
      </div>
      <div class="settings-foot">
        <button class="btn" id="settings-save">Save</button>
        <button class="btn-outline" id="settings-reset">Reset to defaults</button>
      </div>
    </div>`;
  document.body.appendChild(wrap);

  document.getElementById('settings-close').onclick = () => wrap.remove();
  document.getElementById('settings-save').onclick = () => {
    savePrefs({
      autoFocusTerminal: document.getElementById('opt-auto-focus').checked,
      showKeyboardHelper: document.getElementById('opt-kbd-helper').checked,
      targetEditable: document.getElementById('opt-target-editable').checked,
      hostsLiveOnly: document.getElementById('opt-hosts-live').checked,
    });
    wrap.remove();
  };
  document.getElementById('settings-reset').onclick = () => {
    savePrefs(Object.assign({}, DEFAULTS));
    wrap.remove();
  };
  wrap.addEventListener('click', (e) => { if (e.target === wrap) wrap.remove(); });
}

shadowops.openSettings = buildSettingsPanel;

// Apply on every page load and whenever HTMX swaps panels
document.addEventListener('DOMContentLoaded', applyPrefs);
document.body.addEventListener('htmx:afterSwap', applyPrefs);
