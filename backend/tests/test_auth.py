from datetime import timedelta

from app.extensions import db
from app.models import BusinessInvitation, utcnow

from .conftest import create_business, last_email_link, signup, token_from, verify_email

PROTECTED = [
    ("get", "/customers"),
    ("get", "/programs/current"),
    ("get", "/rewards"),
    ("get", "/referrals"),
    ("get", "/analytics/summary"),
    ("get", "/exports/customers.csv"),
    ("get", "/members"),
    ("post", "/purchases"),
    ("post", "/redemptions"),
    ("get", "/customer-portal/me"),
]


def test_unauthenticated_requests_are_rejected(new_api):
    api = new_api()
    for method, path in PROTECTED:
        resp = getattr(api, method)(path)
        assert resp.status_code == 401, (method, path, resp.status_code)
        assert "password" not in resp.get_data(as_text=True)


def test_signup_signin_signout(new_api):
    api = new_api()
    email = signup(api, password="long-enough-pw")
    me = api.get("/auth/me").get_json()["data"]
    assert me["user"]["email"] == email
    assert "password_hash" not in str(me)
    assert api.post("/auth/signout").status_code == 200
    assert api.get("/auth/me").get_json()["data"] is None

    bad = api.post("/auth/signin", {"email": email, "password": "wrong-password"})
    assert bad.status_code == 401
    good = api.post("/auth/signin", {"email": email.upper(), "password": "long-enough-pw"})
    assert good.status_code == 200


def test_signup_validation_errors(new_api):
    resp = new_api().post("/auth/signup", {"display_name": "", "email": "nope", "password": "short"})
    assert resp.status_code == 422
    fields = resp.get_json()["error"]["fields"]
    assert set(fields) == {"display_name", "email", "password"}


def test_state_change_requires_csrf_token(new_api):
    api = new_api()
    signup(api)
    api.csrf = None
    resp = api.post("/businesses", {"name": "No CSRF", "location_name": "Main"})
    assert resp.status_code == 403


def test_non_json_writes_rejected(new_api):
    api = new_api()
    resp = api.client.post(
        "/api/v1/auth/signin", data="email=a@b.co&password=x", content_type="application/x-www-form-urlencoded"
    )
    assert resp.status_code == 415


def test_password_reset_is_single_use_and_revokes_sessions(new_api):
    api = new_api()
    email = signup(api, password="original-pass-1")
    other = new_api()
    assert other.post("/auth/password-reset/request", {"email": email}).status_code == 200
    token = token_from(last_email_link("/reset-password", email))
    assert (
        other.post("/auth/password-reset/confirm", {"token": token, "password": "brand-new-pass-1"}).status_code == 200
    )
    reuse = other.post("/auth/password-reset/confirm", {"token": token, "password": "another-pass-12"})
    assert reuse.status_code == 400
    # Old session revoked
    assert api.get("/auth/me").get_json()["data"] is None
    assert other.post("/auth/signin", {"email": email, "password": "brand-new-pass-1"}).status_code == 200


def test_password_reset_request_does_not_reveal_accounts(new_api):
    resp = new_api().post("/auth/password-reset/request", {"email": "nobody@example.com"})
    assert resp.status_code == 200


def test_email_verification(new_api):
    api = new_api()
    email = signup(api)
    assert api.get("/auth/me").get_json()["data"]["user"]["email_verified"] is False
    verify_email(api, email)
    assert api.get("/auth/me").get_json()["data"]["user"]["email_verified"] is True


def test_invitation_expires_and_cannot_be_reused(owner, new_api):
    resp = owner.post("/members/invitations", {"email": "new.staff@example.com", "role": "staff"})
    assert resp.status_code == 201
    token = token_from(last_email_link("/invite/", "new.staff@example.com"))

    # Expire it
    invitation = BusinessInvitation.query.filter_by(email="new.staff@example.com").one()
    invitation.expires_at = utcnow() - timedelta(minutes=1)
    db.session.commit()
    joiner = new_api()
    expired = joiner.post(f"/auth/invitations/{token}/accept", {"display_name": "S", "password": "member-pass-123"})
    assert expired.status_code == 409
    assert expired.get_json()["error"]["code"] == "invitation_expired"

    # Fresh invite works once
    owner.post("/members/invitations", {"email": "new.staff@example.com", "role": "staff"})
    token2 = token_from(last_email_link("/invite/", "new.staff@example.com"))
    ok = joiner.post(f"/auth/invitations/{token2}/accept", {"display_name": "S", "password": "member-pass-123"})
    assert ok.status_code == 200
    assert ok.get_json()["data"]["role"] == "staff"
    again = new_api().post(f"/auth/invitations/{token2}/accept", {"display_name": "X", "password": "member-pass-123"})
    assert again.status_code == 409
    assert again.get_json()["error"]["code"] == "invitation_used"


def test_invitation_requires_verified_email(new_api):
    api = new_api()
    signup(api)
    create_business(api)
    resp = api.post("/members/invitations", {"email": "x@example.com", "role": "staff"})
    assert resp.status_code == 403


def test_cannot_invite_owner_role(owner):
    resp = owner.post("/members/invitations", {"email": "boss@example.com", "role": "owner"})
    assert resp.status_code == 422


def test_demo_login_disabled_outside_demo_mode(app, new_api):
    app.config["DEMO_MODE"] = False
    assert new_api().post("/auth/demo-login", {"role": "owner"}).status_code == 404


def test_health_and_meta_do_not_leak_secrets(new_api):
    api = new_api()
    health = api.client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.get_json() == {"status": "ok", "database": "ok"}
    text = api.client.get("/api/v1/meta").get_data(as_text=True)
    assert "secret" not in text.lower()
