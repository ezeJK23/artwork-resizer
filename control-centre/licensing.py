"""
Licence codes for Artwork Resizer / Project Builder.

A code carries: licence id, licensee, start date, end date, products – signed with the
vendor's private key (Ed25519). The apps only hold the public key, so they can check a
code but cannot create one.

Code text:  AR1-XXXXX-XXXXX-...   (base32 of payload + 64-byte signature)
"""
import base64, datetime, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ed25519  # noqa: E402

PUBLIC_KEY = bytes.fromhex('6b57153ad3ce0523be5efaad1a925def0af970f3dd6d55310c8cc6dcee3408e3')
PRODUCTS = {'R': 'Artwork Resizer', 'B': 'Project Builder'}
PREFIX = 'AR1'


def config_dir():
    if sys.platform == 'darwin':
        d = os.path.expanduser('~/Library/Application Support/Artwork Resizer')
    elif os.name == 'nt':
        d = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'Artwork Resizer')
    else:
        d = os.path.expanduser('~/.artwork_resizer')
    os.makedirs(d, exist_ok=True)
    return d


# ------------------------------------------------------------------ encoding
def _payload(lic_id, licensee, start, end, products):
    licensee = re.sub(r'[|\r\n]', ' ', licensee).strip()[:48]
    return '|'.join([PREFIX, lic_id, licensee, start.strftime('%Y%m%d'), end.strftime('%Y%m%d'), ''.join(sorted(products))]).encode('utf-8')


def encode(payload, signature):
    raw = base64.b32encode(payload + signature).decode().rstrip('=')
    return PREFIX + '-' + '-'.join(raw[i:i + 5] for i in range(0, len(raw), 5))


def make_code(private_key, lic_id, licensee, start, end, products):
    """Vendor side only."""
    payload = _payload(lic_id, licensee, start, end, products)
    return encode(payload, ed25519.sign(private_key, payload))


def decode(code):
    """Return the licence fields or raise ValueError with a plain-language reason."""
    if not code or not code.strip():
        raise ValueError('Enter a licence code.')
    s = re.sub(r'[^A-Za-z0-9]', '', code).upper()
    if s.startswith(PREFIX):
        s = s[len(PREFIX):]
    s += '=' * (-len(s) % 8)
    try:
        raw = base64.b32decode(s)
    except Exception:
        raise ValueError('This is not a valid licence code. Check that it was copied completely.')
    if len(raw) < 80:
        raise ValueError('This licence code is incomplete. Copy the whole code and try again.')
    payload, sig = raw[:-64], raw[-64:]
    if not ed25519.verify(PUBLIC_KEY, payload, sig):
        raise ValueError('This licence code is not genuine or was changed. Check it was copied correctly.')
    parts = payload.decode('utf-8').split('|')
    if len(parts) != 6 or parts[0] != PREFIX:
        raise ValueError('This licence code is for a different product version.')
    _, lic_id, licensee, a, b, prods = parts
    start = datetime.datetime.strptime(a, '%Y%m%d').date()
    end = datetime.datetime.strptime(b, '%Y%m%d').date()
    return dict(id=lic_id, licensee=licensee, start=start.isoformat(), end=end.isoformat(),
                products=[PRODUCTS.get(c, c) for c in prods], product_codes=prods)


# ------------------------------------------------------------------ installed licence
def _paths(app_code):
    d = config_dir()
    return os.path.join(d, f'license_{app_code}.key'), os.path.join(d, 'license_seen.json')


def status(app_code):
    """Current licence state for one app ('R' or 'B')."""
    key_path, seen_path = _paths(app_code)
    if not os.path.isfile(key_path):
        return dict(valid=False, reason='No licence has been entered on this computer yet.')
    code = open(key_path).read().strip()
    try:
        lic = decode(code)
    except ValueError as e:
        return dict(valid=False, reason=str(e))
    today = datetime.date.today()
    last = None
    try:
        last = datetime.date.fromisoformat(json.load(open(seen_path))['last'])
    except Exception:
        pass
    out = dict(lic, valid=False)
    end = datetime.date.fromisoformat(lic['end']); start = datetime.date.fromisoformat(lic['start'])
    out['days_left'] = (end - today).days
    if app_code not in lic['product_codes']:
        out['reason'] = f"This licence does not include {PRODUCTS.get(app_code, app_code)}."
    elif last and today < last - datetime.timedelta(days=2):
        out['reason'] = "The computer's date is earlier than the last time the app was used. Correct the date and time, then reopen."
    elif today < start:
        out['reason'] = f"This licence starts on {lic['start']}."
    elif today > end:
        out['reason'] = f"This licence ended on {lic['end']}. Enter the new year's licence code to continue."
    else:
        out['valid'] = True
        try:
            if not last or today > last:
                json.dump(dict(last=today.isoformat()), open(seen_path, 'w'))
        except Exception:
            pass
    return out


def install(code, app_code):
    lic = decode(code)                       # raises ValueError with a reason
    today = datetime.date.today()
    if datetime.date.fromisoformat(lic['end']) < today:
        raise ValueError(f"This licence ended on {lic['end']}. Ask for the current year's code.")
    if app_code not in lic['product_codes']:
        raise ValueError(f"This licence does not include {PRODUCTS.get(app_code, app_code)}.")
    for c in lic['product_codes']:            # one code can unlock several apps
        with open(_paths(c)[0], 'w') as f:
            f.write(code.strip())
    return status(app_code)
