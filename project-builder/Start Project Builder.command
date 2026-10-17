#!/bin/bash
# Double-click to start Project Builder. It opens in your web browser.
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is needed. macOS will offer to install it (Command Line Tools) - accept, then double-click this file again."
  xcode-select --install 2>/dev/null
  read -n 1 -s -r -p "Press any key to close"; exit 1
fi
if [ ! -x ".venv/bin/python" ] || [ ! -f ".venv/.ready" ]; then
  echo "First start: installing the image tools Project Builder needs (one time, about 1-3 minutes)..."
  python3 -m venv .venv || { echo "Could not create the Python environment."; read -n 1 -s -r; exit 1; }
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt || { echo; echo "Install failed - check the internet connection and try again."; read -n 1 -s -r -p "Press any key to close"; exit 1; }
  touch .venv/.ready
fi
.venv/bin/python builder_server.py
