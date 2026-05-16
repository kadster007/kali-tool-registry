#!/usr/bin/env bash
# Setup the ShadowOps web UI on kadx.
#  - creates a Python venv with FastAPI + uvicorn
#  - installs a user systemd service that runs the app on 127.0.0.1:8080
#  - configures `tailscale serve` to expose it on the tailnet (HTTPS)
#
# Run:  bash ~/portable-pivot/backend/web/setup.sh

set -euo pipefail
WEB_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$WEB_DIR/.venv"
SERVICE_NAME="shadowops-web"
USER_SD_DIR="$HOME/.config/systemd/user"

echo "==> Creating Python venv at $VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip --quiet
"$VENV/bin/pip" install -r "$WEB_DIR/requirements.txt" --quiet
echo "   ok"

echo "==> Writing user systemd unit -> $USER_SD_DIR/${SERVICE_NAME}.service"
mkdir -p "$USER_SD_DIR"
cat > "$USER_SD_DIR/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=ShadowOps web UI
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$WEB_DIR
ExecStart=$VENV/bin/uvicorn app:app --host 127.0.0.1 --port 8080 --log-level info
Restart=on-failure
RestartSec=3
Environment=HOME=$HOME PATH=$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "$SERVICE_NAME".service
sleep 1
systemctl --user status "$SERVICE_NAME".service --no-pager | head -12 || true
echo

echo "==> Enabling user services on boot (loginctl enable-linger)"
loginctl enable-linger "$USER" 2>/dev/null || true

echo "==> Exposing via tailscale serve (HTTPS on the tailnet)"
sudo tailscale serve --bg --tls-terminated-tcp 443 tcp://127.0.0.1:8080 || true

cat <<EOF

================================================================
ShadowOps web UI is up.

Local URL:     http://127.0.0.1:8080
Tailnet HTTPS: https://\$(tailscale status --json 2>/dev/null | python3 -c \
  "import json,sys; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))" 2>/dev/null || echo kadx)

From the Fold 6: open the tailnet URL in your phone's browser. Bookmark it.

Manage the service:
  systemctl --user status  ${SERVICE_NAME}.service
  systemctl --user restart ${SERVICE_NAME}.service
  systemctl --user stop    ${SERVICE_NAME}.service
  journalctl --user -u     ${SERVICE_NAME} -f

Tear down tailscale serve:
  sudo tailscale serve reset
================================================================
EOF
