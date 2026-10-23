"""QR codes for the join page counter sign and customer referral links."""

from app.mfa import qr_svg

from .conftest import enroll, last_email_link, token_from


def test_join_qr_encodes_the_public_join_link(owner, app):
    resp = owner.client.get("/api/v1/programs/current/join-qr.svg")
    assert resp.status_code == 200
    assert resp.mimetype == "image/svg+xml"
    expected_url = app.config["PUBLIC_BASE_URL"].rstrip("/") + f"/join/{owner.business['slug']}"
    with app.app_context():
        assert resp.get_data(as_text=True) == qr_svg(expected_url)  # deterministic encoding of exactly this URL
    assert "<script" not in resp.get_data(as_text=True)

    sign = owner.get("/programs/current/sign").get_json()["data"]
    assert sign["join_url"] == expected_url
    assert sign["rules"]


def test_join_qr_requires_membership(new_api):
    assert new_api().client.get("/api/v1/programs/current/join-qr.svg").status_code == 401


def test_portal_referral_qr_is_for_signed_in_customer_only(owner, new_api, app):
    alice = enroll(owner, "Alice", email="alice.qr@example.com")
    assert new_api().client.get("/api/v1/customer-portal/referral-qr.svg").status_code == 401
    owner.post(f"/customers/{alice['id']}/portal-link")
    portal = new_api()
    portal.post(
        "/customer-portal/session", {"token": token_from(last_email_link("/portal/access", "alice.qr@example.com"))}
    )
    resp = portal.client.get("/api/v1/customer-portal/referral-qr.svg")
    assert resp.status_code == 200 and resp.mimetype == "image/svg+xml"
    expected = (
        app.config["PUBLIC_BASE_URL"].rstrip("/") + f"/join/{owner.business['slug']}?ref={alice['referral_code']}"
    )
    assert resp.get_data(as_text=True) == qr_svg(expected)

    owner.patch("/programs/current", {"referrals_enabled": False})
    assert portal.client.get("/api/v1/customer-portal/referral-qr.svg").status_code == 404
