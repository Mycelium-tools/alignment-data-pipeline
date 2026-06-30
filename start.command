#!/bin/bash
# Double-click this file to launch the Prompt Studio GUI (macOS).
# It only needs Python 3 — no install step.
cd "$(dirname "$0")" || exit 1
echo "Starting Prompt Studio…"
echo
if command -v python3 >/dev/null 2>&1; then
  exec python3 gui/app.py
elif command -v python >/dev/null 2>&1; then
  exec python gui/app.py
else
  echo "Python 3 doesn't seem to be installed. Two easy options:"
  echo
  echo "  1) Ask Claude Code:   \"launch the prompt GUI\""
  echo "  2) Install Python 3 from https://www.python.org/downloads/"
  echo "     then double-click this file again."
  echo
  read -n 1 -s -r -p "Press any key to close this window."
fi
