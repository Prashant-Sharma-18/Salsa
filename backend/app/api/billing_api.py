import json

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.exceptions import NotFound as HTTPNotFound

from .. import billing
from ..errors import ApiError
from ..extensions import db, limiter
from ..models import utcnow
from ..security import current_tenant, require
from ..validation import Fields, body

bp = Blueprint("billing", __name__)


def _overview(business) -> dict:
    return {
        **billing.summary(business),
        "provider": billing.provider(),
        "has_billing_account": bool(business.stripe_customer_id),
        "limits": billing.limits(business),
        "usage": billing.usage(business),
        "trial_days": billing.TRIAL_DAYS,
        "plans": [
            {
                "id": key,
                "name": p["name"],
                "price_cents": p["price_cents"],
                "description": p["description"],
                "limits": p["limits"],
            }
            for key, p in billing.PLANS.items()
        ],
    }


@bp.get("/billing")
@require("billing.manage")
def overview():
    return jsonify({"data": _overview(current_tenant().business)})


@bp.post("/billing/checkout")
@require("billing.manage", billing_exempt=True)
@limiter.limit("10 per hour")
def checkout():
    if billing.provider() != "stripe":
        raise ApiError("Online checkout is not enabled", code="billing_not_configured", status=409)
    f = Fields(body())
    plan = f.choice("plan", tuple(billing.PLANS))
    f.check()
    tenant = current_tenant()
    return jsonify({"data": {"url": billing.create_checkout(tenant.business, plan, g.user.email)}})


@bp.post("/billing/portal")
@require("billing.manage", billing_exempt=True)
@limiter.limit("20 per hour")
def portal():
    if billing.provider() != "stripe":
        raise ApiError("Online billing is not enabled", code="billing_not_configured", status=409)
    return jsonify({"data": {"url": billing.create_portal(current_tenant().business)}})


@bp.post("/billing/dev/switch")
@require("billing.manage", billing_exempt=True)
def dev_switch():
    """Simulated plan change for local development. Never available in production."""
    if billing.provider() != "dev" or current_app.config["APP_ENV"] == "production":
        raise HTTPNotFound()
    f = Fields(body())
    plan = f.choice("plan", tuple(billing.PLANS))
    status = f.choice("status", ("active", "past_due", "canceled"), required=False, default="active")
    f.check()
    tenant = current_tenant()
    from datetime import timedelta

    billing.apply_plan(tenant.business, plan, status, period_end=utcnow() + timedelta(days=30), source="dev")
    db.session.commit()
    return jsonify({"data": _overview(tenant.business)})


@bp.post("/billing/stripe/webhook")
@limiter.exempt
def stripe_webhook():
    if billing.provider() != "stripe":
        raise HTTPNotFound()
    payload = request.get_data()
    signature = request.headers.get("Stripe-Signature", "")
    if not billing.verify_stripe_signature(payload, signature, current_app.config["STRIPE_WEBHOOK_SECRET"]):
        raise ApiError("Invalid signature", code="invalid_signature", status=400)
    try:
        event = json.loads(payload)
    except ValueError:
        raise ApiError("Invalid payload", code="invalid_payload", status=400)
    outcome = billing.handle_stripe_event(event)
    db.session.commit()
    return jsonify({"received": True, "outcome": outcome})
