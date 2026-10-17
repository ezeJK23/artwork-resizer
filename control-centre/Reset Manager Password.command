#!/bin/bash
# Double-click if you have forgotten the License Manager password.
cd "$(dirname "$0")"
python3 reset_manager_password.py
echo; read -n 1 -s -r -p "Press any key to close"
