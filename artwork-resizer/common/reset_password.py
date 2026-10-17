"""Reset a sign-in password for Artwork Resizer / Project Builder on this computer."""
import getpass, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auth

print('\nReset a sign-in password (Artwork Resizer and Project Builder)\n')
users = auth.list_users()
if not users:
    print('No accounts exist yet. Start the app and create the administrator account.')
    sys.exit(0)
names = {u['id'].lower(): u['id'] for u in users}
if len(users) == 1:
    uid = users[0]['id']
    print(f'Account on this computer: {uid}\n')
else:
    print('Accounts on this computer:')
    for i, u in enumerate(users, 1):
        print(f"  {i}. {u['id']}  ({'administrator' if u['role'] == 'admin' else 'user'})")
    while True:
        a = input('\nType the number or user ID of the account to reset: ').strip()
        if a.isdigit() and 1 <= int(a) <= len(users):
            uid = users[int(a) - 1]['id']; break
        if a.lower() in names:
            uid = names[a.lower()]; break
        print('  Not found – type one of the numbers or user IDs listed above.')
print('(Nothing appears on screen while you type a password – that is normal. Press Return when done.)\n')
while True:
    pw = getpass.getpass(f'New password for {uid} (at least 8 characters): ')
    if len(pw) < 8:
        print(f'  That is {len(pw)} characters – it needs at least 8. Try again.\n'); continue
    if getpass.getpass('Type it again to confirm: ') != pw:
        print('  The two entries did not match. Try again.\n'); continue
    break
auth.set_password(uid, pw)
print(f'\nDone – {uid} can now sign in with the new password (in both apps).')
