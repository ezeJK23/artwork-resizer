"""Forgot the License Manager password: choose a new one here.
Issued licences, the register and the signing key are not touched."""
import getpass, hashlib, json, os, secrets, time
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data'); os.makedirs(DATA, exist_ok=True)
P = os.path.join(DATA, 'manager_password.json')

print('\nSet a new License Manager password')
print('(Nothing appears on screen while you type a password – that is normal. Press Return when done.)\n')
while True:
    pw = getpass.getpass('New password (at least 10 characters): ')
    if len(pw) < 10:
        print(f'  That is {len(pw)} characters – it needs at least 10. Try again.\n'); continue
    if getpass.getpass('Type it again to confirm: ') != pw:
        print('  The two entries did not match. Try again.\n'); continue
    break
if os.path.isfile(P):
    os.replace(P, P + time.strftime('.old-%Y%m%d-%H%M%S'))
salt = secrets.token_hex(16)
h = hashlib.pbkdf2_hmac('sha256', pw.encode(), bytes.fromhex(salt), 200_000).hex()
with open(P, 'w') as f:
    json.dump(dict(salt=salt, hash=h), f)
print('\nDone – the new password is saved.')
print('If License Manager is open, reload the page and sign in with it.')
print('Your licences, register and signing key are unchanged.')
