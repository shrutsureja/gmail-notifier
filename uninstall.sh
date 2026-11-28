#!/usr/bin/env bash
# Removes the app. Keeps your settings unless you pass --purge.
set -euo pipefail
pkill -f "^/usr/bin/python3 -m gmail_notifier" 2>/dev/null || true
rm -rf "$HOME/.local/share/gmail-notifier" "$HOME/.local/bin/gmail-notifier" \
       "$HOME/.config/autostart/gmail-notifier.desktop" \
       "$HOME/.local/share/applications/gmail-notifier.desktop" \
       "$HOME/.local/share/icons/hicolor/scalable/apps/gmail-notifier.svg"
if [[ "${1:-}" == "--purge" ]]; then
  rm -rf "$HOME/.config/gmail-notifier" "$HOME/.local/state/gmail-notifier"
  echo "Settings removed. App passwords stay in the keyring: open 'Passwords and Keys' and delete the 'Gmail Notifier' entries."
fi
echo "Gmail Notifier removed."
