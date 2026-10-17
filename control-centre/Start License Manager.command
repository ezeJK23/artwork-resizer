#!/bin/bash
# Double-click to open Control Centre: licences (back end) + apps, users, projects on this Mac (front end).
cd "$(dirname "$0")"
command -v python3 >/dev/null 2>&1 || { echo "Python 3 is needed."; xcode-select --install 2>/dev/null; read -n 1 -s -r; exit 1; }
python3 control_server.py
