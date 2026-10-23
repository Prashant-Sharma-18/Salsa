"""Request IDs, privacy-safe logging and Sentry scrubbing."""

import logging

import pytest

from app import create_app, observability
from app.config import TestConfig


def _boom_app(**overrides):
    app = create_app(TestConfig, overrides)

    @app.get("/api/v1/boom")
    def boom():
        raise RuntimeError("failure for jane.doe@example.com token abcdefghijklmnopqrstuvwxyz0123456789ABCD")

    return app


def test_every_response_has_a_request_id(new_api):
    resp = new_api().client.get("/api/v1/health")
    assert len(resp.headers["X-Request-ID"]) == 32
    supplied = new_api().client.get("/api/v1/health", headers={"X-Request-ID": "trace-12345678"})
    assert supplied.headers["X-Request-ID"] == "trace-12345678"
    bad = new_api().client.get("/api/v1/health", headers={"X-Request-ID": "<script>"})
    assert bad.headers["X-Request-ID"] != "<script>"


def test_server_errors_return_reference_and_are_reported(monkeypatch, caplog):
    captured = []
    monkeypatch.setattr("sentry_sdk.capture_exception", lambda err: captured.append(err))
    app = _boom_app()
    with caplog.at_level(logging.ERROR):
        resp = app.test_client().get("/api/v1/boom")
    body = resp.get_json()["error"]
    assert resp.status_code == 500 and body["code"] == "server_error"
    assert body["request_id"] == resp.headers["X-Request-ID"]
    assert body["request_id"] in body["message"]
    assert "jane.doe" not in body["message"]  # internals never leak to the client
    assert len(captured) == 1 and isinstance(captured[0], RuntimeError)


def test_access_log_never_contains_query_strings(new_api, caplog):
    with caplog.at_level(logging.INFO, logger="loyalloop.request"):
        new_api().client.get("/api/v1/auth/invitations/secret-token-value?token=supersecret")
    lines = [r.getMessage() for r in caplog.records if r.name == "loyalloop.request"]
    assert lines and "supersecret" not in " ".join(lines)
    assert "status=404" in lines[-1] or "status=4" in lines[-1]


def test_scrub_event_removes_sensitive_data():
    event = {
        "request": {
            "url": "https://app.example.com/portal/access?token=abc",
            "query_string": "token=abc",
            "cookies": {"ll_session": "x"},
            "data": {"password": "hunter2"},
            "headers": {"Cookie": "a", "X-CSRF-Token": "b", "Stripe-Signature": "c", "User-Agent": "UA"},
        },
        "user": {"id": 7, "email": "owner@example.com", "ip_address": "1.2.3.4"},
        "exception": {"values": [{"type": "ValueError", "value": "bad email jane@example.com"}]},
        "message": "token AbCdEfGhIjKlMnOpQrStUvWxYz0123456789 leaked",
        "breadcrumbs": {"values": [{"message": "sql for bob@example.com", "data": {"params": ["secret"]}}]},
    }
    out = observability.scrub_event(event)
    req = out["request"]
    assert "cookies" not in req and "data" not in req and "query_string" not in req
    assert req["url"] == "https://app.example.com/portal/access"
    assert req["headers"] == {"User-Agent": "UA"}
    assert out["user"] == {"id": 7}
    assert out["exception"]["values"][0]["value"] == "bad email [email]"
    assert "[token]" in out["message"]
    assert out["breadcrumbs"]["values"][0] == {"message": "sql for [email]"}


def test_sentry_only_initialises_with_a_dsn(monkeypatch):
    calls = []
    monkeypatch.setattr("sentry_sdk.init", lambda **kw: calls.append(kw))
    create_app(TestConfig)
    assert calls == []
    create_app(TestConfig, {"SENTRY_DSN": "https://public@o0.ingest.sentry.io/0", "APP_RELEASE": "abc123"})
    assert len(calls) == 1
    kw = calls[0]
    assert kw["send_default_pii"] is False
    assert kw["before_send"] is observability.scrub_event
    assert kw["release"] == "abc123" and kw["environment"] == "test"
    assert kw["max_request_body_size"] == "never"


@pytest.mark.parametrize("text", ["contact a.b@c.io now", "key 0123456789abcdef0123456789abcdef0"])
def test_redact(text):
    assert "@" not in observability.redact(text) or "[email]" in observability.redact(text)
    assert "0123456789abcdef0123456789abcdef0" not in observability.redact(text)
