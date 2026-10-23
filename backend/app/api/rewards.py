from flask import Blueprint, g, jsonify, request

from ..errors import Conflict, Forbidden, NotFound, ValidationError
from ..extensions import db, limiter
from ..models import REWARD_TYPES, Redemption, Reward
from ..security import current_tenant, require
from ..services import audit, customers, redemptions, referrals
from ..validation import Fields, body, paginate
from .customers import idempotency_key

bp = Blueprint("rewards", __name__)


def _get_reward(business_id: int, reward_id: int) -> Reward:
    reward = Reward.query.filter_by(id=reward_id, business_id=business_id).first()
    if not reward:
        raise NotFound("Reward not found")
    return reward


def _reward_fields(partial: bool) -> dict:
    f = Fields(body())
    f.string("name", required=not partial, max_len=120)
    f.string("description", required=False, max_len=2000)
    f.choice("reward_type", REWARD_TYPES, required=not partial)
    f.money("value", required=False)
    f.integer("points_cost", required=not partial, min_value=1, max_value=1_000_000)
    f.choice("status", ("active", "archived"), required=False)
    if f.present("stock_limit"):
        f.integer("stock_limit", required=False, min_value=0, max_value=1_000_000)
    f.string("terms", required=False, max_len=2000)
    data = f.check()
    if partial:
        data = {k: v for k, v in data.items() if f.present(k)}
    if data.get("reward_type") == "fixed_discount" and not data.get("value") and not partial:
        raise ValidationError("Enter the discount value", fields={"value": "Required for fixed discounts"})
    return data


def _apply(reward: Reward, data: dict):
    for key, value in data.items():
        if key == "value":
            reward.value_cents = value
        elif key in ("description", "terms"):
            setattr(reward, key, value or "")
        elif key == "stock_limit":
            if value is not None and value < (reward.stock_redeemed or 0):
                raise ValidationError(
                    f"{reward.stock_redeemed} have already been issued; the limit cannot be lower",
                    fields={"stock_limit": "Too low"},
                )
            reward.stock_limit = value
        elif value is not None:
            setattr(reward, key, value)


@bp.get("/rewards")
@require("rewards.view")
def list_rewards():
    tenant = current_tenant()
    query = Reward.query.filter_by(business_id=tenant.business_id)
    status = request.args.get("status")
    if status:
        query = query.filter_by(status=status)
    return jsonify({"data": [r.to_dict() for r in query.order_by(Reward.points_cost)]})


@bp.post("/rewards")
@require("rewards.manage")
def create_reward():
    tenant = current_tenant()
    data = _reward_fields(partial=False)
    reward = Reward(business_id=tenant.business_id)
    _apply(reward, data)
    db.session.add(reward)
    db.session.flush()
    audit.record("reward.created", business_id=tenant.business_id, target_type="reward", target_id=reward.id)
    db.session.commit()
    return jsonify({"data": reward.to_dict()}), 201


@bp.patch("/rewards/<int:reward_id>")
@require("rewards.manage")
def update_reward(reward_id):
    tenant = current_tenant()
    reward = _get_reward(tenant.business_id, reward_id)
    _apply(reward, _reward_fields(partial=True))
    if reward.reward_type == "fixed_discount" and not reward.value_cents:
        raise ValidationError("Enter the discount value", fields={"value": "Required for fixed discounts"})
    audit.record("reward.updated", business_id=tenant.business_id, target_type="reward", target_id=reward.id)
    db.session.commit()
    return jsonify({"data": reward.to_dict()})


@bp.delete("/rewards/<int:reward_id>")
@require("rewards.manage")
def delete_reward(reward_id):
    tenant = current_tenant()
    reward = _get_reward(tenant.business_id, reward_id)
    if Redemption.query.filter_by(reward_id=reward.id).first():
        raise Conflict(
            "This reward has redemptions. Archive it instead so history is preserved.", code="has_redemptions"
        )
    db.session.delete(reward)
    audit.record("reward.deleted", business_id=tenant.business_id, target_type="reward", target_id=reward_id)
    db.session.commit()
    return jsonify({"data": {"deleted": True}})


# ----------------------------------------------------------------- redemptions


@bp.get("/redemptions")
@require("redemptions.issue")
def list_redemptions():
    tenant = current_tenant()
    query = Redemption.query.filter_by(business_id=tenant.business_id)
    status = request.args.get("status")
    if status:
        query = query.filter_by(status=status)
    customer_id = request.args.get("customer_id", type=int)
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    return jsonify(paginate(query.order_by(Redemption.created_at.desc(), Redemption.id.desc()), lambda r: r.to_dict()))


@bp.post("/redemptions")
@require("redemptions.issue")
@limiter.limit("60 per minute")
def issue_redemption():
    tenant = current_tenant()
    key = idempotency_key()
    f = Fields(body())
    f.integer("customer_id")
    f.integer("reward_id")
    f.integer("location_id")
    data = f.check()
    customer = customers.get_customer(tenant.business_id, data["customer_id"])
    reward = _get_reward(tenant.business_id, data["reward_id"])
    location = tenant.require_location(data["location_id"])
    try:
        redemption, duplicate = redemptions.issue(
            tenant.business_id, customer, reward, key, actor_id=g.user.id, location_id=location.id
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return jsonify({"data": dict(redemption.to_dict(), duplicate=duplicate)}), 200 if duplicate else 201


@bp.get("/redemptions/lookup")
@require("redemptions.complete")
@limiter.limit("60 per minute")
def lookup_redemption():
    tenant = current_tenant()
    code = (request.args.get("code") or "").strip()
    if not code or len(code) > 16:
        raise ValidationError("Enter a redemption code", fields={"code": "Required"})
    redemption = redemptions.find_by_code(tenant.business_id, code)
    if redemptions.expire_if_due(redemption, g.user.id):
        db.session.commit()
    return jsonify({"data": redemption.to_dict()})


@bp.post("/redemptions/<int:redemption_id>/complete")
@require("redemptions.complete")
def complete_redemption(redemption_id):
    tenant = current_tenant()
    redemption = Redemption.query.filter_by(id=redemption_id, business_id=tenant.business_id).first()
    if not redemption:
        raise NotFound("Redemption not found")
    f = Fields(body())
    f.integer("location_id")
    data = f.check()
    location = tenant.require_location(data["location_id"])
    redemptions.complete(tenant, redemption, location.id, g.user.id)
    db.session.commit()
    return jsonify({"data": redemption.to_dict()})


@bp.post("/redemptions/<int:redemption_id>/cancel")
@require("redemptions.cancel", billing_exempt=True)
def cancel_redemption(redemption_id):
    tenant = current_tenant()
    redemption = Redemption.query.filter_by(id=redemption_id, business_id=tenant.business_id).first()
    if not redemption:
        raise NotFound("Redemption not found")
    f = Fields(body())
    f.string("reason", max_len=255, min_len=3)
    data = f.check()
    redemptions.cancel(tenant, redemption, data["reason"], g.user.id)
    db.session.commit()
    return jsonify({"data": redemption.to_dict()})


# ------------------------------------------------------------------- referrals


@bp.get("/referrals")
@require("referrals.view")
def list_referrals():
    from ..models import Referral

    tenant = current_tenant()
    query = Referral.query.filter_by(business_id=tenant.business_id)
    status = request.args.get("status")
    if status:
        query = query.filter_by(status=status)
    counts = dict(
        db.session.query(Referral.status, db.func.count(Referral.id))
        .filter(Referral.business_id == tenant.business_id)
        .group_by(Referral.status)
        .all()
    )
    result = paginate(query.order_by(Referral.created_at.desc(), Referral.id.desc()), lambda r: r.to_dict())
    result["meta"]["status_counts"] = counts
    return jsonify(result)


@bp.post("/referrals")
@require("referrals.manage")
@limiter.limit("30 per hour")
def create_referral():
    tenant = current_tenant()
    f = Fields(body())
    f.integer("referrer_customer_id")
    f.email("email")
    data = f.check()
    referrer = customers.get_customer(tenant.business_id, data["referrer_customer_id"])
    from ..models import LoyaltyProgram

    if not LoyaltyProgram.query.filter_by(business_id=tenant.business_id).one().referrals_enabled:
        raise Forbidden("Referrals are turned off in program settings")
    referral = referrals.create_invite(tenant, referrer, data["email"])
    db.session.commit()
    return jsonify({"data": referral.to_dict()}), 201


@bp.post("/referrals/<int:referral_id>/reject")
@require("referrals.manage")
def reject_referral(referral_id):
    tenant = current_tenant()
    referral = referrals.get_referral(tenant.business_id, referral_id)
    f = Fields(body())
    f.string("reason", max_len=255, min_len=3)
    data = f.check()
    referrals.reject(tenant, referral, data["reason"])
    db.session.commit()
    return jsonify({"data": referral.to_dict()})
