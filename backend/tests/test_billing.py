"""Plans, limits, read-only mode and the Stripe integration (signed webhooks, mocked API)."""

import hashlib
import hmac
import io
import json
import time
import urllib.parse
from datetime import timedelta

import pytest

from app import billing, create_app
from app.config import TestConfig
from app.extensions import db
from app.models import Business, utcnow

from .conftest import enroll, invite_and_join, purchase

STRIPE = {
    "BILLING_PROVIDER": "stripe",
    "STRIPE_SECRET_KEY": "sk_test_dummy",
    "STRIPE_WEBHOOK_SECRET": "whsec_test_secret",
    "STRIPE_PRICES": {"starter": "price_starter", "growth": "price_growth", "pro": "price_pro"},
}


def _business(owner) -> Business:
    return db.session.get(Business, owner.business["id"])


def _expire_trial(owner):
    b = _business(owner)
    b.trial_ends_at = utcnow() - timedelta(minutes=1)
    db.session.commit()


# ------------------------------------------------------------------ trial


def test_new_business_starts_on_trial(owner):
    me = owner.get("/auth/me").get_json()["data"]
    assert me["billing"]["plan"] == "trial"
    assert me["billing"]["status"] == "trialing"
    overview = owner.get("/billing").get_json()["data"]
    assert overview["limits"] == billing.PLANS["growth"]["limits"]
    assert overview["usage"] == {"locations": 1, "customers": 0, "members": 1}
    ends = _business(owner).trial_ends_at
    assert timedelta(days=13) < ends - utcnow() <= timedelta(days=14)


def test_expired_trial_is_read_only_until_a_plan_is_chosen(owner):
    c = enroll(owner)
    _expire_trial(owner)
    blocked = purchase(owner, c["id"], "10.00", owner.location_id)
    assert blocked.status_code == 402 and blocked.get_json()["error"]["code"] == "subscription_inactive"
    assert owner.post("/customers", {"display_name": "X", "email": "x@example.com"}).status_code == 402
    # Reads, privacy and account actions still work
    assert owner.get("/customers").status_code == 200
    assert owner.get(f"/customers/{c['id']}/privacy-export").status_code == 200
    assert owner.post(f"/customers/{c['id']}/consent", {"marketing_opt_in": True}).status_code == 200
    assert owner.patch("/businesses/current", {"name": "Renamed Cafe"}).status_code == 200
    assert owner.get("/auth/me").get_json()["data"]["billing"]["status"] == "trial_expired"

    switched = owner.post("/billing/dev/switch", {"plan": "starter"})
    assert switched.status_code == 200 and switched.get_json()["data"]["status"] == "active"
    assert purchase(owner, c["id"], "10.00", owner.location_id).status_code == 201


def test_public_join_closed_when_inactive(owner, new_api):
    _expire_trial(owner)
    resp = new_api().post(
        f"/public/programs/{owner.business['slug']}/join", {"display_name": "A", "email": "a@example.com"}
    )
    assert resp.status_code == 409


# ------------------------------------------------------------------ limits


def test_location_limit(owner):
    owner.post("/billing/dev/switch", {"plan": "starter"})
    resp = owner.post("/locations", {"name": "Second"})
    assert resp.status_code == 402 and resp.get_json()["error"]["code"] == "plan_limit_reached"
    owner.post("/billing/dev/switch", {"plan": "growth"})
    second = owner.post("/locations", {"name": "Second"}).get_json()["data"]
    owner.patch(f"/locations/{second['id']}", {"status": "archived"})
    owner.post("/billing/dev/switch", {"plan": "starter"})
    # Restoring an archived location also counts against the limit
    assert owner.patch(f"/locations/{second['id']}", {"status": "active"}).status_code == 402


def test_member_limit_counts_pending_invitations(owner, new_api):
    owner.post("/billing/dev/switch", {"plan": "starter"})  # 3 members incl. owner
    invite_and_join(owner, new_api, "staff")
    assert owner.post("/members/invitations", {"email": "two@example.com", "role": "staff"}).status_code == 201
    # Re-sending to the same address does not use another seat
    assert owner.post("/members/invitations", {"email": "two@example.com", "role": "staff"}).status_code == 201
    third = owner.post("/members/invitations", {"email": "three@example.com", "role": "staff"})
    assert third.status_code == 402


def test_customer_limit_staff_and_public(owner, new_api, monkeypatch):
    owner.post("/billing/dev/switch", {"plan": "starter"})
    monkeypatch.setitem(billing.PLANS["starter"]["limits"], "customers", 2)
    enroll(owner)
    enroll(owner)
    assert owner.post("/customers", {"display_name": "C", "email": "c3@example.com"}).status_code == 402
    joined = new_api().post(
        f"/public/programs/{owner.business['slug']}/join", {"display_name": "P", "email": "p@example.com"}
    )
    assert joined.status_code == 409 and joined.get_json()["error"]["code"] == "program_full"


def test_only_owner_manages_billing(owner, new_api):
    manager = invite_and_join(owner, new_api, "manager")
    assert manager.get("/billing").status_code == 403
    assert manager.post("/billing/dev/switch", {"plan": "pro"}).status_code == 403


def test_dev_billing_not_available_with_other_providers(owner, app):
    app.config["BILLING_PROVIDER"] = "none"
    assert owner.post("/billing/dev/switch", {"plan": "pro"}).status_code == 404
    assert owner.post("/billing/checkout", {"plan": "pro"}).status_code == 409


def test_demo_business_always_active(app):
    from app.seed import seed

    seed(quiet=True)
    demo = Business.query.filter_by(is_demo=True).one()
    demo.plan, demo.plan_status = "trial", "trialing"
    demo.trial_ends_at = utcnow() - timedelta(days=1)
    assert billing.in_good_standing(demo)


# ------------------------------------------------------------------ config


def test_billing_config_validation():
    with pytest.raises(RuntimeError, match="STRIPE_SECRET_KEY"):
        create_app(TestConfig, {"BILLING_PROVIDER": "stripe"})
    with pytest.raises(RuntimeError, match="not allowed in production"):
        from app.config import validate_config

        cfg = {k: getattr(TestConfig, k) for k in dir(TestConfig) if k.isupper()}
        cfg.update(
            APP_ENV="production",
            DEMO_MODE=False,
            COOKIE_SECURE=True,
            BILLING_PROVIDER="dev",
            SQLALCHEMY_DATABASE_URI="postgresql://x/y",
        )
        validate_config(cfg)


# ------------------------------------------------------------------ Stripe


def _sign(payload: bytes, secret="whsec_test_secret", ts=None) -> str:
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def test_stripe_signature_verification():
    body = b'{"id":"evt_1"}'
    assert billing.verify_stripe_signature(body, _sign(body), "whsec_test_secret")
    assert not billing.verify_stripe_signature(body, _sign(body, "wrong"), "whsec_test_secret")
    assert not billing.verify_stripe_signature(body + b" ", _sign(body), "whsec_test_secret")
    assert not billing.verify_stripe_signature(body, _sign(body, ts=int(time.time()) - 3600), "whsec_test_secret")
    assert not billing.verify_stripe_signature(body, "garbage", "whsec_test_secret")


@pytest.fixture
def stripe_app(app):
    app.config.update(STRIPE)
    return app


def _post_event(owner, event: dict):
    body = json.dumps(event).encode()
    return owner.client.post(
        "/api/v1/billing/stripe/webhook",
        data=body,
        headers={"Stripe-Signature": _sign(body), "Content-Type": "application/json"},
    )


def test_stripe_webhooks_update_subscription(stripe_app, owner):
    bid = owner.business["id"]
    _expire_trial(owner)
    resp = _post_event(
        owner,
        {
            "id": "evt_checkout",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "object": "checkout.session",
                    "client_reference_id": str(bid),
                    "customer": "cus_123",
                    "subscription": "sub_123",
                    "metadata": {"business_id": str(bid), "plan": "growth"},
                }
            },
        },
    )
    assert resp.status_code == 200 and resp.get_json()["outcome"] == "checkout_completed"
    b = _business(owner)
    db.session.refresh(b)
    assert (b.plan, b.plan_status, b.stripe_customer_id) == ("growth", "active", "cus_123")

    # Duplicate delivery is ignored
    assert (
        _post_event(
            owner, {"id": "evt_checkout", "type": "checkout.session.completed", "data": {"object": {}}}
        ).get_json()["outcome"]
        == "duplicate"
    )

    period_end = int(time.time()) + 30 * 86400
    upgrade = _post_event(
        owner,
        {
            "id": "evt_upgrade",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "object": "subscription",
                    "id": "sub_123",
                    "customer": "cus_123",
                    "status": "active",
                    "current_period_end": period_end,
                    "items": {"data": [{"price": {"id": "price_pro"}}]},
                }
            },
        },
    )
    assert upgrade.get_json()["outcome"] == "subscription_active"
    db.session.refresh(b)
    assert b.plan == "pro" and b.current_period_end is not None

    _post_event(
        owner,
        {
            "id": "evt_fail",
            "type": "invoice.payment_failed",
            "data": {"object": {"object": "invoice", "subscription": "sub_123", "customer": "cus_123"}},
        },
    )
    db.session.refresh(b)
    assert b.plan_status == "past_due" and billing.in_good_standing(b)  # grace while Stripe retries

    _post_event(
        owner,
        {
            "id": "evt_cancel",
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "object": "subscription",
                    "id": "sub_123",
                    "customer": "cus_123",
                    "status": "canceled",
                    "items": {"data": [{"price": {"id": "price_pro"}}]},
                }
            },
        },
    )
    db.session.refresh(b)
    assert b.plan_status == "canceled"
    assert owner.post("/customers", {"display_name": "Late", "email": "late@example.com"}).status_code == 402
    actions = [row["action"] for row in owner.get("/audit-logs").get_json()["data"]]
    assert actions.count("billing.plan_changed") >= 3


def test_stripe_webhook_rejects_bad_signature(stripe_app, owner):
    body = json.dumps({"id": "evt_x", "type": "checkout.session.completed", "data": {"object": {}}}).encode()
    resp = owner.client.post(
        "/api/v1/billing/stripe/webhook",
        data=body,
        headers={"Stripe-Signature": _sign(body, "attacker"), "Content-Type": "application/json"},
    )
    assert resp.status_code == 400


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_checkout_and_portal_call_stripe(stripe_app, owner, monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append((req.full_url, dict(urllib.parse.parse_qsl(req.data.decode())), req.headers))
        url = (
            "https://checkout.stripe.com/c/pay/cs_test"
            if "checkout" in req.full_url
            else "https://billing.stripe.com/p/session"
        )
        return _FakeResponse(json.dumps({"url": url}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    resp = owner.post("/billing/checkout", {"plan": "growth"})
    assert resp.get_json()["data"]["url"].startswith("https://checkout.stripe.com/")
    url, form, headers = calls[0]
    assert url == "https://api.stripe.com/v1/checkout/sessions"
    assert form["mode"] == "subscription"
    assert form["line_items[0][price]"] == "price_growth"
    assert form["metadata[business_id]"] == str(owner.business["id"])
    assert form["subscription_data[metadata][plan]"] == "growth"
    assert form["customer_email"] == owner.email
    assert headers["Authorization"] == "Bearer sk_test_dummy"

    # Portal needs a Stripe customer first
    assert owner.post("/billing/portal").status_code == 409
    b = _business(owner)
    b.stripe_customer_id = "cus_999"
    db.session.commit()
    assert owner.post("/billing/portal").get_json()["data"]["url"].startswith("https://billing.stripe.com/")
    assert calls[-1][1]["customer"] == "cus_999"
