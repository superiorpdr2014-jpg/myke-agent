"""
gmail_reader.py — Gmail IMAP reader for Myke Agent
Fetches recent emails, classifies them, and returns structured summaries.
"""

import sys, io, imaplib, email, textwrap, pathlib, tomllib
from email.header import decode_header
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_secrets = tomllib.loads(
    pathlib.Path(__file__).parent.joinpath(".streamlit/secrets.toml").read_text(encoding="utf-8")
)
GMAIL_USER = _secrets["GMAIL_USER"]
GMAIL_PASS = _secrets["GMAIL_PASS"]

IMAP_HOST = "imap.gmail.com"

# Keywords that flag a message as a customer/business inquiry
INQUIRY_KEYWORDS = [
    "凹痕", "修復", "報價", "pdr", "板金", "保險桿", "掉漆", "維修",
    "dent", "repair", "quote", "estimate", "appointment", "booking",
    "合作", "詢問", "inquiry", "collaboration",
]


def _decode_str(value):
    parts = decode_header(value or "")
    result = []
    for b, enc in parts:
        if isinstance(b, bytes):
            result.append(b.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(b)
    return "".join(result)


def _body_text(msg) -> str:
    """Extract plain-text body from email.message.Message."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in disp:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace") if payload else ""
    return ""


def _is_inquiry(subject: str, body: str) -> bool:
    text = (subject + " " + body).lower()
    return any(kw in text for kw in INQUIRY_KEYWORDS)


def fetch_emails(hours: int = 24, max_results: int = 30) -> list[dict]:
    """
    Fetch emails from the past `hours` hours.
    Returns list of dicts with keys: subject, sender, date, snippet, is_inquiry, uid.
    """
    conn = imaplib.IMAP4_SSL(IMAP_HOST)
    conn.login(GMAIL_USER, GMAIL_PASS)
    conn.select("INBOX")

    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%d-%b-%Y")
    _, data = conn.search(None, f'(SINCE "{since}")')
    uid_list = data[0].split() if data[0] else []

    # Newest first, cap at max_results
    uid_list = uid_list[-max_results:][::-1]

    results = []
    for uid in uid_list:
        _, msg_data = conn.fetch(uid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        subject = _decode_str(msg.get("Subject", "(no subject)"))
        sender  = _decode_str(msg.get("From", ""))
        date_str = msg.get("Date", "")
        body = _body_text(msg)
        snippet = textwrap.shorten(body.strip(), width=200, placeholder="...")

        results.append({
            "uid":        uid.decode(),
            "subject":    subject,
            "sender":     sender,
            "date":       date_str,
            "snippet":    snippet,
            "body":       body,
            "is_inquiry": _is_inquiry(subject, body),
        })

    conn.logout()
    return results


def summarise(hours: int = 24) -> str:
    """
    Return a human-readable summary of recent emails.
    Used by MCP server tool and morning report.
    """
    emails = fetch_emails(hours=hours)
    if not emails:
        return f"No emails in the past {hours} hours."

    inquiries = [e for e in emails if e["is_inquiry"]]
    others    = [e for e in emails if not e["is_inquiry"]]

    lines = [f"=== Gmail Summary (past {hours}h) — {len(emails)} emails ===\n"]

    if inquiries:
        lines.append(f"🔔 CUSTOMER / BUSINESS INQUIRIES ({len(inquiries)})")
        lines.append("─" * 50)
        for e in inquiries:
            lines.append(f"From   : {e['sender']}")
            lines.append(f"Subject: {e['subject']}")
            lines.append(f"Date   : {e['date']}")
            lines.append(f"Preview: {e['snippet']}")
            lines.append("")

    if others:
        lines.append(f"📬 OTHER EMAILS ({len(others)})")
        lines.append("─" * 50)
        for e in others:
            lines.append(f"• [{e['date'][:16]}] {e['sender'][:30]}  |  {e['subject']}")

    return "\n".join(lines)


def draft_reply(uid: str, tone: str = "professional") -> str:
    """
    Fetch a specific email by UID and return a draft reply in Traditional Chinese.
    """
    conn = imaplib.IMAP4_SSL(IMAP_HOST)
    conn.login(GMAIL_USER, GMAIL_PASS)
    conn.select("INBOX")
    _, msg_data = conn.fetch(uid.encode(), "(RFC822)")
    conn.logout()

    raw = msg_data[0][1]
    msg = email.message_from_bytes(raw)
    subject = _decode_str(msg.get("Subject", ""))
    sender  = _decode_str(msg.get("From", ""))
    body    = _body_text(msg)

    return (
        f"[DRAFT REPLY]\n"
        f"To: {sender}\n"
        f"Subject: Re: {subject}\n\n"
        f"--- Original ---\n{textwrap.shorten(body, 300, placeholder='...')}\n\n"
        f"--- Draft (tone={tone}) ---\n"
        f"(請用 Claude 根據以上原文產生繁體中文回覆草稿)"
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--draft", type=str, default=None, help="UID to draft reply for")
    args = parser.parse_args()

    if args.draft:
        print(draft_reply(args.draft))
    else:
        print(summarise(hours=args.hours))
