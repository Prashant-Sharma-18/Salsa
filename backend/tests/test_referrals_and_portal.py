from datetime import timedelta

from app.extensions import db
from app.models import CustomerAccessToken, Referral, utcnow

from .conftest import enroll, last_email_link, purchase, token_from


def _setup_program(owner, **overrides):
    settings = {"referrer_reward_points": 100, "referee_reward_points": 50, "referral_min_spend": "10.00", **overrides}
    assert owner.patch("/programs/current", settings).status_code == 200


def _balance(owner, cid):
    return owner.get(f"/customers/{cid}").get_json()["data"]["points_balance"]


def test_qualified_referral_awards_configured_reward_once(owner):
    _setup_program(owner)
    referrer = enroll(owner, "Referrer")
    friend = enroll(owner, "Friend", referral_code=referrer["referral_code"].lower())
    assert friend["referral"]["status"] == "signed_up"

    small = purchase(owner, friend["id"], "5.00", owner.location_id)  # below referral minimum
    assert small.status_code == 201
    assert _balance(owner, referrer["id"]) == 0

    purchase(owner, friend["id"], "20.00", owner.location_id)
    assert _balance(owner, referrer["id"]) == 100
    assert _balance(owner, friend["id"]) == 5 + 20 + 50
    referral = owner.get("/referrals").get_json()["data"][0]
    assert referral["status"] == "rewarded"

    purchase(owner, friend["id"], "30.00", owner.location_id)
    assert _balance(owner, referrer["id"]) == 100  # no duplicate reward


def test_self_referral_rejected(owner):
    _setup_program(owner)
    referrer = enroll(owner, "Self", email="self@example.com", phone="503-555-0199")
    twin = enroll(
        owner, "Self Again", email="self2@example.com", phone="(503) 555-0199", referral_code=referrer["referral_code"]
    )
    assert twin["referral"]["status"] == "rejected"
    assert twin["referral"]["rejection_reason"] == "Self-referral"
    purchase(owner, twin["id"], "50", owner.location_id)
    assert _balance(owner, referrer["id"]) == 0

    resp = owner.post("/referrals", {"referrer_customer_id": referrer["id"], "email": "self@example.com"})
    assert resp.status_code == 409


def test_invalid_referral_code_rejected(owner):
    resp = owner.post("/customers", {"display_name": "X", "email": "x@example.com", "referral_code": "NOTREAL1"})
    assert resp.status_code == 422


def test_client_cannot_bypass_qualification(owner):
    _setup_program(owner)
    referrer = enroll(owner, "R")
    friend = enroll(owner, "F", referral_code=referrer["referral_code"])
    referral_id = friend["referral"]["id"]
    # No endpoint accepts a status; extra fields are ignored and purchases below the minimum don't qualify
    owner.patch(f"/customers/{friend['id']}", {"display_name": "F", "status": "active", "referral_status": "qualified"})
    purchase(owner, friend["id"], "9.99", owner.location_id, referral_status="qualified")
    assert db.session.get(Referral, referral_id).status == "signed_up"
    assert _balance(owner, referrer["id"]) == 0


def test_referrals_disabled_awards_nothing(owner):
    _setup_program(owner, referrals_enabled=False)
    referrer = enroll(owner, "R")
    friend = enroll(owner, "F", referral_code=referrer["referral_code"])
    assert friend["referral"] is None
    purchase(owner, friend["id"], "50", owner.location_id)
    assert _balance(owner, referrer["id"]) == 0


def test_pending_referral_converts_on_join(owner, new_api):
    _setup_program(owner)
    referrer = enroll(owner, "R", email="r@example.com")
    owner.post("/referrals", {"referrer_customer_id": referrer["id"], "email": "pal@example.com"})
    slug = owner.business["slug"]
    public = new_api()
    resp = public.post(
        f"/public/programs/{slug}/join",
        {"display_name": "Pal", "email": "PAL@example.com", "ref": referrer["referral_code"]},
    )
    assert resp.status_code == 202
    referrals = owner.get("/referrals").get_json()["data"]
    assert len(referrals) == 1 and referrals[0]["status"] == "signed_up"


# ------------------------------------------------------------------ customer portal


def _portal_login(new_api, email):
    portal = new_api()
    token = token_from(last_email_link("/portal/access", email))
    resp = portal.post("/customer-portal/session", {"token": token})
    assert resp.status_code == 200, resp.get_json()
    return portal, token


def test_portal_link_is_single_use_and_scoped_to_customer(owner, new_api):
    alice = enroll(owner, "Alice", email="alice@example.com")
    bob = enroll(owner, "Bob", email="bob@example.com")
    purchase(owner, alice["id"], "42.00", owner.location_id)
    purchase(owner, bob["id"], "7.00", owner.location_id)
    owner.post(f"/customers/{alice['id']}/portal-link")
    portal, token = _portal_login(new_api, "alice@example.com")

    me = portal.get("/customer-portal/me").get_json()["data"]
    assert me["customer"]["display_name"] == "Alice"
    assert me["customer"]["points_balance"] == 42
    text = str(me)
    assert "Bob" not in text and "bob@example.com" not in text
    assert me["customer"]["referral_url"].endswith(f"ref={alice['referral_code']}")

    # Token cannot be reused
    assert new_api().post("/customer-portal/session", {"token": token}).status_code == 400
    # Portal session cannot reach staff endpoints
    assert portal.get(f"/customers/{bob['id']}").status_code == 401
    assert portal.get("/customers").status_code == 401


def test_portal_link_expires(owner, new_api):
    alice = enroll(owner, "Alice", email="alice2@example.com")
    owner.post(f"/customers/{alice['id']}/portal-link")
    CustomerAccessToken.query.update({"expires_at": utcnow() - timedelta(minutes=1)})
    db.session.commit()
    token = token_from(last_email_link("/portal/access", "alice2@example.com"))
    assert new_api().post("/customer-portal/session", {"token": token}).status_code == 400


def test_portal_redeem_and_consent(owner, new_api):
    alice = enroll(owner, "Alice", email="alice3@example.com")
    purchase(owner, alice["id"], "120.00", owner.location_id)
    reward = owner.post("/rewards", {"name": "Mug", "reward_type": "free_item", "points_cost": 100}).get_json()["data"]
    owner.post(f"/customers/{alice['id']}/portal-link")
    portal, _ = _portal_login(new_api, "alice3@example.com")
    portal.get("/customer-portal/me")  # obtains CSRF token

    resp = portal.post("/customer-portal/redemptions", {"reward_id": reward["id"]}, idem="portal-key-01")
    assert resp.status_code == 201
    assert resp.get_json()["data"]["status"] == "issued"
    assert portal.get("/customer-portal/me").get_json()["data"]["customer"]["points_balance"] == 20
    again = portal.post("/customer-portal/redemptions", {"reward_id": reward["id"]}, idem="portal-key-02")
    assert again.status_code == 409

    assert portal.patch("/customer-portal/consent", {"marketing_opt_in": True}).get_json()["data"]["marketing_opt_in"]
    history = owner.get(f"/customers/{alice['id']}").get_json()["data"]["consent_history"]
    assert history[0]["granted"] is True and history[0]["source"] == "customer_portal"

    portal.csrf = None
    assert portal.patch("/customer-portal/consent", {"marketing_opt_in": False}).status_code == 403


def test_public_join_does_not_reveal_existing_members(owner, new_api):
    enroll(owner, "Existing", email="existing@example.com")
    slug = owner.business["slug"]
    public = new_api()
    existing = public.post(f"/public/programs/{slug}/join", {"display_name": "X", "email": "existing@example.com"})
    fresh = public.post(f"/public/programs/{slug}/join", {"display_name": "Y", "email": "brand.new@example.com"})
    assert existing.status_code == fresh.status_code == 202
    assert existing.get_json() == fresh.get_json()
    assert owner.get("/customers").get_json()["meta"]["total"] == 2


def test_anonymize_removes_personal_data_and_keeps_ledger(owner, new_api):
    alice = enroll(owner, "Alice", email="alice4@example.com", phone="5035550123")
    purchase(owner, alice["id"], "10", owner.location_id)
    owner.post(f"/customers/{alice['id']}/portal-link")
    portal, _ = _portal_login(new_api, "alice4@example.com")
    export = owner.get(f"/customers/{alice['id']}/privacy-export").get_json()["data"]
    assert export["customer"]["email"] == "alice4@example.com"
    assert owner.post(f"/customers/{alice['id']}/anonymize", {"confirm": "nope"}).status_code == 422
    resp = owner.post(f"/customers/{alice['id']}/anonymize", {"confirm": "DELETE"})
    data = resp.get_json()["data"]
    assert data["email"] is None and data["phone"] is None and data["status"] == "anonymized"
    assert len(owner.get(f"/customers/{alice['id']}/ledger").get_json()["data"]) == 1
    assert portal.get("/customer-portal/me").status_code == 401
