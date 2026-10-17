#!/bin/bash
# Double-click to start Artwork Resizer. It opens in your web browser.
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is needed. macOS will offer to install it (Command Line Tools) - accept, then double-click this file again."
  xcode-select --install 2>/dev/null
  read -n 1 -s -r -p "Press any key to close"
  exit 1
fi
python3 server.py
