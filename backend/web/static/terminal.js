// xterm.js + WebSocket — handles kadx shell and phone SSH modes.
window.shadowops = window.shadowops || {};

(function () {
  const host = document.getElementById('terminal-host');
  const modeLabel = document.getElementById('term-mode');
  if (!host) return;

  const term = new Terminal({
    convertEol: true,
    cursorBlink: true,
    fontFamily: 'ui-monospace, "JetBrains Mono", "Fira Code", Consolas, monospace',
    fontSize: 13,
    theme: { background: '#010409', foreground: '#e6edf3', cursor: '#58a6ff' },
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(host);
  setTimeout(() => { try { fit.fit(); } catch (e) {} }, 50);

  let ws = null;
  let currentMode = 'local';

  function connect(mode) {
    if (ws) { try { ws.close(); } catch (_) {} ws = null; }
    currentMode = mode;
    if (modeLabel) modeLabel.textContent = (mode === 'phone' ? 'phone' : 'kadx');
    term.reset();
    const proto = (location.protocol === 'https:') ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/terminal?cmd=${encodeURIComponent(mode)}`);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
      sendResize();
      term.focus();
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data === 'string') {
        term.write(ev.data);
      } else {
        const decoder = new TextDecoder('utf-8');
        term.write(decoder.decode(new Uint8Array(ev.data)));
      }
    };
    ws.onclose = () => {
      term.write('\r\n\x1b[33m[session ended — click "kadx shell" or "SSH to phone" to restart]\x1b[0m\r\n');
    };
    ws.onerror = () => {
      term.write('\r\n\x1b[31m[ws error]\x1b[0m\r\n');
    };
  }

  function sendResize() {
    if (!ws || ws.readyState !== 1) return;
    try {
      ws.send(JSON.stringify({ type: 'resize', rows: term.rows, cols: term.cols }));
    } catch (_) {}
  }

  term.onData((data) => {
    if (ws && ws.readyState === 1) ws.send(data);
  });

  // Wire buttons
  document.getElementById('term-local')?.addEventListener('click', () => connect('local'));
  document.getElementById('term-phone')?.addEventListener('click', () => connect('phone'));
  document.getElementById('term-reset')?.addEventListener('click', () => connect(currentMode));
  document.getElementById('open-phone-shell')?.addEventListener('click', () => {
    connect('phone');
    document.getElementById('layout')?.classList.remove('term-collapsed');
  });

  // ----- preset runner: accepts the preset object (or a raw command string)
  // Substitutes {target}, {ports}, and other named params from:
  //   1. The target/ports widget at top of main (user-editable)
  //   2. preset.param_defaults
  //   3. A prompt() if still missing.
  shadowops.runPreset = function (preset) {
    // Allow legacy callers that pass a string
    if (typeof preset === 'string') {
      sendCmd(preset);
      return;
    }
    let cmd = preset.command || '';
    const tInput = document.getElementById('target-input');
    const pInput = document.getElementById('ports-input');
    const widgetTarget = tInput && tInput.value.trim();
    const widgetPorts  = pInput && pInput.value.trim();

    const params = preset.params || extractTokens(cmd);
    for (const p of params) {
      let val = null;
      if (p === 'target' && widgetTarget) val = widgetTarget;
      else if (p === 'ports' && widgetPorts) val = widgetPorts;
      else if (preset.param_defaults && p in preset.param_defaults) {
        val = preset.param_defaults[p];
      }
      if (val == null || val === '') {
        val = window.prompt(`Value for {${p}}?`, '');
        if (val == null) return;  // cancelled
      }
      cmd = cmd.split(`{${p}}`).join(val);
    }

    if (preset.requires_root && !/^\s*sudo\s/.test(cmd)) {
      cmd = 'sudo ' + cmd;
    }

    // Where should it run? If the preset declares runs_on='phone', we need to
    // be in the phone shell (SSH'd via the -R 8022 tunnel). Otherwise kadx.
    const wantedMode = (preset.runs_on === 'phone') ? 'phone' : 'local';
    if (currentMode !== wantedMode) {
      // Switch terminal mode then run; small delay so the new shell prompt
      // is ready to accept input.
      connect(wantedMode);
      setTimeout(() => sendCmd(cmd), 900);
    } else {
      sendCmd(cmd);
    }
  };

  function extractTokens(s) {
    const out = []; const seen = new Set();
    const re = /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g;
    let m;
    while ((m = re.exec(s)) !== null) {
      if (!seen.has(m[1])) { seen.add(m[1]); out.push(m[1]); }
    }
    return out;
  }

  function sendCmd(cmd) {
    if (!ws || ws.readyState !== 1) {
      connect('local');
      setTimeout(() => sendCmd(cmd), 600);
      return;
    }
    ws.send(cmd + '\r');
    term.focus();
  }
  shadowops._sendCmd = sendCmd;

  // Refit on window/sidebar resize
  let fitTimer = null;
  function deferredFit() {
    clearTimeout(fitTimer);
    fitTimer = setTimeout(() => {
      try { fit.fit(); sendResize(); } catch (e) {}
    }, 60);
  }
  window.addEventListener('resize', deferredFit);
  shadowops.terminalFit = deferredFit;

  // Initial connection
  connect('local');
})();
