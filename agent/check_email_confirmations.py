#!/usr/bin/env python3
"""Check Gmail for Indeed 'Application submitted' confirmations and record them,
so email-confirmed jobs are skipped next run. Prints titles/companies only."""
import os, imaplib, email, json, re
from email.header import decode_header

for line in open('.env'):
    line=line.strip()
    if line and not line.startswith('#') and '=' in line:
        k,v=line.split('=',1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

user=os.environ.get('GMAIL_USER',''); pw=os.environ.get('GMAIL_APP_PASSWORD','')
if not user or not pw:
    print("no gmail creds"); raise SystemExit

def dec(s):
    if not s: return ''
    out=''
    for t,enc in decode_header(s):
        out += t.decode(enc or 'utf-8','ignore') if isinstance(t,bytes) else t
    return out

M=imaplib.IMAP4_SSL('imap.gmail.com'); M.login(user,pw); M.select('inbox')
# Indeed confirmation emails have subject starting "Indeed Application:"
typ,data=M.search(None, "(SUBJECT \"Indeed Application:\")")
ids=data[0].split()
print(f"Found {len(ids)} Indeed 'Application submitted' emails")
titles=[]
for i in ids[-40:]:
    typ,md=M.fetch(i,'(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)])')
    m=email.message_from_string(md[0][1].decode('utf-8','ignore'))
    subj=dec(m.get('Subject'))
    # subject: "Indeed Application: <Job Title>"
    t=subj.replace('Indeed Application:','').strip()
    if t: titles.append(t)
M.logout()

# Save confirmed titles to a file the bot can use to skip by title match
CONF='data/email_confirmed_titles.json'
existing=set()
try: existing=set(json.load(open(CONF)))
except Exception: pass
before=len(existing)
existing.update(titles)
json.dump(sorted(existing), open(CONF,'w'))
print(f"Recorded {len(existing)} email-confirmed job titles ({len(existing)-before} new):")
for t in sorted(existing)[:30]:
    print("  •", t[:70])
