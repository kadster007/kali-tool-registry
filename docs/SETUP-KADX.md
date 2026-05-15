# Setup — kadx (the execution engine)

One-time install on a fresh Kali workstation. Assumes you have sudo, git, and Tailscale already.

## 1. Clone the repo

```bash
git clone git@github.com:kadster007/kali-tool-registry.git ~/portable-pivot
cd ~/portable-pivot
```

## 2. OpenSSH on port 2222, hardened

```bash
sudo bash backend/openssh-setup.sh        # binds to Tailscale IP only, key-only auth
sudo bash backend/openssh-add-lan.sh      # also bind to LAN IP for at-home fallback
```

Verify with `ss -tlnp | grep :2222` — should show two listeners (Tailscale IPv4 + LAN IPv4), no `0.0.0.0`.

## 3. Symlink the wrapper onto PATH

```bash
ln -sf "$PWD/backend/pivot/pivot" ~/.local/bin/pivot
ln -sf "$PWD/backend/pivot-status.sh" ~/pivot-status.sh
```

## 4. **Make PATH visible to SSH non-interactive commands**

Add this to `~/.zshenv` (creating it if it doesn't exist):

```bash
cat > ~/.zshenv <<'EOF'
# Make ~/.local/bin visible to non-interactive SSH commands.
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) export PATH="$HOME/.local/bin:$PATH" ;;
esac
EOF
```

**Why this matters:** when the Fold 6 runs `ssh kadx@... 'pivot nmap ...'`, sshd spawns a non-interactive zsh that does NOT source `~/.zshrc` (only `~/.zshenv`). Without this, the `pivot` command won't be found and you'll see `zsh: command not found: pivot`.

If you use bash instead of zsh, the equivalent file is `~/.bashrc` (yes, bash *does* source it for non-interactive non-login if `BASH_ENV` is set; otherwise edit `/etc/environment` or set `IdentityFile` PATH in the Fold 6's SSH command).

## 5. Verify

```bash
# Should print the pivot help:
env -i HOME="$HOME" USER="$USER" /usr/bin/zsh -c 'pivot help' | head -3
```

If that prints the help, you're set. If it says `command not found`, double-check step 4.

## 6. Authorized keys

Add the Fold 6's ed25519 public key (`~/.ssh/id_ed25519.pub` on the phone) to `~/.ssh/authorized_keys` on kadx. Mode 0600.

## 7. Tailscale

If not already done:
```bash
sudo bash backend/tailscale-setup.sh
```
Approve the exit-node advertisement at https://login.tailscale.com/admin/machines.

---

You should now be able to:
- SSH from the phone to kadx on port 2222 with key auth.
- Run `pivot help` (locally on kadx, and via `ssh kadx@... 'pivot help'`).
- See `ss -tlnp | grep :2222` showing tailnet + LAN listeners only.
