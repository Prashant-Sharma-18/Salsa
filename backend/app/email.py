"""Email provider boundary.

Messages are written to ``notification_outbox`` inside the caller's transaction
(so they are only sent if the business operation commits) and delivered by
``deliver_pending``, which runs from ``flask email-worker`` (continuous) or
``flask deliver-emails`` (one batch).

Providers:
- ``console``: logs a redacted summary only. In non-production demo mode the
  full message is viewable via the dev mailbox endpoint.
- ``smtp``: any SMTP relay (SendGrid, Postmark, Amazon SES, Mailgun, ...).

Delivery is at-least-once: each message is claimed atomically before sending,
so concurrent workers never pick the same row; a claim older than
``CLAIM_TIMEOUT`` (worker crashed mid-send) is retried.
"""

import logging
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from email.utils import make_msgid

from flask import current_app
from sqlalchemy import or_, update

from .extensions import db
from .models import NotificationOutbox, utcnow

log = logging.getLogger("loyalloop.email")

MAX_ATTEMPTS = 5
CLAIM_TIMEOUT = timedelta(minutes=10)


def redact_email(address: str) -> str:
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


class ConsoleProvider:
    name = "console"

    def send(self, recipient: str, subject: str, body: str) -> None:
        log.info("email sent provider=console to=%s subject=%r", redact_email(recipient), subject)


class SMTPProvider:
    name = "smtp"

    def __init__(self, config):
        self.host = config["SMTP_HOST"]
        self.port = config["SMTP_PORT"]
        self.username = config["SMTP_USERNAME"]
        self.password = config["SMTP_PASSWORD"]
        self.security = config["SMTP_SECURITY"]  # starttls | ssl | none
        self.sender = config["EMAIL_FROM"]
        self.reply_to = config["EMAIL_REPLY_TO"]
        self.timeout = config["SMTP_TIMEOUT"]

    def _connect(self) -> smtplib.SMTP:
        context = ssl.create_default_context()
        if self.security == "ssl":
            return smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=context)
        client = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        if self.security == "starttls":
            client.starttls(context=context)
        return client

    def send(self, recipient: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = recipient
        msg["Subject"] = subject
        msg["Message-ID"] = make_msgid(domain=self.sender.rpartition("@")[2].rstrip(">") or None)
        if self.reply_to:
            msg["Reply-To"] = self.reply_to
        msg.set_content(body)
        with self._connect() as client:
            if self.username:
                client.login(self.username, self.password)
            client.send_message(msg)
        log.info("email sent provider=smtp to=%s subject=%r", redact_email(recipient), subject)


def get_provider():
    provider = current_app.config["EMAIL_PROVIDER"]
    if provider == "console":
        return ConsoleProvider()
    if provider == "smtp":
        return SMTPProvider(current_app.config)
    raise RuntimeError(f"Email provider '{provider}' is not supported. Use 'console' or 'smtp'.")


def queue_email(kind: str, recipient: str, subject: str, body: str, business_id=None, dedupe_key=None):
    """Add to outbox in the current transaction. Duplicate dedupe keys are ignored."""
    if dedupe_key and NotificationOutbox.query.filter_by(dedupe_key=dedupe_key).first():
        return None
    msg = NotificationOutbox(
        business_id=business_id, kind=kind, recipient=recipient, subject=subject, body=body, dedupe_key=dedupe_key
    )
    db.session.add(msg)
    return msg


def _claim(message_id: int) -> bool:
    """Atomically mark a message as being sent. Returns False if another worker owns it."""
    now = utcnow()
    result = db.session.execute(
        update(NotificationOutbox)
        .where(
            NotificationOutbox.id == message_id,
            or_(
                NotificationOutbox.status == "pending",
                (NotificationOutbox.status == "sending") & (NotificationOutbox.claimed_at < now - CLAIM_TIMEOUT),
            ),
        )
        .values(status="sending", claimed_at=now, attempts=NotificationOutbox.attempts + 1)
        .execution_options(synchronize_session=False)
    )
    db.session.commit()
    return result.rowcount == 1


def deliver_pending(limit: int = 50) -> int:
    """Send due messages through the configured provider. Safe to run from several workers."""
    provider = get_provider()
    stale = utcnow() - CLAIM_TIMEOUT
    candidates = [
        row.id
        for row in NotificationOutbox.query.filter(
            NotificationOutbox.attempts < MAX_ATTEMPTS,
            or_(
                NotificationOutbox.status == "pending",
                (NotificationOutbox.status == "sending") & (NotificationOutbox.claimed_at < stale),
            ),
        )
        .order_by(NotificationOutbox.id)
        .limit(limit)
    ]
    sent = 0
    for message_id in candidates:
        if not _claim(message_id):
            continue
        msg = db.session.get(NotificationOutbox, message_id)
        try:
            provider.send(msg.recipient, msg.subject, msg.body)
        except Exception as exc:  # provider failures are retried on a later run
            msg.status = "failed" if msg.attempts >= MAX_ATTEMPTS else "pending"
            msg.last_error = f"{type(exc).__name__}: {exc}"[:255]
            log.warning("email delivery failed id=%s attempt=%s error=%s", msg.id, msg.attempts, type(exc).__name__)
        else:
            msg.status = "sent"
            msg.sent_at = utcnow()
            msg.last_error = None
            sent += 1
        db.session.commit()
    return sent


def link(path: str) -> str:
    return current_app.config["PUBLIC_BASE_URL"].rstrip("/") + path
