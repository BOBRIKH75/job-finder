"""Email handler — IMAP reading, outreach sending, follow-ups."""
import imaplib, email, re, os, time
from datetime import datetime, timedelta
from email.mime.text import MIMEText


def connect_imap(host: str = "imap.gmail.com", user: str = None, password: str = None) -> imaplib.IMAP4_SSL:
    user = user or os.environ.get("GMAIL_USER", "")
    password = password or os.environ.get("GMAIL_APP_PASSWORD", "")
    conn = imaplib.IMAP4_SSL(host)
    conn.login(user, password)
    return conn


def search_verification_emails(conn: imaplib.IMAP4_SSL, since_minutes: int = 30) -> list[dict]:
    """Find recent verification/confirmation emails."""
    conn.select("INBOX")
    since = (datetime.now() - timedelta(minutes=since_minutes)).strftime("%d-%b-%Y")
    _, data = conn.search(None, f'(SINCE {since} OR SUBJECT "verify" SUBJECT "confirm")')
    results = []
    for num in data[0].split():
        _, msg_data = conn.fetch(num, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        body = _get_body(msg)
        links = re.findall(r'https?://[^\s"<>]+(?:verify|confirm|activate|token)[^\s"<>]*', body)
        codes = re.findall(r'\b\d{6}\b', body)
        if links or codes:
            results.append({"subject": msg["subject"], "links": links, "codes": codes})
    return results


def _get_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return part.get_payload(decode=True).decode(errors="ignore")
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode(errors="ignore")
    return msg.get_payload(decode=True).decode(errors="ignore") if msg.get_payload() else ""


def check_for_replies(conn: imaplib.IMAP4_SSL, sent_to: str) -> bool:
    """Check if a recruiter has replied."""
    conn.select("INBOX")
    _, data = conn.search(None, f'(FROM "{sent_to}")')
    return len(data[0].split()) > 0


def should_follow_up(last_contacted: str, follow_up_days: list[int] = None) -> int | None:
    """Returns which follow-up number to send, or None."""
    if not last_contacted:
        return None
    follow_up_days = follow_up_days or [3, 7, 14]
    days_since = (datetime.now() - datetime.fromisoformat(last_contacted)).days
    for i, day in enumerate(follow_up_days):
        if days_since >= day and days_since < day + 2:
            return i + 1
    return None


def render_template(template: str, **kwargs) -> str:
    """Simple template rendering with {placeholder} substitution."""
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


class EmailThrottle:
    """Rate limiter for email sending."""

    def __init__(self, max_per_day: int = 10):
        self.max_per_day = max_per_day
        self._sent_today: list[float] = []

    def can_send(self) -> bool:
        cutoff = time.time() - 86400
        self._sent_today = [t for t in self._sent_today if t > cutoff]
        return len(self._sent_today) < self.max_per_day

    def record_send(self):
        self._sent_today.append(time.time())

    @property
    def remaining(self) -> int:
        cutoff = time.time() - 86400
        self._sent_today = [t for t in self._sent_today if t > cutoff]
        return max(0, self.max_per_day - len(self._sent_today))
