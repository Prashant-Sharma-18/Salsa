"""Two-factor authentication, account lockout, MFA enforcement and proxy handling."""

import time
from datetime import timedelta

from flask import request

from app import create_app, mfa
from app.config import TestConfig
from app.extensions import db
from app.models import User, utcnow

from .conftest import invite_and_join, last_email_link, signup, token_from

PASSWORD = "correct-horse-1"


# ------------------------------------------------------------------- TOTP maths


def test_totp_matches_rfc6238_vectors():
    # RFC 6238 Appendix B, SHA-1 secret "12345678901234567890" (8-digit values truncated to 6).
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert mfa.totp(secret, now=59) == "287082"
    assert mfa.totp(secret, now=1111111109) == "081804"
    assert mfa.totp(secret, now=1234567890) == "005924"
    assert mfa.totp(secret, now=2000000000) == "279037"


def test_totp_accepts_one_step_of_clock_drift_only():
    secret = mfa.new_secret()
    now = 1_700_000_000
    assert mfa.match_step(secret, mfa.totp(secret, now - 30), now) is not None
    assert mfa.match_step(secret, mfa.totp(secret, now + 30), now) is not None
    assert mfa.match_step(secret, mfa.totp(secret, now - 90), now) is None
    assert mfa.match_step(secret, "12345", now) is None


# ------------------------------------------------------------------- helpers


def _enable_mfa(api) -> tuple[str, list[str]]:
    setup = api.post("/auth/mfa/setup").get_json()["data"]
    assert setup["qr_svg"].startswith("data:image/svg+xml")
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    secret = setup["secret"]
    assert api.post("/auth/mfa/enable", {"code": "000000"}).status_code in (422,)  # wrong code first
    resp = api.post("/auth/mfa/enable", {"code": mfa.totp(secret)})
    assert resp.status_code == 200, resp.get_json()
    codes = resp.get_json()["data"]["recovery_codes"]
    assert len(codes) == 10
    return secret, codes


def _next_code(secret: str) -> str:
    """A valid code for the next time step (setup consumed the current one)."""
    return mfa.totp(secret, time.time() + 30)


# ------------------------------------------------------------------- MFA flow


def test_mfa_enrol_and_sign_in(new_api):
    api = new_api()
    email = signup(api, password=PASSWORD)
    secret, _ = _enable_mfa(api)

    user = User.query.filter_by(email=email).one()
    assert user.mfa_secret_encrypted and secret not in user.mfa_secret_encrypted  # encrypted at rest

    browser = new_api()
    first = browser.post("/auth/signin", {"email": email, "password": PASSWORD}).get_json()["data"]
    assert first["mfa_required"] is True and "user" not in first
    assert browser.get("/auth/me").get_json()["data"] is None  # no session yet

    bad = browser.post("/auth/mfa/verify", {"mfa_token": first["mfa_token"], "code": "123456"})
    assert bad.status_code == 401 and bad.get_json()["error"]["code"] == "invalid_code"
    code = _next_code(secret)
    ok = browser.post("/auth/mfa/verify", {"mfa_token": first["mfa_token"], "code": code})
    assert ok.status_code == 200
    assert browser.get("/auth/me").get_json()["data"]["user"]["mfa_enabled"] is True

    # The challenge token is single use and the code cannot be replayed.
    assert browser.post("/auth/mfa/verify", {"mfa_token": first["mfa_token"], "code": code}).status_code == 401
    again = new_api().post("/auth/signin", {"email": email, "password": PASSWORD}).get_json()["data"]
    replay = new_api().post("/auth/mfa/verify", {"mfa_token": again["mfa_token"], "code": code})
    assert replay.status_code == 401


def test_recovery_code_works_once(new_api):
    api = new_api()
    email = signup(api, password=PASSWORD)
    _, codes = _enable_mfa(api)

    def sign_in_with(code):
        b = new_api()
        token = b.post("/auth/signin", {"email": email, "password": PASSWORD}).get_json()["data"]["mfa_token"]
        return b.post("/auth/mfa/verify", {"mfa_token": token, "recovery_code": code})

    assert sign_in_with(codes[0].lower()).status_code == 200
    assert sign_in_with(codes[0]).status_code == 401
    assert api.get("/auth/mfa").get_json()["data"]["recovery_codes_remaining"] == 9
    assert "recovery code was used" in last_email_link_subjects(email)


def last_email_link_subjects(email):
    from app.models import NotificationOutbox

    return " ".join(m.subject.lower() for m in NotificationOutbox.query.filter_by(recipient=email))


def test_challenge_expires_after_too_many_wrong_codes(new_api):
    api = new_api()
    email = signup(api, password=PASSWORD)
    secret, _ = _enable_mfa(api)
    b = new_api()
    token = b.post("/auth/signin", {"email": email, "password": PASSWORD}).get_json()["data"]["mfa_token"]
    for _ in range(5):
        b.post("/auth/mfa/verify", {"mfa_token": token, "code": "000000"})
    resp = b.post("/auth/mfa/verify", {"mfa_token": token, "code": _next_code(secret)})
    assert resp.status_code == 401 and resp.get_json()["error"]["code"] == "mfa_expired"


def test_disable_requires_password_and_code(new_api):
    api = new_api()
    signup(api, password=PASSWORD)
    secret, _ = _enable_mfa(api)
    assert (
        api.post("/auth/mfa/disable", {"password": "wrong-password-1", "code": _next_code(secret)}).status_code == 422
    )
    assert api.post("/auth/mfa/disable", {"password": PASSWORD, "code": "000000"}).status_code == 422
    ok = api.post("/auth/mfa/disable", {"password": PASSWORD, "code": _next_code(secret)})
    assert ok.status_code == 200
    assert api.get("/auth/mfa").get_json()["data"]["enabled"] is False


def test_demo_accounts_cannot_enable_mfa(app, new_api):
    from app.seed import seed

    seed(quiet=True)
    api = new_api()
    api.post("/auth/demo-login", {"role": "owner"})
    assert api.post("/auth/mfa/setup").status_code == 403


# ------------------------------------------------------------------- lockout


def test_account_locks_after_repeated_failures(app, new_api):
    app.config["LOCKOUT_THRESHOLD"] = 3
    api = new_api()
    email = signup(api, password=PASSWORD)
    attacker = new_api()
    for _ in range(2):
        assert attacker.post("/auth/signin", {"email": email, "password": "wrong-password"}).status_code == 401
    locked = attacker.post("/auth/signin", {"email": email, "password": "wrong-password"})
    assert locked.status_code == 423 and locked.get_json()["error"]["code"] == "account_locked"
    # Even the correct password is refused while locked.
    assert new_api().post("/auth/signin", {"email": email, "password": PASSWORD}).status_code == 423
    assert "temporarily locked" in last_email_link_subjects(email)

    # Lock expires.
    user = User.query.filter_by(email=email).one()
    user.locked_until = utcnow() - timedelta(seconds=1)
    db.session.commit()
    assert new_api().post("/auth/signin", {"email": email, "password": PASSWORD}).status_code == 200


def test_password_reset_clears_lockout(app, new_api):
    app.config["LOCKOUT_THRESHOLD"] = 2
    api = new_api()
    email = signup(api, password=PASSWORD)
    for _ in range(2):
        new_api().post("/auth/signin", {"email": email, "password": "wrong-password"})
    assert new_api().post("/auth/signin", {"email": email, "password": PASSWORD}).status_code == 423
    new_api().post("/auth/password-reset/request", {"email": email})
    token = token_from(last_email_link("/reset-password", email))
    new_api().post("/auth/password-reset/confirm", {"token": token, "password": "fresh-password-9"})
    assert new_api().post("/auth/signin", {"email": email, "password": "fresh-password-9"}).status_code == 200


def test_successful_signin_resets_failure_count(app, new_api):
    app.config["LOCKOUT_THRESHOLD"] = 3
    api = new_api()
    email = signup(api, password=PASSWORD)
    for _ in range(2):
        new_api().post("/auth/signin", {"email": email, "password": "wrong-password"})
    assert new_api().post("/auth/signin", {"email": email, "password": PASSWORD}).status_code == 200
    for _ in range(2):
        assert new_api().post("/auth/signin", {"email": email, "password": "wrong-password"}).status_code == 401


# ------------------------------------------------------------- business policy


def test_business_can_require_mfa_for_owners_and_managers(owner, new_api):
    manager = invite_and_join(owner, new_api, "manager")
    staff = invite_and_join(owner, new_api, "staff")

    # Owner must have MFA before requiring it.
    assert owner.patch("/businesses/current", {"require_mfa": True}).status_code == 409
    _enable_mfa(owner)
    assert owner.patch("/businesses/current", {"require_mfa": True}).status_code == 200

    blocked = manager.get("/customers")
    assert blocked.status_code == 403 and blocked.get_json()["error"]["code"] == "mfa_setup_required"
    assert manager.get("/auth/me").get_json()["data"]["mfa_setup_required"] is True
    assert staff.get("/customers").status_code == 200  # staff are not affected
    assert owner.get("/customers").status_code == 200

    secret, _ = _enable_mfa(manager)
    assert manager.get("/customers").status_code == 200
    # Cannot switch MFA off while a business requires it.
    resp = manager.post("/auth/mfa/disable", {"password": "member-pass-123", "code": _next_code(secret)})
    assert resp.status_code == 409 and resp.get_json()["error"]["code"] == "mfa_required_by_business"
    actions = {row["action"] for row in owner.get("/audit-logs").get_json()["data"]}
    assert "business.require_mfa_changed" in actions
    # Enrolment is a user-level event (users can belong to several businesses).
    from app.models import AuditLog

    assert AuditLog.query.filter_by(action="mfa.enabled", business_id=None).count() == 2


# ------------------------------------------------------------------- proxies


def _ip_app(proxy_count: int):
    app = create_app(TestConfig, {"TRUSTED_PROXY_COUNT": proxy_count})
    app.add_url_rule("/whoami", "whoami", lambda: request.remote_addr or "")
    return app


def test_client_ip_from_trusted_proxy_only():
    headers = {"X-Forwarded-For": "203.0.113.7"}
    trusted = _ip_app(1).test_client().get("/whoami", headers=headers, environ_base={"REMOTE_ADDR": "10.0.0.2"})
    assert trusted.get_data(as_text=True) == "203.0.113.7"
    untrusted = _ip_app(0).test_client().get("/whoami", headers=headers, environ_base={"REMOTE_ADDR": "10.0.0.2"})
    assert untrusted.get_data(as_text=True) == "10.0.0.2"  # spoofed header ignored without a trusted proxy


def test_invalid_mfa_encryption_key_is_rejected():
    import pytest

    with pytest.raises(RuntimeError, match="MFA_ENCRYPTION_KEY"):
        create_app(TestConfig, {"MFA_ENCRYPTION_KEY": "not-a-fernet-key"})
