"""SMTP/IMAP helper functions for the smtp email provider.

Uses only Python stdlib — no external dependencies.
"""

from __future__ import annotations

import email as email_lib
import imaplib
import logging
import smtplib
import ssl
from email.header import decode_header as _decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_smtp_connection(
    host: str, port: int, username: str, password: str, use_tls: bool
) -> smtplib.SMTP | smtplib.SMTP_SSL:
    """Create and authenticate an SMTP connection."""
    if use_tls and port == 465:
        conn = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        conn = smtplib.SMTP(host, port, timeout=30)
        conn.ehlo()
        if use_tls:
            conn.starttls(context=ssl.create_default_context())
            conn.ehlo()
    conn.login(username, password)
    return conn


def _get_imap_connection(
    host: str, port: int, username: str, password: str, use_tls: bool
) -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
    """Create and authenticate an IMAP connection."""
    if use_tls:
        conn = imaplib.IMAP4_SSL(host, port)
    else:
        conn = imaplib.IMAP4(host, port)
    conn.login(username, password)
    return conn


def _decode_header_value(value: str | None) -> str:
    """Decode RFC 2047 encoded header value."""
    if not value:
        return ""
    parts = _decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _get_text_body(msg: email_lib.message.Message) -> tuple[str, str]:
    """Extract plain text and HTML body from a message. Returns (text, html)."""
    text_body = ""
    html_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain" and not text_body:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    text_body = payload.decode(charset, errors="replace")
            elif ct == "text/html" and not html_body:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    html_body = payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            content = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_body = content
            else:
                text_body = content
    return text_body, html_body


def _get_attachments(msg: email_lib.message.Message) -> list[dict[str, Any]]:
    """Extract attachment metadata from a message."""
    attachments = []
    if not msg.is_multipart():
        return attachments
    for part in msg.walk():
        disposition = str(part.get("Content-Disposition", ""))
        if "attachment" in disposition:
            filename = part.get_filename() or "unknown"
            filename = _decode_header_value(filename)
            payload = part.get_payload(decode=True)
            attachments.append(
                {
                    "filename": filename,
                    "content_type": part.get_content_type(),
                    "size_bytes": len(payload) if payload else 0,
                }
            )
    return attachments


def _parse_message_summary(
    uid: bytes, msg: email_lib.message.Message
) -> dict[str, Any]:
    """Extract summary fields from a parsed email message."""
    msg_id = msg.get("Message-ID", "") or ""
    subject = _decode_header_value(msg.get("Subject", ""))
    sender = _decode_header_value(msg.get("From", ""))
    date = msg.get("Date", "")
    text_body, _ = _get_text_body(msg)
    snippet = text_body[:200].replace("\n", " ").strip() if text_body else ""

    # Use Message-ID as primary identifier, fall back to uid:NNNN
    identifier = msg_id if msg_id else f"uid:{uid.decode()}"

    return {
        "message_id": identifier,
        "from": sender,
        "subject": subject,
        "snippet": snippet,
        "received_at": date,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def test_smtp_connection(
    host: str, port: int, username: str, password: str, use_tls: bool = True
) -> dict[str, Any]:
    """Test SMTP connection and authentication."""
    try:
        conn = _get_smtp_connection(host, port, username, password, use_tls)
        conn.quit()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def test_imap_connection(
    host: str,
    port: int,
    username: str,
    password: str,
    use_tls: bool = True,
    mailbox: str = "INBOX",
) -> dict[str, Any]:
    """Test IMAP connection, auth, and mailbox select."""
    try:
        conn = _get_imap_connection(host, port, username, password, use_tls)
        status, data = conn.select(mailbox, readonly=True)
        count = int(data[0]) if data and data[0] else 0
        conn.logout()
        return {"success": True, "message_count": count}
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_email(
    host: str,
    port: int,
    username: str,
    password: str,
    use_tls: bool,
    from_address: str,
    from_name: str,
    to: str,
    subject: str,
    body: str,
    html: bool = False,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> dict[str, Any]:
    """Send an email via SMTP. Returns {"message_id": str, "status": "sent"}."""
    msg = MIMEMultipart("alternative") if html else MIMEText(body, "plain", "utf-8")

    if html:
        msg.attach(MIMEText(body, "html", "utf-8"))

    msg["From"] = formataddr((from_name, from_address))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()

    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    conn = _get_smtp_connection(host, port, username, password, use_tls)
    try:
        conn.sendmail(
            from_address, [addr.strip() for addr in to.split(",")], msg.as_string()
        )
    finally:
        conn.quit()

    return {"message_id": msg["Message-ID"], "status": "sent"}


def list_messages(
    host: str,
    port: int,
    username: str,
    password: str,
    use_tls: bool,
    mailbox: str = "INBOX",
    limit: int = 20,
    offset: int = 0,
    from_filter: str = "",
    unread_only: bool = False,
) -> list[dict[str, Any]]:
    """List message summaries from IMAP."""
    conn = _get_imap_connection(host, port, username, password, use_tls)
    try:
        conn.select(mailbox, readonly=True)

        # Build search criteria
        if unread_only:
            _, data = conn.uid("search", None, "UNSEEN")
        else:
            _, data = conn.uid("search", None, "ALL")

        uids = data[0].split() if data[0] else []
        # Newest first
        uids.reverse()
        # Apply offset and limit
        uids = uids[offset : offset + limit]

        results: list[dict[str, Any]] = []
        for uid in uids:
            _, msg_data = conn.uid("fetch", uid, "(RFC822)")
            if not msg_data or not msg_data[0] or not isinstance(msg_data[0], tuple):
                continue
            raw_email = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw_email)
            summary = _parse_message_summary(uid, msg)

            # Apply from_filter
            if from_filter and from_filter.lower() not in summary["from"].lower():
                continue

            results.append(summary)

        return results
    finally:
        conn.logout()


def read_message(
    host: str,
    port: int,
    username: str,
    password: str,
    use_tls: bool,
    mailbox: str,
    message_id: str,
) -> dict[str, Any]:
    """Fetch a full message by RFC Message-ID or uid:NNNN fallback."""
    conn = _get_imap_connection(host, port, username, password, use_tls)
    try:
        conn.select(mailbox, readonly=True)

        # Determine search strategy
        if message_id.startswith("uid:"):
            uid = message_id[4:].encode()
            _, msg_data = conn.uid("fetch", uid, "(RFC822)")
        else:
            # Search by Message-ID header
            search_id = message_id.strip("<>")
            _, data = conn.uid("search", None, f'HEADER Message-ID "<{search_id}>"')
            uids = data[0].split() if data[0] else []
            if not uids:
                # Fallback: try without angle brackets
                _, data = conn.uid("search", None, f'HEADER Message-ID "{message_id}"')
                uids = data[0].split() if data[0] else []
            if not uids:
                return {"error": f"Message not found: {message_id}"}
            uid = uids[0]
            _, msg_data = conn.uid("fetch", uid, "(RFC822)")

        if not msg_data or not msg_data[0] or not isinstance(msg_data[0], tuple):
            return {"error": f"Failed to fetch message: {message_id}"}

        raw_email = msg_data[0][1]
        msg = email_lib.message_from_bytes(raw_email)

        text_body, html_body = _get_text_body(msg)
        attachments = _get_attachments(msg)

        # Extract recipients
        to_addr = _decode_header_value(msg.get("To", ""))
        cc_addr = _decode_header_value(msg.get("Cc", ""))

        return {
            "message_id": msg.get("Message-ID", message_id),
            "from": _decode_header_value(msg.get("From", "")),
            "to": to_addr,
            "cc": cc_addr,
            "subject": _decode_header_value(msg.get("Subject", "")),
            "body": text_body,
            "html_body": html_body,
            "received_at": msg.get("Date", ""),
            "in_reply_to": msg.get("In-Reply-To", ""),
            "references": msg.get("References", ""),
            "attachments": attachments,
        }
    finally:
        conn.logout()


def search_messages(
    host: str,
    port: int,
    username: str,
    password: str,
    use_tls: bool,
    mailbox: str,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search messages. Tries IMAP SEARCH, falls back to client-side keyword scoring."""
    conn = _get_imap_connection(host, port, username, password, use_tls)
    try:
        conn.select(mailbox, readonly=True)

        # Try IMAP TEXT search first (searches full message)
        try:
            _, data = conn.uid("search", None, f'TEXT "{query}"')
            uids = data[0].split() if data[0] else []
        except Exception:
            # Server doesn't support TEXT search — fall back to ALL + client-side
            _, data = conn.uid("search", None, "ALL")
            uids = data[0].split() if data[0] else []

        # Newest first, cap at reasonable fetch size
        uids.reverse()
        fetch_limit = max(limit * 3, 50)  # fetch more for client-side scoring
        uids = uids[:fetch_limit]

        results: list[dict[str, Any]] = []
        query_lower = query.lower()
        query_words = query_lower.split()

        for uid in uids:
            _, msg_data = conn.uid("fetch", uid, "(RFC822)")
            if not msg_data or not msg_data[0] or not isinstance(msg_data[0], tuple):
                continue
            raw_email = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw_email)
            summary = _parse_message_summary(uid, msg)

            # Client-side relevance scoring
            text = (
                f"{summary['subject']} {summary['snippet']} {summary['from']}".lower()
            )
            score = sum(1 for word in query_words if word in text)
            if score > 0:
                summary["relevance_score"] = score
                results.append(summary)

        # Sort by relevance and limit
        results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        return results[:limit]
    finally:
        conn.logout()
