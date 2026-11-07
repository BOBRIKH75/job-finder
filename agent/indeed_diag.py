"""Diagnostic: report (counts/booleans only) whether any Chrome profile on this Mac holds Indeed auth cookies."""
import glob, os, shutil, sqlite3, tempfile, time, subprocess
AUTH = ('CTK', 'SHARED_INDEED_CSRF_TOKEN', 'INDEED_CSRF_TOKEN', 'PPID', 'SOCK', 'ctkgen', 'SURF', 'RF', 'LV', 'LC', 'SHOE', 'MICRO')
home = os.path.expanduser('~')
cands = set(glob.glob(home + '/Library/Application Support/Google/Chrome/*/Cookies'))
cands |= set(glob.glob(home + '/Library/Application Support/Google/Chrome/*/Network/Cookies'))
for root in (home, os.getcwd(), os.path.abspath('..'), os.path.abspath('../..'), os.path.abspath('../../..')):
    for pat in ('**/.chrome-profile/*/Network/Cookies', '**/.chrome-profile/*/Cookies', '**/.chrome-profile/Default/Network/Cookies'):
        try: cands |= set(glob.glob(os.path.join(root, pat), recursive=True)[:20])
        except Exception: pass
print('profiles found:', len(cands))
now_chrome = (time.time() + 11644473600) * 1e6
for p in sorted(cands):
    tag = p.replace(home, '~')
    tag = tag.split('/')[-4:] if 'chrome-profile' in tag else tag.split('/')[-3:]
    try:
        d = tempfile.mkdtemp(); t = os.path.join(d, 'c'); shutil.copy(p, t)
        con = sqlite3.connect(t)
        rows = con.execute("select name, expires_utc, length(encrypted_value)>0 from cookies where host_key like '%indeed.com'").fetchall()
        names = {r[0] for r in rows}
        live = [r for r in rows if r[1] == 0 or r[1] > now_chrome]
        print('PROFILE', '/'.join(tag), 'indeed_cookies=%d live=%d' % (len(rows), len(live)),
              'auth_names_present=%s' % sorted(n for n in names if n in AUTH),
              'CTK_live=%s' % any(r[0] == 'CTK' for r in live))
        g = con.execute("select count(*) from cookies where host_key like '%google.com'").fetchone()[0]
        print('   google_cookies=%d' % g)
    except Exception as e:
        print('PROFILE', '/'.join(tag), 'err', str(e)[:60])
print('chrome running:', subprocess.run(['pgrep', '-fc', 'Google Chrome'], capture_output=True, text=True).stdout.strip())
print('gmail env present:', bool(os.environ.get('GMAIL_USER')), bool(os.environ.get('GMAIL_APP_PASSWORD')))
