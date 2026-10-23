"""Platform administration: access control, suspension, manual plan changes."""

import pytest

from app import mfa
from app.extensions import db
from app.models import AuditLog, User

from .conftest import enroll, invite_and_join, last_email_link, purchase, signup, token_from


@pytest.fixture
def admin(new_api):
    api = new_api()
    email = signup(api, name="Ada Admin", email="ada.admin@example.com")
    user = User.query.filter_by(email=email).one()
    user.is_platform_admin = True
    db.session.commit()
    return api


def test_non_admins_are_forbidden(owner, new_api):
    for path in ("/admin/overview", "/admin/businesses"):
        assert owner.get(path).status_code == 403
        assert new_api().get(path).status_code == 401


def test_admin_requires_mfa_when_configured(app, admin):
    app.config["ADMIN_REQUIRE_MFA"] = True
    resp = admin.get("/admin/overview")
    assert resp.status_code == 403 and resp.get_json()["error"]["code"] == "admin_mfa_required"
    setup = admin.post("/auth/mfa/setup").get_json()["data"]
    admin.post("/auth/mfa/enable", {"code": mfa.totp(setup["secret"])})
    assert admin.get("/admin/overview").status_code == 200


def test_admin_lists_businesses_without_customer_data(admin, owner):
    enroll(owner, "Secret Customer", email="secret.customer@example.com")
    data = admin.get("/admin/businesses?q=alpha").get_json()
    assert data["meta"]["total"] == 1
    row = data["data"][0]
    assert row["name"] == "Alpha Cafe" and row["customers"] == 1 and row["owner_email"] == owner.email
    detail = admin.get(f"/admin/businesses/{row['id']}").get_json()["data"]
    assert detail["owners"][0]["email"] == owner.email
    assert "secret.customer@example.com" not in str(detail)
    # Admins have no tenant access to customer records.
    assert admin.get("/customers").status_code == 403
    overview = admin.get("/admin/overview").get_json()["data"]
    assert overview["businesses"] == 1 and overview["customers"] == 1


def test_suspension_blocks_members_public_pages_and_portal(admin, owner, new_api):
    staff = invite_and_join(owner, new_api, "staff")
    alice = enroll(owner, "Alice", email="alice.s@example.com")
    owner.post(f"/customers/{alice['id']}/portal-link")
    portal = new_api()
    portal.post(
        "/customer-portal/session", {"token": token_from(last_email_link("/portal/access", "alice.s@example.com"))}
    )
    assert portal.get("/customer-portal/me").status_code == 200

    bid = owner.business["id"]
    assert admin.post(f"/admin/businesses/{bid}/suspend", {"reason": "x"}).status_code == 422  # reason too short
    assert (
        admin.post(f"/admin/businesses/{bid}/suspend", {"reason": "Chargeback fraud investigation"}).status_code == 200
    )

    blocked = owner.get("/customers")
    assert blocked.status_code == 403 and blocked.get_json()["error"]["code"] == "business_suspended"
    assert staff.get("/customers").status_code == 403
    assert new_api().get(f"/public/programs/{owner.business['slug']}").status_code == 404
    assert portal.get("/customer-portal/me").status_code == 401
    assert admin.get("/admin/businesses?status=suspended").get_json()["meta"]["total"] == 1

    assert admin.post(f"/admin/businesses/{bid}/unsuspend", {"reason": "Investigation closed"}).status_code == 200
    assert owner.get("/customers").status_code == 200
    assert purchase(owner, alice["id"], "10", owner.location_id).status_code == 201  # nothing was lost

    actions = [a.action for a in AuditLog.query.filter_by(business_id=bid)]
    assert "admin.business_suspended" in actions and "admin.business_unsuspended" in actions


def test_admin_plan_change_and_trial_extension(admin, owner):
    bid = owner.business["id"]
    resp = admin.post(f"/admin/businesses/{bid}/plan", {"plan": "pro", "reason": "Invoiced annually"})
    assert resp.get_json()["data"]["billing"]["plan"] == "pro"
    assert owner.get("/auth/me").get_json()["data"]["billing"]["status"] == "active"

    ext = admin.post(f"/admin/businesses/{bid}/plan", {"extend_trial_days": 30, "reason": "Sales extension"})
    billing_state = ext.get_json()["data"]["billing"]
    assert billing_state["plan"] == "trial" and billing_state["status"] == "trialing"
    assert admin.post(f"/admin/businesses/{bid}/plan", {"reason": "nothing chosen"}).status_code == 422
    history = admin.get(f"/admin/businesses/{bid}").get_json()["data"]["history"]
    assert {"admin.plan_changed", "admin.trial_extended"} <= {h["action"] for h in history}


def test_make_admin_cli(app, new_api):
    signup(new_api(), email="future.admin@example.com")
    runner = app.test_cli_runner()
    result = runner.invoke(args=["make-admin", "future.admin@example.com"])
    assert result.exit_code == 0 and "granted" in result.output
    assert User.query.filter_by(email="future.admin@example.com").one().is_platform_admin
    result = runner.invoke(args=["make-admin", "future.admin@example.com", "--revoke"])
    assert not User.query.filter_by(email="future.admin@example.com").one().is_platform_admin
    assert runner.invoke(args=["make-admin", "nobody@example.com"]).exit_code != 0


def test_demo_admin_login(app, new_api):
    from app.seed import seed

    seed(quiet=True)
    api = new_api()
    me = api.post("/auth/demo-login", {"role": "admin"}).get_json()["data"]
    assert me["user"]["is_platform_admin"] is True and me["active_business"] is None
    assert api.get("/admin/overview").status_code == 200


def test_production_requires_admin_mfa():
    from app.config import TestConfig, validate_config

    cfg = {k: getattr(TestConfig, k) for k in dir(TestConfig) if k.isupper()}
    cfg.update(
        APP_ENV="production",
        DEMO_MODE=False,
        COOKIE_SECURE=True,
        BILLING_PROVIDER="none",
        SQLALCHEMY_DATABASE_URI="postgresql://x/y",
        ADMIN_REQUIRE_MFA=False,
    )
    with pytest.raises(RuntimeError, match="ADMIN_REQUIRE_MFA"):
        validate_config(cfg)
