#!/usr/bin/env bash
# Installs Gmail Notifier for the current user (no root files except apt packages).
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/share/gmail-notifier"
BIN="$HOME/.local/bin/gmail-notifier"
EXT="ubuntu-appindicators@ubuntu.com"

echo "==> Installing desktop libraries (asks for your password once)"
sudo apt-get install -y python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 \
  gir1.2-notify-0.7 gir1.2-secret-1 libnotify-bin gnome-shell-extension-appindicator

echo "==> Removing the old Go version, if present"
systemctl --user disable --now gmail-notifier.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/gmail-notifier.service"
if dpkg -s gmail-notifier-2 >/dev/null 2>&1; then sudo apt-get remove -y gmail-notifier-2; fi
pkill -x gmail-notifier 2>/dev/null || true   # old Go binary (exact process name)
pkill -f "^/usr/bin/python3 -m gmail_notifier" 2>/dev/null || true

echo "==> Copying the app to $DEST"
rm -rf "$DEST"
mkdir -p "$DEST" "$(dirname "$BIN")"
cp -r "$SRC/gmail_notifier" "$DEST/"
find "$DEST" -name __pycache__ -prune -exec rm -rf {} +

cat > "$BIN" <<LAUNCHER
#!/bin/sh
cd "$DEST" && PYTHONPATH="$DEST" exec /usr/bin/python3 -m gmail_notifier "\$@"
LAUNCHER
chmod +x "$BIN"

mkdir -p "$HOME/.local/share/icons/hicolor/scalable/apps" "$HOME/.local/share/applications" "$HOME/.config/autostart"
cp "$SRC/gmail_notifier/icons/gmail-notifier.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/gmail-notifier.svg"
DESKTOP="[Desktop Entry]
Type=Application
Name=Gmail Notifier
Comment=Tray icon and notifications for your Gmail accounts
Exec=$BIN
Icon=gmail-notifier
Terminal=false
Categories=Network;Email;
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5"
echo "$DESKTOP" > "$HOME/.local/share/applications/gmail-notifier.desktop"
echo "$DESKTOP" > "$HOME/.config/autostart/gmail-notifier.desktop"   # start at every login

if command -v gnome-extensions >/dev/null 2>&1; then
  if ! gnome-extensions info "$EXT" 2>/dev/null | grep -qE "(State|Enabled): (ENABLED|ACTIVE|Yes)"; then
    echo "==> Enabling Ubuntu's tray-icon extension ($EXT)"
    gnome-extensions enable "$EXT" 2>/dev/null || \
      echo "   Couldn't enable it automatically – open the 'Extensions' app and turn on 'Ubuntu AppIndicators'."
  fi
fi

if ! "$BIN" check >/dev/null 2>&1; then
  echo
  echo "==> Let's add your Gmail accounts"
  while true; do
    "$BIN" add-account || true
    read -r -p "Add another account? [y/N] " again || again=""
    [[ "$again" =~ ^[Yy] ]] || break
  done
fi

echo "==> Starting Gmail Notifier"
setsid "$BIN" >/dev/null 2>&1 < /dev/null &
echo
echo "Done. Look for the envelope icon in the top bar. It will also start automatically when you log in."
echo "Commands:  gmail-notifier check | add-account | remove-account EMAIL | test-notification"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "(Open a new terminal so 'gmail-notifier' is on your PATH.)";; esac
