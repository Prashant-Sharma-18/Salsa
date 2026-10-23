"""Subscription plans, usage limits and the billing provider boundary.

Plans and limits live in ``PLANS``. Prices are placeholders: change them here
and create matching Stripe prices (``STRIPE_PRICE_<PLAN>``).

Standing:
- ``trialing``: new businesses get ``TRIAL_DAYS`` with Growth limits.
- ``active`` / ``past_due``: full access (past_due shows a warning while Stripe retries).
- ``trial_expired`` / ``canceled``: read-only. Writes return HTTP 402, except
  billing, account, privacy and team-cleanup actions.
Demo businesses are always active.

Providers (``BILLING_PROVIDER``):
- ``dev``: owners can switch plans without payment. Refused in production.
- ``stripe``: Checkout + Customer Portal + signed webhooks.
- ``none``: no self-serve upgrades (plans changed by a platform admin).
"""

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from flask import current_app

from .errors import ApiError
from .extensions import db
from .models import BillingEvent, Business, BusinessInvitation, BusinessMembership, Customer, Location, utcnow
from .services import audit

TRIAL_DAYS = 14
TRIAL_LIMITS_PLAN = "growth"

PLANS: dict[str, dict] = {
    "starter": {
        "name": "Starter",
        "price_cents": 2900,
        "description": "One location getting started with loyalty.",
        "limits": {"locations": 1, "customers": 500, "members": 3},
    },
    "growth": {
        "name": "Growth",
        "price_cents": 7900,
        "description": "Growing businesses with a few locations.",
        "limits": {"locations": 3, "customers": 5000, "members": 10},
    },
    "pro": {
        "name": "Pro",
        "price_cents": 19900,
        "description": "Multi-location chains.",
        "limits": {"locations": None, "customers": None, "members": None},
    },
}

GOOD_STANDING = {"trialing", "active", "past_due"}
LIMIT_LABELS = {"locations": "active locations", "customers": "customers", "members": "team members"}


class PaymentRequired(ApiError):
    status = 402


# ------------------------------------------------------------------ standing


def standing(business: Business) -> str:
    if business.is_demo:
        return "active"
    if business.plan == "trial":
        return "trialing" if business.trial_ends_at and business.trial_ends_at > utcnow() else "trial_expired"
    return business.plan_status or "active"


def in_good_standing(business: Business) -> bool:
    return standing(business) in GOOD_STANDING


def limits(business: Business) -> dict:
    if business.is_demo:
        return PLANS["pro"]["limits"]
    plan = TRIAL_LIMITS_PLAN if business.plan == "trial" else business.plan
    return PLANS.get(plan, PLANS["starter"])["limits"]


def usage(business: Business) -> dict:
    members = BusinessMembership.query.filter_by(business_id=business.id, status="active").count()
    pending = BusinessInvitation.query.filter(
        BusinessInvitation.business_id == business.id,
        BusinessInvitation.accepted_at.is_(None),
        BusinessInvitation.revoked_at.is_(None),
        BusinessInvitation.expires_at > utcnow(),
    ).count()
    return {
        "locations": Location.query.filter_by(business_id=business.id, status="active").count(),
        "customers": Customer.query.filter(
            Customer.business_id == business.id, Customer.status != "anonymized"
        ).count(),
        "members": members + pending,
    }


def require_good_standing(business: Business) -> None:
    state = standing(business)
    if state in GOOD_STANDING:
        return
    message = (
        "Your free trial has ended. Choose a plan in Billing to keep recording activity."
        if state == "trial_expired"
        else "Your subscription is not active. Update billing to keep recording activity."
    )
    raise PaymentRequired(message, code="subscription_inactive")


def check_limit(business: Business, resource: str, adding: int = 1) -> None:
    """Raise 402 if adding ``adding`` more of ``resource`` would exceed the plan limit."""
    limit = limits(business)[resource]
    if limit is None:
        return
    current = usage(business)[resource]
    if current + adding > limit:
        raise PaymentRequired(
            f"Your plan allows {limit} {LIMIT_LABELS[resource]}. Upgrade in Billing to add more.",
            code="plan_limit_reached",
        )


def start_trial(business: Business) -> None:
    business.plan = "trial"
    business.plan_status = "trialing"
    business.trial_ends_at = utcnow() + timedelta(days=TRIAL_DAYS)


def summary(business: Business) -> dict:
    state = standing(business)
    return {
        "plan": business.plan,
        "plan_name": "Free trial"
        if business.plan == "trial"
        else PLANS.get(business.plan, {}).get("name", business.plan),
        "status": state,
        "in_good_standing": state in GOOD_STANDING,
        "trial_ends_at": business.trial_ends_at.isoformat() + "Z" if business.trial_ends_at else None,
        "current_period_end": business.current_period_end.isoformat() + "Z" if business.current_period_end else None,
    }


def apply_plan(
    business: Business, plan: str, status: str = "active", period_end: datetime | None = None, source=""
) -> None:
    if plan not in PLANS:
        raise ApiError("Unknown plan", code="unknown_plan", status=422)
    old = (business.plan, business.plan_status)
    business.plan = plan
    business.plan_status = status
    if period_end:
        business.current_period_end = period_end
    if old != (plan, status):
        audit.record(
            "billing.plan_changed",
            business_id=business.id,
            target_type="business",
            target_id=business.id,
            plan=plan,
            status=status,
            source=source,
        )


# ------------------------------------------------------------------ providers


def provider() -> str:
    return current_app.config["BILLING_PROVIDER"]


def _stripe_price(plan: str) -> str:
    price = current_app.config["STRIPE_PRICES"].get(plan)
    if not price:
        raise ApiError(f"No Stripe price configured for {plan}", code="billing_not_configured", status=503)
    return price


def _flatten(params: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Encode nested dicts/lists the way Stripe's form API expects (a[b][0][c]=...)."""
    items: list[tuple[str, str]] = []
    for key, value in params.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict):
            items.extend(_flatten(value, name))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                items.extend(_flatten(v, f"{name}[{i}]") if isinstance(v, dict) else [(f"{name}[{i}]", str(v))])
        elif value is not None:
            items.append((name, str(value).lower() if isinstance(value, bool) else str(value)))
    return items


def stripe_request(path: str, params: dict) -> dict:
    data = urllib.parse.urlencode(_flatten(params)).encode()
    req = urllib.request.Request(
        "https://api.stripe.com/v1/" + path.lstrip("/"),
        data=data,
        method="POST",
        headers={
            "Authorization": "Bearer " + current_app.config["STRIPE_SECRET_KEY"],
            "Content-Type": "application/x-www-form-urlencoded",
            "Stripe-Version": current_app.config["STRIPE_API_VERSION"],
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read()).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            pass
        current_app.logger.warning("Stripe API error status=%s path=%s message=%s", exc.code, path, detail)
        raise ApiError("The payment provider rejected the request. Please try again.", code="billing_error", status=502)
    except urllib.error.URLError:
        raise ApiError(
            "Could not reach the payment provider. Please try again.", code="billing_unavailable", status=503
        )


def create_checkout(business: Business, plan: str, owner_email: str) -> str:
    if plan not in PLANS:
        raise ApiError("Unknown plan", code="unknown_plan", status=422)
    base = current_app.config["PUBLIC_BASE_URL"].rstrip("/")
    params = {
        "mode": "subscription",
        "line_items": [{"price": _stripe_price(plan), "quantity": 1}],
        "success_url": f"{base}/settings/billing?checkout=success",
        "cancel_url": f"{base}/settings/billing?checkout=cancelled",
        "client_reference_id": str(business.id),
        "metadata": {"business_id": business.id, "plan": plan},
        "subscription_data": {"metadata": {"business_id": business.id, "plan": plan}},
    }
    if business.stripe_customer_id:
        params["customer"] = business.stripe_customer_id
    else:
        params["customer_email"] = owner_email
    return stripe_request("checkout/sessions", params)["url"]


def create_portal(business: Business) -> str:
    if not business.stripe_customer_id:
        raise ApiError("No billing account yet. Choose a plan first.", code="no_billing_account", status=409)
    base = current_app.config["PUBLIC_BASE_URL"].rstrip("/")
    session = stripe_request(
        "billing_portal/sessions", {"customer": business.stripe_customer_id, "return_url": f"{base}/settings/billing"}
    )
    return session["url"]


# ------------------------------------------------------------------- webhooks

WEBHOOK_TOLERANCE_SECONDS = 300
STRIPE_STATUS = {
    "active": "active",
    "trialing": "active",
    "past_due": "past_due",
    "unpaid": "past_due",
    "incomplete": "past_due",
    "canceled": "canceled",
    "incomplete_expired": "canceled",
    "paused": "canceled",
}


def verify_stripe_signature(payload: bytes, header: str, secret: str, now: float | None = None) -> bool:
    try:
        parts = dict(item.split("=", 1) for item in header.split(",") if "=" in item)
        timestamp = int(parts["t"])
    except (KeyError, ValueError):
        return False
    if abs((now or time.time()) - timestamp) > WEBHOOK_TOLERANCE_SECONDS:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    signatures = [v for k, v in (item.split("=", 1) for item in header.split(",") if "=" in item) if k == "v1"]
    return any(hmac.compare_digest(expected, sig) for sig in signatures)


def _plan_for_price(price_id: str | None) -> str | None:
    for plan, pid in current_app.config["STRIPE_PRICES"].items():
        if pid and pid == price_id:
            return plan
    return None


def _business_for(obj: dict) -> Business | None:
    meta = obj.get("metadata") or {}
    business_id = meta.get("business_id") or obj.get("client_reference_id")
    if business_id and str(business_id).isdigit():
        business = db.session.get(Business, int(business_id))
        if business:
            return business
    if obj.get("object") == "subscription" and obj.get("id"):
        return Business.query.filter_by(stripe_subscription_id=obj["id"]).first()
    if obj.get("subscription"):
        return Business.query.filter_by(stripe_subscription_id=obj["subscription"]).first()
    if obj.get("customer"):
        return Business.query.filter_by(stripe_customer_id=obj["customer"]).first()
    return None


def _period_end(sub: dict) -> datetime | None:
    ts = sub.get("current_period_end")
    if ts is None:
        items = (sub.get("items") or {}).get("data") or []
        ts = items[0].get("current_period_end") if items else None
    return datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None) if ts else None


def handle_stripe_event(event: dict) -> str:
    """Apply a verified Stripe event. Idempotent per event id. Returns a short outcome string."""
    event_id = event.get("id")
    if not event_id:
        return "ignored"
    if BillingEvent.query.filter_by(event_id=event_id).first():
        return "duplicate"
    kind = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    business = _business_for(obj)
    outcome = "ignored"
    if business:
        if kind == "checkout.session.completed":
            business.stripe_customer_id = obj.get("customer") or business.stripe_customer_id
            business.stripe_subscription_id = obj.get("subscription") or business.stripe_subscription_id
            plan = (obj.get("metadata") or {}).get("plan")
            if plan in PLANS:
                apply_plan(business, plan, "active", source="stripe")
            outcome = "checkout_completed"
        elif kind in (
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        ):
            business.stripe_subscription_id = obj.get("id") or business.stripe_subscription_id
            business.stripe_customer_id = obj.get("customer") or business.stripe_customer_id
            items = (obj.get("items") or {}).get("data") or []
            price_id = (items[0].get("price") or {}).get("id") if items else None
            plan = _plan_for_price(price_id) or (obj.get("metadata") or {}).get("plan") or business.plan
            status = "canceled" if kind.endswith("deleted") else STRIPE_STATUS.get(obj.get("status"), "past_due")
            if plan in PLANS:
                apply_plan(business, plan, status, period_end=_period_end(obj), source="stripe")
            outcome = "subscription_" + status
        elif kind == "invoice.payment_failed" and business.plan in PLANS:
            apply_plan(business, business.plan, "past_due", source="stripe")
            outcome = "payment_failed"
    db.session.add(BillingEvent(event_id=event_id, event_type=kind[:64], business_id=business.id if business else None))
    return outcome
