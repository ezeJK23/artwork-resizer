#!/bin/bash
# Double-click to put this code in a PRIVATE GitHub repository under your account.
cd "$(dirname "$0")"
NAME="artwork-resizer"
echo
echo "Saving the Artwork Resizer code to GitHub as a private repository named '$NAME'."
echo
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  if git remote get-url origin >/dev/null 2>&1; then
    git push -u origin main
  else
    gh repo create "$NAME" --private --source . --push \
      --description "Resize retail/POS artwork to any size from a master layout guide"
  fi
else
  echo "Step 1: in your browser, create an EMPTY private repository:"
  echo "        https://github.com/new   (name: $NAME, Private, no README)"
  open "https://github.com/new" 2>/dev/null
  echo
  read -r -p "Step 2: paste the repository URL here (e.g. https://github.com/you/$NAME.git): " URL
  [ -z "$URL" ] && { echo "No URL entered - nothing was pushed."; read -n 1 -s -r; exit 1; }
  git remote remove origin 2>/dev/null
  git remote add origin "$URL"
  echo "Pushing… (GitHub may ask you to sign in)"
  git push -u origin main
fi
echo
echo "Done if you see no errors above. Press any key to close."
read -n 1 -s -r
