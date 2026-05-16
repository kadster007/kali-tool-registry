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

  // Phase preset buttons type the command into the current shell
  shadowops.runPreset = function (cmd) {
    if (!ws || ws.readyState !== 1) {
      connect('local');
      // Wait for connection then send
      setTimeout(() => shadowops.runPreset(cmd), 600);
      return;
    }
    ws.send(cmd + '\r');
    term.focus();
  };

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
