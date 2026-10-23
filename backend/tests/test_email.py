"""Email delivery through a real (local) SMTP server."""

import socket
from email import message_from_bytes, policy

import pytest
from aiosmtpd.controller import Controller

from app import create_app
from app.config import TestConfig, validate_config
from app.email import MAX_ATTEMPTS, _claim, deliver_pending, queue_email
from app.extensions import db
from app.models import NotificationOutbox

from .conftest import Api


class Inbox:
    def __init__(self):
        self.messages = []

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(
            {
                "from": envelope.mail_from,
                "to": envelope.rcpt_tos,
                "msg": message_from_bytes(envelope.content, policy=policy.default),
            }
        )
        return "250 OK"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def smtp_server():
    inbox = Inbox()
    controller = Controller(inbox, hostname="127.0.0.1", port=_free_port())
    controller.start()
    yield controller, inbox
    controller.stop()


def _smtp_app(port: int):
    return create_app(
        TestConfig,
        {
            "EMAIL_PROVIDER": "smtp",
            "SMTP_HOST": "127.0.0.1",
            "SMTP_PORT": port,
            "SMTP_SECURITY": "none",
            "SMTP_TIMEOUT": 5,
            "EMAIL_FROM": "LoyalLoop <no-reply@loyalloop.test>",
            "EMAIL_REPLY_TO": "support@loyalloop.test",
            "PUBLIC_BASE_URL": "https://app.loyalloop.test",
        },
    )


@pytest.fixture
def smtp_app(smtp_server):
    controller, inbox = smtp_server
    app = _smtp_app(controller.port)
    with app.app_context():
        db.create_all()
        yield app, inbox
        db.session.remove()
        db.drop_all()


def test_password_reset_email_is_delivered_over_smtp(smtp_app):
    app, inbox = smtp_app
    api = Api(app)
    api.post(
        "/auth/signup", {"display_name": "Mail Test", "email": "mail.test@example.com", "password": "long-password-1"}
    )
    api.post("/auth/password-reset/request", {"email": "mail.test@example.com"})

    assert deliver_pending() == 2  # verification + reset
    assert len(inbox.messages) == 2
    reset = next(m["msg"] for m in inbox.messages if m["msg"]["Subject"] == "Reset your password")
    assert reset["To"] == "mail.test@example.com"
    assert reset["From"] == "LoyalLoop <no-reply@loyalloop.test>"
    assert reset["Reply-To"] == "support@loyalloop.test"
    assert reset["Message-ID"]
    assert "https://app.loyalloop.test/reset-password?token=" in reset.get_content()

    rows = NotificationOutbox.query.all()
    assert {r.status for r in rows} == {"sent"}
    assert all(r.sent_at and r.attempts == 1 for r in rows)

    # Running again sends nothing: no duplicate emails.
    assert deliver_pending() == 0
    assert len(inbox.messages) == 2


def test_failed_delivery_is_retried_then_marked_failed(app):
    app.config.update(
        EMAIL_PROVIDER="smtp",
        SMTP_HOST="127.0.0.1",
        SMTP_PORT=_free_port(),
        SMTP_SECURITY="none",
        SMTP_TIMEOUT=2,
        EMAIL_FROM="no-reply@loyalloop.test",
    )
    queue_email("test", "someone@example.com", "Hello", "Body")
    db.session.commit()

    assert deliver_pending() == 0
    msg = NotificationOutbox.query.one()
    assert msg.status == "pending" and msg.attempts == 1
    assert msg.last_error  # e.g. ConnectionRefusedError or TimeoutError depending on OS

    for _ in range(MAX_ATTEMPTS):
        deliver_pending()
    db.session.refresh(msg)
    assert msg.status == "failed"
    assert msg.attempts == MAX_ATTEMPTS


def test_claim_prevents_two_workers_sending_the_same_message(app):
    msg = queue_email("test", "someone@example.com", "Hello", "Body")
    db.session.commit()
    assert _claim(msg.id) is True
    assert _claim(msg.id) is False  # a second worker cannot take it


def test_delivery_failure_does_not_log_contents(app, caplog):
    app.config.update(
        EMAIL_PROVIDER="smtp",
        SMTP_HOST="127.0.0.1",
        SMTP_PORT=_free_port(),
        SMTP_SECURITY="none",
        SMTP_TIMEOUT=2,
        EMAIL_FROM="no-reply@loyalloop.test",
    )
    queue_email("password_reset", "secret.person@example.com", "Reset", "https://x/reset-password?token=SECRET")
    db.session.commit()
    deliver_pending()
    assert "SECRET" not in caplog.text
    assert "secret.person@example.com" not in caplog.text


@pytest.mark.parametrize(
    "overrides, error",
    [
        ({"EMAIL_PROVIDER": "smtp"}, "requires SMTP_HOST, EMAIL_FROM"),
        (
            {"EMAIL_PROVIDER": "smtp", "SMTP_HOST": "h", "EMAIL_FROM": "a@b.c", "SMTP_SECURITY": "weird"},
            "SMTP_SECURITY",
        ),
        ({"EMAIL_PROVIDER": "carrier-pigeon"}, "EMAIL_PROVIDER must be"),
    ],
)
def test_email_config_is_validated(overrides, error):
    config = {k: getattr(TestConfig, k) for k in dir(TestConfig) if k.isupper()}
    config.update(overrides)
    with pytest.raises(RuntimeError, match=error):
        validate_config(config)
