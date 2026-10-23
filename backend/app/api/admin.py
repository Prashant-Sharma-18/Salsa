"""Platform administration (the SaaS operator, not merchants).

Admins see business-level metadata only (plan, usage, owner contact) and never
customer records or ledgers. Every action is audit-logged against the
business with the admin as actor. In production admins must use two-factor.
"""

from datetime import timedelta
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import func, or_

from .. import billing
from ..errors import ApiError, Conflict, Forbidden, NotFound
from ..extensions import db
from ..models import AuditLog, Business, BusinessMembership, Customer, PointLedgerEntry, User, utcnow
from ..security import login_required
from ..services import audit
from ..validation import Fields, body, pagination_args

bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not g.user.is_platform_admin:
            raise Forbidden()
        if current_app.config["ADMIN_REQUIRE_MFA"] and not g.user.mfa_enabled:
            raise ApiError(
                "Platform administrators must turn on two-factor authentication.", code="admin_mfa_required", status=403
            )
        return fn(*args, **kwargs)

    return wrapper


def _get_business(business_id: int) -> Business:
    business = db.session.get(Business, business_id)
    if not business:
        raise NotFound("Business not found")
    return business


def _owners(business_id: int) -> list[dict]:
    rows = (
        BusinessMembership.query.filter_by(business_id=business_id, role="owner")
        .join(User)
        .order_by(BusinessMembership.id)
        .all()
    )
    return [{"name": m.user.display_name, "email": m.user.email, "status": m.status} for m in rows]


def _row(business: Business) -> dict:
    return {
        **business.to_dict(),
        "billing": billing.summary(business),
        "suspended": business.suspended_at is not None,
        "suspended_reason": business.suspended_reason,
        "members": BusinessMembership.query.filter_by(business_id=business.id, status="active").count(),
        "customers": db.session.scalar(
            db.select(func.count(Customer.id)).where(
                Customer.business_id == business.id, Customer.status != "anonymized"
            )
        ),
        "owner_email": (_owners(business.id) or [{}])[0].get("email"),
    }


@bp.get("/overview")
@admin_required
def overview():
    businesses = Business.query.filter(Business.is_demo.is_(False)).all()
    by_status: dict[str, int] = {}
    mrr = 0
    for b in businesses:
        state = "suspended" if b.suspended_at else billing.standing(b)
        by_status[state] = by_status.get(state, 0) + 1
        if not b.suspended_at and state in ("active", "past_due") and b.plan in billing.PLANS:
            mrr += billing.PLANS[b.plan]["price_cents"]
    since = utcnow() - timedelta(days=30)
    active_businesses = db.session.scalar(
        db.select(func.count(func.distinct(PointLedgerEntry.business_id))).where(PointLedgerEntry.created_at >= since)
    )
    return jsonify(
        {
            "data": {
                "businesses": len(businesses),
                "by_status": by_status,
                "active_last_30_days": int(active_businesses or 0),
                "users": User.query.filter(User.is_demo.is_(False)).count(),
                "customers": db.session.scalar(
                    db.select(func.count(Customer.id))
                    .join(Business, Business.id == Customer.business_id)
                    .where(Business.is_demo.is_(False), Customer.status != "anonymized")
                ),
                "mrr_cents": mrr,
            }
        }
    )


@bp.get("/businesses")
@admin_required
def list_businesses():
    query = Business.query
    q = (request.args.get("q") or "").strip()
    if q:
        owner_ids = db.select(BusinessMembership.business_id).join(User).where(User.email.ilike(f"%{q}%"))
        query = query.filter(
            or_(Business.name.ilike(f"%{q}%"), Business.slug.ilike(f"%{q}%"), Business.id.in_(owner_ids))
        )
    status = request.args.get("status")
    rows = [b for b in query.order_by(Business.created_at.desc()).all()]
    if status == "suspended":
        rows = [b for b in rows if b.suspended_at]
    elif status:
        rows = [b for b in rows if not b.suspended_at and billing.standing(b) == status]
    page, size = pagination_args()
    total = len(rows)
    page_rows = rows[(page - 1) * size : page * size]
    return jsonify(
        {
            "data": [_row(b) for b in page_rows],
            "meta": {"page": page, "page_size": size, "total": total, "pages": max(1, -(-total // size))},
        }
    )


@bp.get("/businesses/<int:business_id>")
@admin_required
def get_business(business_id):
    business = _get_business(business_id)
    history = (
        AuditLog.query.filter(
            AuditLog.business_id == business.id,
            or_(AuditLog.action.like("admin.%"), AuditLog.action.like("billing.%")),
        )
        .order_by(AuditLog.id.desc())
        .limit(20)
    )
    return jsonify(
        {
            "data": {
                **_row(business),
                "owners": _owners(business.id),
                "limits": billing.limits(business),
                "usage": billing.usage(business),
                "history": [a.to_dict() for a in history],
            }
        }
    )


@bp.post("/businesses/<int:business_id>/suspend")
@admin_required
def suspend(business_id):
    business = _get_business(business_id)
    f = Fields(body())
    reason = f.string("reason", max_len=255, min_len=5)
    f.check()
    if business.suspended_at:
        raise Conflict("Business is already suspended")
    business.suspended_at = utcnow()
    business.suspended_reason = reason
    audit.record(
        "admin.business_suspended",
        business_id=business.id,
        target_type="business",
        target_id=business.id,
        reason=reason,
    )
    db.session.commit()
    return jsonify({"data": _row(business)})


@bp.post("/businesses/<int:business_id>/unsuspend")
@admin_required
def unsuspend(business_id):
    business = _get_business(business_id)
    f = Fields(body())
    reason = f.string("reason", max_len=255, min_len=5)
    f.check()
    if not business.suspended_at:
        raise Conflict("Business is not suspended")
    business.suspended_at = None
    business.suspended_reason = None
    audit.record(
        "admin.business_unsuspended",
        business_id=business.id,
        target_type="business",
        target_id=business.id,
        reason=reason,
    )
    db.session.commit()
    return jsonify({"data": _row(business)})


@bp.post("/businesses/<int:business_id>/plan")
@admin_required
def change_plan(business_id):
    """Manual plan changes for support (e.g. invoiced customers) and trial extensions."""
    business = _get_business(business_id)
    f = Fields(body())
    plan = f.choice("plan", ("trial", *billing.PLANS), required=False)
    status = f.choice("status", ("active", "past_due", "canceled"), required=False, default="active")
    extend = f.integer("extend_trial_days", required=False, min_value=1, max_value=90)
    reason = f.string("reason", max_len=255, min_len=5)
    f.check()
    if extend:
        start = max(business.trial_ends_at or utcnow(), utcnow())
        business.plan = "trial"
        business.plan_status = "trialing"
        business.trial_ends_at = start + timedelta(days=extend)
        audit.record(
            "admin.trial_extended",
            business_id=business.id,
            target_type="business",
            target_id=business.id,
            days=extend,
            reason=reason,
        )
    elif plan == "trial":
        raise ApiError("Use extend_trial_days to put a business on trial", code="validation_error", status=422)
    elif plan:
        billing.apply_plan(business, plan, status, source="admin")
        audit.record(
            "admin.plan_changed",
            business_id=business.id,
            target_type="business",
            target_id=business.id,
            plan=plan,
            status=status,
            reason=reason,
        )
    else:
        raise ApiError("Choose a plan or a trial extension", code="validation_error", status=422)
    db.session.commit()
    return jsonify({"data": _row(business)})
