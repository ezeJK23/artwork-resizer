# Artwork Resizer suite

Local Mac apps that resize retail/POS artwork to any size by following a brand's master layout guide (PDF exported from InDesign).

| Folder | What it is | Port |
|---|---|---|
| `artwork-resizer/` | Front end: enter a size, get a live proof (rulers, trim, bleed) and a vector `.ai` file laid out per the guide | 8765 |
| `project-builder/` | Front end: drag in a master guide PDF (+ optional link pictures) to create a new project | 8766 |
| `control-centre/` | Back end + admin: issue/renew licence codes, start/stop apps, manage users, projects and this Mac's licence | 8770 |
| `shared/` | Sign-in, licensing (Ed25519) and password-reset code used by the apps (copied into each app's `common/`) | – |

## Run (macOS)
Each folder has a `Start … .command` file – double-click it. The three folders should sit side by side.
Project Builder installs its image tools on first start (`requirements.txt`, needs internet).
Artwork Resizer needs only Python 3 (pypdf is vendored).

## Licensing
Codes are signed with an Ed25519 private key that is **not** in this repository (`private_key.hex`, git-ignored).
The matching public key is in `shared/licensing.py`. Keep the private key backed up outside Git;
without it no new codes can be issued for builds already delivered.

## Not included
Client guides, link pictures, generated projects and artwork (brand assets) – see `.gitignore`.
