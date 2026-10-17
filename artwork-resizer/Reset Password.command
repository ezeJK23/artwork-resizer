#!/bin/bash
# Double-click if someone has forgotten their password for Artwork Resizer / Project Builder.
cd "$(dirname "$0")"
python3 common/reset_password.py
echo; read -n 1 -s -r -p "Press any key to close"
