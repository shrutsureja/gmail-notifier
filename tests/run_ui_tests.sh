#!/usr/bin/env bash
# Headless desktop: virtual X server + session bus + dunst notification daemon.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHON="${PYTHON:-python3}"
exec dbus-run-session -- bash -c '
  Xvfb :99 -screen 0 1280x800x24 >/dev/null 2>&1 &
  export DISPLAY=:99
  sleep 1
  dunst >/dev/null 2>&1 &
  sleep 1
  "${PYTHON:-python3}" -m unittest tests.test_ui -v
'
