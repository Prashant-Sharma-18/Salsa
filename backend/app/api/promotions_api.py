from flask import Blueprint, jsonify, request

from ..errors import NotFound, ValidationError
from ..extensions import db
from ..models import Location, Promotion
from ..security import current_tenant, require
from ..services import audit, promotions
from ..validation import Fields, body

bp = Blueprint("promotions", __name__)


def _get(business_id: int, promo_id: int) -> Promotion:
    promo = Promotion.query.filter_by(id=promo_id, business_id=business_id).first()
    if not promo:
        raise NotFound("Promotion not found")
    return promo


def _fields(partial: bool, existing: Promotion | None = None) -> dict:
    tenant = current_tenant()
    f = Fields(body())
    f.string("name", required=not partial, max_len=120)
    f.string("description", required=False, max_len=500, default="")
    f.choice("promo_type", ("multiplier", "bonus"), required=not partial)
    f.integer("multiplier_percent", required=False, min_value=101, max_value=1000)
    f.integer("bonus_points", required=False, min_value=1, max_value=100_000)
    f.date("starts_on", required=not partial)
    f.date("ends_on", required=False)
    days = f.int_list("days_of_week") if f.present("days_of_week") else None
    locs = f.int_list("location_ids") if f.present("location_ids") else None
    f.money("min_spend", required=False, allow_zero=True)
    f.choice("status", ("active", "archived"), required=False)
    data = f.check()
    if partial:
        data = {k: v for k, v in data.items() if f.present(k)}

    promo_type = data.get("promo_type") or (existing.promo_type if existing else None)
    multiplier = data.get("multiplier_percent", existing.multiplier_percent if existing else None)
    bonus = data.get("bonus_points", existing.bonus_points if existing else None)
    errors = {}
    if promo_type == "multiplier" and not multiplier:
        errors["multiplier_percent"] = "Choose a multiplier, e.g. 200 for double points"
    if promo_type == "bonus" and not bonus:
        errors["bonus_points"] = "Enter the bonus points"
    starts = data.get("starts_on") or (existing.starts_on if existing else None)
    ends = data["ends_on"] if "ends_on" in data else (existing.ends_on if existing else None)
    if starts and ends and ends < starts:
        errors["ends_on"] = "End date must be on or after the start date"
    if days is not None and any(d < 0 or d > 6 for d in days):
        errors["days_of_week"] = "Use 0 (Monday) to 6 (Sunday)"
    if locs:
        valid = {
            loc.id for loc in Location.query.filter(Location.business_id == tenant.business_id, Location.id.in_(locs))
        }
        if set(locs) - valid:
            errors["location_ids"] = "Contains an unknown location"
    if errors:
        raise ValidationError("Please correct the highlighted fields", fields=errors)
    # Keep only the value that matches the type.
    if promo_type == "multiplier":
        data["bonus_points"] = None
    elif promo_type == "bonus":
        data["multiplier_percent"] = None
    return data


def _apply(promo: Promotion, data: dict) -> None:
    for key, value in data.items():
        if key == "min_spend":
            promo.min_spend_cents = value or 0
        elif key == "description":
            promo.description = value or ""
        else:
            setattr(promo, key, value)


@bp.get("/promotions")
@require("promotions.view")
def list_promotions():
    tenant = current_tenant()
    query = Promotion.query.filter_by(business_id=tenant.business_id)
    status = request.args.get("status")
    if status:
        query = query.filter_by(status=status)
    return jsonify({"data": [p.to_dict() for p in query.order_by(Promotion.starts_on.desc(), Promotion.id.desc())]})


@bp.get("/promotions/active")
@require("promotions.view")
def active_promotions():
    """Promotions running today at a location (for the checkout preview). Min spend is checked by the client."""
    tenant = current_tenant()
    location_id = request.args.get("location_id", type=int)
    today = promotions.local_today(tenant.business)
    promos = promotions.applicable(tenant.business, location_id, 10**9, today)
    return jsonify({"data": [p.to_dict() for p in promos], "meta": {"date": today.isoformat()}})


@bp.post("/promotions")
@require("promotions.manage")
def create_promotion():
    tenant = current_tenant()
    data = _fields(partial=False)
    promo = Promotion(business_id=tenant.business_id, days_of_week=[], location_ids=[])
    _apply(promo, data)
    db.session.add(promo)
    db.session.flush()
    audit.record("promotion.created", business_id=tenant.business_id, target_type="promotion", target_id=promo.id)
    db.session.commit()
    return jsonify({"data": promo.to_dict()}), 201


@bp.patch("/promotions/<int:promo_id>")
@require("promotions.manage")
def update_promotion(promo_id):
    tenant = current_tenant()
    promo = _get(tenant.business_id, promo_id)
    _apply(promo, _fields(partial=True, existing=promo))
    audit.record("promotion.updated", business_id=tenant.business_id, target_type="promotion", target_id=promo.id)
    db.session.commit()
    return jsonify({"data": promo.to_dict()})
