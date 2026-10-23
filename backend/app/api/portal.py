"""Customer-facing endpoints.

Customers authenticate with single-use, expiring magic links that are
exchanged for an HttpOnly portal session cookie. Every portal query is scoped
to ``g.customer``; no endpoint accepts a customer ID from the client.
"""

from flask import Blueprint, Response, current_app, g, jsonify, make_response

from .. import billing
from ..email import link
from ..errors import ApiError, NotFound
from ..extensions import db, limiter
from ..models import (
    Business,
    Customer,
    CustomerAccessToken,
    LoyaltyProgram,
    PointLedgerEntry,
    Redemption,
    Reward,
    utcnow,
)
from ..security import clear_cookie, create_customer_session, hash_token, portal_required
from ..services import customers, redemptions, referrals
from ..validation import Fields, body
from .customers import idempotency_key, issue_portal_link

bp = Blueprint("portal", __name__)


def _program_public(business: Business, program: LoyaltyProgram) -> dict:
    return {
        "business_name": business.name,
        "slug": business.slug,
        "name": program.name,
        "description": program.description,
        "status": program.status,
        "brand_color": program.brand_color,
        "logo_url": program.logo_url,
        "contact_email": program.contact_email,
        "contact_phone": program.contact_phone,
        "rules": program.rules_summary(),
        "referrals_enabled": program.referrals_enabled,
        "is_demo": business.is_demo,
    }


def _business_by_slug(slug: str) -> tuple[Business, LoyaltyProgram]:
    business = Business.query.filter_by(slug=slug).first()
    program = LoyaltyProgram.query.filter_by(business_id=business.id).first() if business else None
    if not business or not program or program.status == "draft" or business.suspended_at:
        raise NotFound("Program not found")
    return business, program


# ------------------------------------------------------------------- public


@bp.get("/public/programs/<slug>")
@limiter.limit("60 per minute")
def public_program(slug):
    business, program = _business_by_slug(slug)
    data = _program_public(business, program)
    data["rewards"] = [
        {"name": r.name, "points_cost": r.points_cost, "description": r.description}
        for r in Reward.query.filter_by(business_id=business.id, status="active").order_by(Reward.points_cost)
    ]
    return jsonify({"data": data})


@bp.post("/public/programs/<slug>/join")
@limiter.limit("5 per minute;30 per hour")
def public_join(slug):
    """Self-enrollment. Responds identically whether or not the email already exists (no enumeration)."""
    business, program = _business_by_slug(slug)
    if program.status != "active" or not billing.in_good_standing(business):
        raise ApiError("This program is not accepting new members right now", code="program_paused", status=409)
    f = Fields(body())
    f.string("display_name", max_len=120)
    f.email("email")
    f.boolean("marketing_opt_in", default=False)
    f.string("ref", required=False, max_len=16)
    data = f.check()
    existing = customers.find_by_email(business.id, data["email"])
    if existing:
        if existing.status == "active":
            issue_portal_link(existing, business.name)
    else:
        try:
            billing.check_limit(business, "customers")
        except billing.PaymentRequired:
            raise ApiError("This program is not accepting new members right now", code="program_full", status=409)
        customer = customers.enroll(
            business.id, data["display_name"], data["email"], None, data["marketing_opt_in"], source="join_page"
        )
        referrals.attribute_signup(business.id, customer, data.get("ref"), source="link")
        issue_portal_link(customer, business.name)
    db.session.commit()
    return jsonify({"data": {"message": "Check your email for a link to your rewards account."}}), 202


# ------------------------------------------------------------------- portal auth


@bp.post("/customer-portal/request-link")
@limiter.limit("5 per minute;20 per hour")
def request_link():
    f = Fields(body())
    slug = f.string("business_slug", max_len=80)
    email = f.email("email")
    f.check()
    business = Business.query.filter_by(slug=slug).first()
    if business and not business.suspended_at:
        customer = customers.find_by_email(business.id, email)
        if customer and customer.status == "active":
            issue_portal_link(customer, business.name)
            db.session.commit()
    return jsonify({"data": {"message": "If you are a member, a sign-in link has been sent to your email."}}), 202


@bp.post("/customer-portal/session")
@limiter.limit("10 per minute")
def exchange_link():
    f = Fields(body())
    token = f.string("token", max_len=200)
    f.check()
    record = CustomerAccessToken.query.filter_by(token_hash=hash_token(token)).first()
    if not record or record.used_at or record.expires_at < utcnow():
        raise ApiError("This link is invalid or has expired. Request a new one.", code="invalid_token", status=400)
    record.used_at = utcnow()
    customer = db.session.get(Customer, record.customer_id)
    if customer.status != "active":
        raise ApiError("This account is not active", code="inactive", status=403)
    response = make_response()
    session = create_customer_session(response, customer)
    db.session.commit()
    business = db.session.get(Business, customer.business_id)
    response.set_data(jsonify({"data": {"csrf_token": session.csrf_token, "business_slug": business.slug}}).get_data())
    response.mimetype = "application/json"
    return response


@bp.post("/customer-portal/signout")
@portal_required
def portal_signout():
    g.portal_session.revoked_at = utcnow()
    db.session.commit()
    response = jsonify({"data": {"signed_out": True}})
    clear_cookie(response, current_app.config["PORTAL_COOKIE_NAME"])
    return response


# ------------------------------------------------------------------- portal data


@bp.get("/customer-portal/me")
@portal_required
def portal_me():
    customer: Customer = g.customer
    business = db.session.get(Business, customer.business_id)
    program = LoyaltyProgram.query.filter_by(business_id=business.id).one()
    return jsonify(
        {
            "data": {
                "csrf_token": g.portal_session.csrf_token,
                "customer": {
                    "display_name": customer.display_name,
                    "email": customer.email,
                    "points_balance": customer.points_balance,
                    "enrolled_at": customer.to_dict()["enrolled_at"],
                    "marketing_opt_in": customer.marketing_opt_in,
                    "referral_code": customer.referral_code,
                    "referral_url": link(f"/join/{business.slug}?ref={customer.referral_code}")
                    if program.referrals_enabled
                    else None,
                },
                "program": dict(_program_public(business, program), redemption_enabled=program.redemption_enabled),
                "rewards": [
                    r.to_dict()
                    for r in Reward.query.filter_by(business_id=business.id, status="active").order_by(
                        Reward.points_cost
                    )
                ],
                "ledger": [
                    {k: v for k, v in e.to_dict().items() if k not in ("actor", "customer_id", "source_id")}
                    for e in PointLedgerEntry.query.filter_by(customer_id=customer.id)
                    .order_by(PointLedgerEntry.created_at.desc(), PointLedgerEntry.id.desc())
                    .limit(50)
                ],
                "redemptions": [
                    r.to_dict(include_customer=False)
                    for r in Redemption.query.filter_by(customer_id=customer.id)
                    .order_by(Redemption.created_at.desc())
                    .limit(20)
                ],
            }
        }
    )


@bp.post("/customer-portal/redemptions")
@portal_required
@limiter.limit("10 per minute")
def portal_redeem():
    customer: Customer = g.customer
    key = idempotency_key()
    f = Fields(body())
    reward_id = f.integer("reward_id")
    f.check()
    business = db.session.get(Business, customer.business_id)
    if not billing.in_good_standing(business):
        raise ApiError(
            "Rewards can't be redeemed online right now. Please ask staff in store.", code="unavailable", status=409
        )
    reward = Reward.query.filter_by(id=reward_id, business_id=customer.business_id).first()
    if not reward:
        raise NotFound("Reward not found")
    try:
        redemption, duplicate = redemptions.issue(
            customer.business_id, customer, reward, f"portal:{customer.id}:{key}", via="customer_portal"
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return jsonify({"data": redemption.to_dict(include_customer=False)}), 200 if duplicate else 201


@bp.get("/customer-portal/referral-qr.svg")
@portal_required
def portal_referral_qr():
    """QR code of the signed-in customer's own referral link."""
    from ..mfa import qr_svg

    customer: Customer = g.customer
    business = db.session.get(Business, customer.business_id)
    program = LoyaltyProgram.query.filter_by(business_id=business.id).one()
    if not program.referrals_enabled:
        raise NotFound("Referrals are not enabled")
    svg = qr_svg(link(f"/join/{business.slug}?ref={customer.referral_code}"))
    return Response(svg, mimetype="image/svg+xml", headers={"Cache-Control": "private, max-age=300"})


@bp.patch("/customer-portal/consent")
@portal_required
def portal_consent():
    f = Fields(body())
    granted = f.boolean("marketing_opt_in", required=True)
    f.check()
    customers.set_marketing_consent(g.customer, granted, source="customer_portal")
    db.session.commit()
    return jsonify({"data": {"marketing_opt_in": g.customer.marketing_opt_in}})
