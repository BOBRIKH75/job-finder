#!/usr/bin/env python3
"""Deep analysis: are the 'interview/RTR/call' emails REAL engagement TO Bob, or
noise (Bob's own sent hotlists, mass C2C blasts, job alerts)? Statistical truth."""
import os, imaplib, email
from email.header import decode_header
from collections import Counter

user=os.environ.get("GMAIL_USER","bobrikh75@gmail.com"); pw=os.environ.get("GMAIL_APP_PASSWORD","")
if not pw: print("no creds"); raise SystemExit
M=imaplib.IMAP4_SSL("imap.gmail.com"); M.login(user,pw); M.select('"[Gmail]/All Mail"')

def _dec(s):
    if not s: return ""
    out=[]
    for t,enc in decode_header(s):
        out.append(t.decode(enc or 'utf-8','replace') if isinstance(t,bytes) else t)
    return "".join(out)

def analyze(crit, label, n=40):
    typ,data=M.search(None,crit)
    ids=data[0].split() if data and data[0] else []
    print(f"\n=== {label}: {len(ids)} total ===")
    from_me=0; to_me_real=0; blast=0; senders=Counter()
    for i in ids[-n:]:  # sample last N
        typ,md=M.fetch(i,'(BODY[HEADER.FIELDS (FROM SUBJECT)])')
        if not md or not md[0]: continue
        hdr=email.message_from_bytes(md[0][1])
        frm=_dec(hdr.get("From","")).lower()
        subj=_dec(hdr.get("Subject",""))
        senders[frm.split('<')[-1].strip('> ')]+=1
        if user in frm:  # Bob sent it himself (his hotlist posts)
            from_me+=1
        elif any(x in frm for x in ('noreply','no-reply','jobs-noreply','alert','notification','indeed.com','ziprecruiter','linkedin.com')):
            blast+=1
        else:
            to_me_real+=1
    print(f"  sampled {min(len(ids),n)}: FROM Bob himself={from_me} | job-alert/noreply={blast} | real human TO Bob={to_me_real}")
    print("  top senders:")
    for s,c in senders.most_common(6): print(f"    {c:3}  {s[:55]}")

analyze('(SUBJECT "interview")', "SUBJECT interview")
analyze('(SUBJECT "right to represent")', "RTR requests")
analyze('(BODY "available for a call")', "available for a call", n=30)
M.logout()
