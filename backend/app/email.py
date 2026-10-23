"""Email provider boundary.

Messages are written to ``notification_outbox`` inside the caller's transaction
(so they are only sent if the business operation commits) and delivered by
``deliver_pending``. The default ``console`` provider logs a redacted summary;
in non-production demo mode the full message is viewable via the dev mailbox
endpoint so links can be followed locally.
"""

import logging

from flask import current_app
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import NotificationOutbox, utcnow

log = logging.getLogger("loyalloop.email")


def redact_email(address: str) -> str:
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


class ConsoleProvider:
    name = "console"

    def send(self, recipient: str, subject: str, body: str) -> None:
        log.info("email sent provider=console to=%s subject=%r", redact_email(recipient), subject)


def get_provider():
    provider = current_app.config["EMAIL_PROVIDER"]
    if provider == "console":
        return ConsoleProvider()
    raise RuntimeError(f"Email provider '{provider}' is not configured. See README > Email.")


def queue_email(kind: str, recipient: str, subject: str, body: str, business_id=None, dedupe_key=None):
    """Add to outbox in the current transaction. Duplicate dedupe keys are ignored."""
    if dedupe_key and NotificationOutbox.query.filter_by(dedupe_key=dedupe_key).first():
        return None
    msg = NotificationOutbox(
        business_id=business_id, kind=kind, recipient=recipient, subject=subject, body=body, dedupe_key=dedupe_key
    )
    db.session.add(msg)
    return msg


def deliver_pending(limit: int = 50) -> int:
    """Send pending messages. Safe to call repeatedly; each message is marked sent once."""
    provider = get_provider()
    sent = 0
    for msg in NotificationOutbox.query.filter(
        NotificationOutbox.status == "pending", NotificationOutbox.attempts < 5
    ).limit(limit):
        msg.attempts += 1
        try:
            provider.send(msg.recipient, msg.subject, msg.body)
            msg.status = "sent"
            msg.sent_at = utcnow()
            sent += 1
        except Exception as exc:  # provider failures are retried on next run
            msg.last_error = str(exc)[:255]
            if msg.attempts >= 5:
                msg.status = "failed"
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
    return sent


def link(path: str) -> str:
    return current_app.config["PUBLIC_BASE_URL"].rstrip("/") + path
