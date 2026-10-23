import csv
import io
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, Response, jsonify, request

from ..errors import Forbidden, ValidationError
from ..extensions import db, limiter
from ..models import Customer, Location, PointLedgerEntry
from ..security import current_tenant, require
from ..services import analytics, audit

bp = Blueprint("analytics", __name__)


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def date_range() -> tuple[datetime, datetime, date, date]:
    """Parse start/end (inclusive YYYY-MM-DD in the business timezone) into a UTC [start, end) window."""
    tenant = current_tenant()
    tz = _tz(tenant.business.timezone)
    today = datetime.now(tz).date()
    try:
        end_day = date.fromisoformat(request.args["end"]) if request.args.get("end") else today
        start_day = (
            date.fromisoformat(request.args["start"]) if request.args.get("start") else end_day - timedelta(days=29)
        )
    except ValueError:
        raise ValidationError("Dates must be in YYYY-MM-DD format")
    if start_day > end_day:
        raise ValidationError("Start date must be on or before end date")
    if (end_day - start_day).days > 366:
        raise ValidationError("Choose a range of one year or less")
    utc = ZoneInfo("UTC")
    start = datetime.combine(start_day, time.min, tz).astimezone(utc).replace(tzinfo=None)
    end = datetime.combine(end_day + timedelta(days=1), time.min, tz).astimezone(utc).replace(tzinfo=None)
    return start, end, start_day, end_day


def location_scope() -> list[int] | None:
    """Intersect the requested location filter with the user's location access."""
    tenant = current_tenant()
    allowed = tenant.allowed_location_ids()
    requested = request.args.get("location_id", type=int)
    if requested:
        if not Location.query.filter_by(id=requested, business_id=tenant.business_id).first():
            raise ValidationError("Unknown location")
        if allowed is not None and requested not in allowed:
            raise Forbidden("You do not have access to this location")
        return [requested]
    return allowed


@bp.get("/dashboard")
@require("customers.view")
def dashboard():
    tenant = current_tenant()
    start, end, start_day, end_day = date_range()
    scope = location_scope()
    feed_query = PointLedgerEntry.query.filter_by(business_id=tenant.business_id)
    if scope is not None:
        feed_query = feed_query.filter(PointLedgerEntry.location_id.in_(scope or [0]))
    feed = []
    for entry in feed_query.order_by(PointLedgerEntry.created_at.desc(), PointLedgerEntry.id.desc()).limit(15):
        customer = db.session.get(Customer, entry.customer_id)
        feed.append(dict(entry.to_dict(), customer_name=customer.display_name))
    data = {
        "range": {"start": start_day.isoformat(), "end": end_day.isoformat()},
        "activity": feed,
        "summary": None,
        "totals": None,
    }
    if tenant.can("analytics.view"):
        data["summary"] = analytics.summary(tenant.business_id, start, end, scope)
        data["totals"] = {
            "enrolled_customers": Customer.query.filter(
                Customer.business_id == tenant.business_id, Customer.status != "anonymized"
            ).count()
        }
    return jsonify({"data": data})


@bp.get("/analytics/summary")
@require("analytics.view")
def summary():
    tenant = current_tenant()
    start, end, start_day, end_day = date_range()
    scope = location_scope()
    return jsonify(
        {
            "data": {
                "range": {
                    "start": start_day.isoformat(),
                    "end": end_day.isoformat(),
                    "timezone": tenant.business.timezone,
                },
                "metrics": analytics.summary(tenant.business_id, start, end, scope),
                "series": analytics.daily_series(tenant.business_id, start, end, scope),
                "definitions": analytics.DEFINITIONS,
            }
        }
    )


def _csv_response(filename: str, header: list[str], rows) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        # Neutralise spreadsheet formula injection.
        writer.writerow(["'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v for v in row])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@bp.get("/exports/customers.csv")
@require("exports.run")
@limiter.limit("20 per hour")
def export_customers():
    tenant = current_tenant()
    rows = Customer.query.filter_by(business_id=tenant.business_id).order_by(Customer.id).all()
    audit.record("export.customers", business_id=tenant.business_id, rows=len(rows))
    db.session.commit()
    return _csv_response(
        f"customers-{tenant.business.slug}.csv",
        [
            "id",
            "display_name",
            "email",
            "phone",
            "status",
            "enrolled_at_utc",
            "points_balance",
            "referral_code",
            "marketing_opt_in",
        ],
        (
            [
                c.id,
                c.display_name,
                c.email or "",
                c.phone or "",
                c.status,
                c.enrolled_at.isoformat(),
                c.points_balance,
                c.referral_code,
                "yes" if c.marketing_opt_in else "no",
            ]
            for c in rows
        ),
    )


@bp.get("/exports/ledger.csv")
@require("exports.run")
@limiter.limit("20 per hour")
def export_ledger():
    tenant = current_tenant()
    start, end, start_day, end_day = date_range()
    scope = location_scope()
    query = PointLedgerEntry.query.filter(
        PointLedgerEntry.business_id == tenant.business_id,
        PointLedgerEntry.created_at >= start,
        PointLedgerEntry.created_at < end,
    )
    if scope is not None:
        query = query.filter(PointLedgerEntry.location_id.in_(scope or [0]))
    rows = query.order_by(PointLedgerEntry.id).all()
    audit.record(
        "export.ledger",
        business_id=tenant.business_id,
        rows=len(rows),
        start=start_day.isoformat(),
        end=end_day.isoformat(),
    )
    db.session.commit()
    return _csv_response(
        f"ledger-{tenant.business.slug}-{start_day}-{end_day}.csv",
        [
            "id",
            "created_at_utc",
            "customer_id",
            "location_id",
            "entry_type",
            "points",
            "balance_after",
            "reason",
            "source_type",
            "source_id",
            "actor",
            "reverses_entry_id",
        ],
        (
            [
                e.id,
                e.created_at.isoformat(),
                e.customer_id,
                e.location_id or "",
                e.entry_type,
                e.points,
                e.balance_after,
                e.reason,
                e.source_type or "",
                e.source_id or "",
                e.actor.display_name if e.actor else "",
                e.reverses_entry_id or "",
            ]
            for e in rows
        ),
    )
