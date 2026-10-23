import re

from flask import Blueprint, current_app, g, jsonify, request

from .. import billing
from ..email import link, queue_email
from ..errors import ApiError, Conflict, ValidationError
from ..extensions import db, limiter
from ..models import (
    ConsentRecord,
    CustomerAccessToken,
    LoyaltyProgram,
    PointLedgerEntry,
    Redemption,
    Referral,
    utcnow,
)
from ..security import current_tenant, hash_token, new_token, require
from ..services import audit, customers, ledger, purchases, referrals
from ..validation import Fields, body, paginate

bp = Blueprint("customers", __name__)

IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9_\-:.]{8,64}$")


def idempotency_key() -> str:
    key = request.headers.get("Idempotency-Key", "")
    if not IDEMPOTENCY_RE.match(key):
        raise ValidationError("An Idempotency-Key header (8-64 safe characters) is required for this request")
    return key


# --------------------------------------------------------------------- customers


@bp.get("/customers")
@require("customers.view")
def list_customers():
    tenant = current_tenant()
    status = request.args.get("status") or None
    if status and status not in ("active", "inactive", "anonymized"):
        raise ValidationError("Invalid status filter")
    query = customers.search(tenant.business_id, request.args.get("q"), status)
    return jsonify(paginate(query, lambda c: c.to_dict()))


@bp.post("/customers")
@require("customers.create")
def enroll_customer():
    tenant = current_tenant()
    f = Fields(body())
    f.string("display_name", max_len=120)
    f.email("email", required=False)
    f.phone("phone")
    f.boolean("marketing_opt_in", default=False)
    f.integer("location_id", required=False)
    f.string("referral_code", required=False, max_len=16)
    data = f.check()
    if not data.get("email") and not data.get("phone"):
        raise ValidationError(
            "Provide an email or phone number so the customer can be found later",
            fields={"email": "Email or phone required"},
        )
    location = tenant.require_location(data.get("location_id"), required=False)
    billing.check_limit(tenant.business, "customers")
    customer = customers.enroll(
        tenant.business_id,
        data["display_name"],
        data.get("email"),
        data.get("phone"),
        data["marketing_opt_in"],
        source="staff",
        location_id=location.id if location else None,
        actor_id=g.user.id,
    )
    referral = None
    if data.get("referral_code"):
        if not referrals.find_referrer(tenant.business_id, data["referral_code"]):
            raise ValidationError("Referral code not found", fields={"referral_code": "Not a valid referral code"})
        referral = referrals.attribute_signup(tenant.business_id, customer, data["referral_code"], source="staff")
    audit.record("customer.enrolled", business_id=tenant.business_id, target_type="customer", target_id=customer.id)
    db.session.commit()
    result = customer.to_dict(detail=True)
    result["referral"] = referral.to_dict() if referral else None
    return jsonify({"data": result}), 201


@bp.get("/customers/<int:customer_id>")
@require("customers.view")
def get_customer(customer_id):
    tenant = current_tenant()
    customer = customers.get_customer(tenant.business_id, customer_id)
    data = customer.to_dict(detail=True)
    data["recent_ledger"] = [
        e.to_dict()
        for e in PointLedgerEntry.query.filter_by(customer_id=customer.id)
        .order_by(PointLedgerEntry.created_at.desc(), PointLedgerEntry.id.desc())
        .limit(10)
    ]
    data["open_redemptions"] = [
        r.to_dict(include_customer=False)
        for r in Redemption.query.filter_by(customer_id=customer.id, status="issued").order_by(
            Redemption.created_at.desc()
        )
    ]
    referred_by = Referral.query.filter_by(referred_customer_id=customer.id).first()
    data["referred_by"] = referred_by.to_dict() if referred_by else None
    data["referrals_made"] = [
        r.to_dict()
        for r in Referral.query.filter_by(referrer_customer_id=customer.id).order_by(Referral.created_at.desc())
    ]
    data["consent_history"] = [
        c.to_dict() for c in ConsentRecord.query.filter_by(customer_id=customer.id).order_by(ConsentRecord.id.desc())
    ]
    return jsonify({"data": data})


@bp.patch("/customers/<int:customer_id>")
@require("customers.edit")
def update_customer(customer_id):
    tenant = current_tenant()
    customer = customers.get_customer(tenant.business_id, customer_id)
    if customer.status == "anonymized":
        raise Conflict("Anonymized customers cannot be edited")
    f = Fields(body())
    f.string("display_name", required=False, max_len=120)
    if f.present("email"):
        f.email("email", required=False)
    if f.present("phone"):
        f.phone("phone")
    f.choice("status", ("active", "inactive"), required=False)
    data = f.check()
    if f.present("email") and data.get("email") != customer.email_normalized:
        if data.get("email") and customers.find_by_email(tenant.business_id, data["email"]):
            raise Conflict("Another customer already uses this email", code="duplicate_customer")
        customer.email = customer.email_normalized = data.get("email")
    if f.present("phone"):
        customer.phone = data.get("phone")
    if data.get("display_name"):
        customer.display_name = data["display_name"]
    if data.get("status"):
        customer.status = data["status"]
    audit.record("customer.updated", business_id=tenant.business_id, target_type="customer", target_id=customer.id)
    db.session.commit()
    return jsonify({"data": customer.to_dict(detail=True)})


@bp.post("/customers/<int:customer_id>/consent")
@require("customers.create", billing_exempt=True)
def set_consent(customer_id):
    tenant = current_tenant()
    customer = customers.get_customer(tenant.business_id, customer_id)
    f = Fields(body())
    granted = f.boolean("marketing_opt_in", required=True)
    f.check()
    customers.set_marketing_consent(customer, granted, source="staff", actor_id=g.user.id)
    db.session.commit()
    return jsonify({"data": customer.to_dict(detail=True)})


@bp.get("/customers/<int:customer_id>/ledger")
@require("customers.view")
def customer_ledger(customer_id):
    tenant = current_tenant()
    customer = customers.get_customer(tenant.business_id, customer_id)
    query = PointLedgerEntry.query.filter_by(business_id=tenant.business_id, customer_id=customer.id).order_by(
        PointLedgerEntry.created_at.desc(), PointLedgerEntry.id.desc()
    )
    reversed_ids = {
        rid
        for (rid,) in db.session.query(PointLedgerEntry.reverses_entry_id).filter(
            PointLedgerEntry.customer_id == customer.id, PointLedgerEntry.reverses_entry_id.isnot(None)
        )
    }
    return jsonify(paginate(query, lambda e: dict(e.to_dict(), reversed=e.id in reversed_ids)))


@bp.post("/customers/<int:customer_id>/adjustments")
@require("ledger.adjust")
def adjust_points(customer_id):
    tenant = current_tenant()
    customer = customers.get_customer(tenant.business_id, customer_id)
    f = Fields(body())
    f.integer("points", min_value=-1_000_000, max_value=1_000_000)
    f.string("reason", max_len=255, min_len=3)
    f.integer("location_id", required=False)
    data = f.check()
    if data["points"] == 0:
        raise ValidationError("Points must not be zero", fields={"points": "Must not be zero"})
    location = tenant.require_location(data.get("location_id"), required=False)
    entry = ledger.adjust(
        tenant, customer, data["points"], data["reason"], g.user.id, location.id if location else None
    )
    db.session.commit()
    return jsonify({"data": entry.to_dict()}), 201


@bp.get("/customers/<int:customer_id>/reconcile")
@require("ledger.adjust")
def reconcile_customer(customer_id):
    tenant = current_tenant()
    customer = customers.get_customer(tenant.business_id, customer_id)
    mismatches = ledger.reconcile(tenant.business_id, customer.id)
    return jsonify(
        {"data": {"consistent": not mismatches, "mismatches": mismatches, "balance": customer.points_balance}}
    )


@bp.get("/customers/<int:customer_id>/privacy-export")
@require("customers.privacy")
def privacy_export(customer_id):
    tenant = current_tenant()
    customer = customers.get_customer(tenant.business_id, customer_id)
    audit.record(
        "customer.data_exported", business_id=tenant.business_id, target_type="customer", target_id=customer.id
    )
    db.session.commit()
    return jsonify({"data": customers.privacy_export(customer)})


@bp.post("/customers/<int:customer_id>/anonymize")
@require("customers.privacy", billing_exempt=True)
def anonymize_customer(customer_id):
    tenant = current_tenant()
    customer = customers.get_customer(tenant.business_id, customer_id)
    f = Fields(body())
    f.string("confirm", max_len=20)
    data = f.check()
    if data["confirm"] != "DELETE":
        raise ValidationError("Type DELETE to confirm", fields={"confirm": "Type DELETE to confirm"})
    customers.anonymize(tenant, customer, g.user.id)
    db.session.commit()
    return jsonify({"data": customer.to_dict(detail=True)})


@bp.post("/customers/<int:customer_id>/portal-link")
@require("customers.view")
@limiter.limit("10 per hour")
def send_portal_link(customer_id):
    tenant = current_tenant()
    customer = customers.get_customer(tenant.business_id, customer_id)
    if customer.status != "active" or not customer.email:
        raise Conflict("The customer needs an active record with an email address to receive a link")
    issue_portal_link(customer, tenant.business.name)
    db.session.commit()
    return jsonify({"data": {"sent": True}})


def issue_portal_link(customer, business_name: str):
    token = new_token()
    db.session.add(
        CustomerAccessToken(
            business_id=customer.business_id,
            customer_id=customer.id,
            token_hash=hash_token(token),
            expires_at=utcnow() + current_app.config["PORTAL_LINK_TTL"],
        )
    )
    queue_email(
        "portal_link",
        customer.email,
        f"Your {business_name} rewards",
        f"View your points, rewards and referral link (link expires in 24 hours, single use):\n"
        f"{link('/portal/access?token=' + token)}\n",
        business_id=customer.business_id,
    )


# ------------------------------------------------------------------- ledger


@bp.get("/ledger")
@require("analytics.view")
def list_ledger():
    tenant = current_tenant()
    query = PointLedgerEntry.query.filter_by(business_id=tenant.business_id)
    allowed = tenant.allowed_location_ids()
    if allowed is not None:
        query = query.filter(PointLedgerEntry.location_id.in_(allowed or [0]))
    entry_type = request.args.get("type")
    if entry_type:
        query = query.filter(PointLedgerEntry.entry_type == entry_type)
    location_id = request.args.get("location_id", type=int)
    if location_id:
        query = query.filter(PointLedgerEntry.location_id == location_id)
    return jsonify(
        paginate(query.order_by(PointLedgerEntry.created_at.desc(), PointLedgerEntry.id.desc()), lambda e: e.to_dict())
    )


@bp.post("/ledger/<int:entry_id>/reverse")
@require("ledger.reverse")
def reverse_entry(entry_id):
    tenant = current_tenant()
    entry = ledger.get_entry(tenant.business_id, entry_id)
    f = Fields(body())
    f.string("reason", max_len=255, min_len=3)
    data = f.check()
    reversal = ledger.reverse(tenant, entry, data["reason"], g.user.id)
    db.session.commit()
    return jsonify({"data": reversal.to_dict()}), 201


# ---------------------------------------------------------------- purchases


@bp.post("/purchases")
@require("purchases.create")
@limiter.limit("120 per minute")
def record_purchase():
    tenant = current_tenant()
    key = idempotency_key()
    f = Fields(body())
    f.integer("customer_id")
    f.integer("location_id")
    f.money("amount")
    f.money("eligible_amount", required=False, allow_zero=True)
    f.string("external_ref", required=False, max_len=64)
    data = f.check()
    customer = customers.get_customer(tenant.business_id, data["customer_id"])
    location = tenant.require_location(data["location_id"])
    try:
        purchase, duplicate = purchases.record_purchase(
            tenant,
            customer,
            data["amount"],
            data.get("eligible_amount"),
            location.id,
            data.get("external_ref"),
            key,
            g.user.id,
        )
        db.session.commit()
    except ApiError:
        db.session.rollback()
        raise
    program = LoyaltyProgram.query.filter_by(business_id=tenant.business_id).one()
    message = (
        f"Awarded {purchase.points_awarded} points."
        if purchase.points_awarded
        else (
            "No points: earning is turned off."
            if not program.earning_enabled or program.status != "active"
            else "No points: purchase is below the minimum spend."
        )
    )
    return (
        jsonify(
            {
                "data": {
                    "purchase": purchase.to_dict(),
                    "duplicate": duplicate,
                    "message": "This purchase was already recorded; points were not awarded twice."
                    if duplicate
                    else message,
                    "customer": customer.to_dict(),
                }
            }
        ),
        200 if duplicate else 201,
    )
