"""Customer import from CSV.

Design:
- Header names are matched case-insensitively with common aliases.
- Every row is validated first; a preview (dry run) reports what would be
  created, skipped or rejected without writing anything.
- A real import is all-or-nothing in one transaction, and refuses to run while
  any row has errors.
- Existing customers (same email in this business) and duplicate rows within
  the file are skipped, never overwritten.
- Opening balances become audited ``adjustment`` ledger entries.
- Marketing consent is imported only when the merchant confirms they hold it.
"""

import calendar
import csv
import io
import re

from flask import current_app

from .. import billing
from ..errors import ApiError, ValidationError
from ..extensions import db
from ..models import Customer
from ..validation import EMAIL_RE, normalize_email, normalize_phone
from . import audit, customers, ledger

MAX_BYTES = 2_000_000
MAX_ROWS = 5_000
MAX_OPENING_POINTS = 1_000_000

HEADER_ALIASES = {
    "name": {"name", "full name", "fullname", "display name", "display_name", "customer", "customer name"},
    "first_name": {"first name", "first_name", "firstname", "given name"},
    "last_name": {"last name", "last_name", "lastname", "surname", "family name"},
    "email": {"email", "e-mail", "email address", "mail"},
    "phone": {"phone", "phone number", "mobile", "cell", "telephone", "tel"},
    "birthday": {"birthday", "birth date", "birthdate", "date of birth", "dob"},
    "points": {"points", "balance", "points balance", "opening balance", "opening points"},
    "marketing_opt_in": {
        "marketing",
        "marketing opt in",
        "marketing_opt_in",
        "opt in",
        "opt-in",
        "subscribed",
        "accepts marketing",
    },
}
TRUE_VALUES = {"yes", "y", "true", "1", "subscribed", "opted in", "opt-in", "x"}
FALSE_VALUES = {"no", "n", "false", "0", "unsubscribed", "", "opted out"}


def _canonical(header: str) -> str | None:
    h = re.sub(r"\s+", " ", header.strip().lower().replace("_", " "))
    for key, aliases in HEADER_ALIASES.items():
        if h in aliases or h.replace(" ", "_") in aliases:
            return key
    return None


def _parse_birthday(value: str) -> tuple[int, int] | None | str:
    """Accepts MM-DD, MM/DD, YYYY-MM-DD, MM/DD/YYYY. Returns (month, day), None if empty, or an error string."""
    v = value.strip()
    if not v:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", v)
    if m:
        month, day = int(m.group(2)), int(m.group(3))
    else:
        m = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})(?:[-/](\d{2,4}))?", v)
        if not m:
            return "Birthday must look like 03-14, 03/14/1990 or 1990-03-14"
        month, day = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12 or not 1 <= day <= calendar.monthrange(2024, month)[1]:
        return "Birthday is not a real date"
    return month, day


def parse(csv_text: str) -> tuple[list[dict], list[str]]:
    """Return (rows, unknown_headers). Each row has 'line' plus canonical fields."""
    if len(csv_text.encode("utf-8")) > MAX_BYTES:
        raise ValidationError("The file is too large (2 MB maximum). Split it into smaller files.")
    text = csv_text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        headers = next(reader)
    except StopIteration:
        raise ValidationError("The file is empty")
    mapping = [_canonical(h) for h in headers]
    if not any(m in ("name", "first_name") for m in mapping):
        raise ValidationError("Add a 'name' column (or 'first name' / 'last name' columns).")
    if not any(m in ("email", "phone") for m in mapping):
        raise ValidationError("Add an 'email' or 'phone' column so customers can be found later.")
    unknown = [h for h, m in zip(headers, mapping, strict=True) if m is None and h.strip()]
    rows = []
    for line_no, values in enumerate(reader, start=2):
        if not any(v.strip() for v in values):
            continue
        row = {"line": line_no}
        for key, value in zip(mapping, values, strict=False):  # short rows (missing trailing cells) are normal
            if key:
                row[key] = value.strip()
        rows.append(row)
        if len(rows) > MAX_ROWS:
            raise ValidationError(f"Too many rows ({MAX_ROWS:,} maximum per file).")
    return rows, unknown


def analyse(business, rows: list[dict], import_points: bool, import_consent: bool) -> dict:
    """Validate rows and classify them. No writes."""
    existing = {
        e
        for (e,) in db.session.query(Customer.email_normalized).filter(
            Customer.business_id == business.id, Customer.email_normalized.isnot(None)
        )
    }
    seen: set[str] = set()
    to_create, skipped, errors = [], [], []
    for row in rows:
        problems = []
        name = row.get("name") or " ".join(p for p in (row.get("first_name"), row.get("last_name")) if p)
        name = (name or "").strip()
        if not name:
            problems.append("Name is missing")
        elif len(name) > 120:
            problems.append("Name is longer than 120 characters")
        email = normalize_email(row["email"]) if row.get("email") else None
        if email and (len(email) > 254 or not EMAIL_RE.match(email)):
            problems.append(f"'{row['email']}' is not a valid email")
            email = None
        phone = None
        if row.get("phone"):
            phone = normalize_phone(row["phone"])
            if phone is None:
                problems.append(f"'{row['phone']}' is not a valid US phone number")
        if not email and not phone and not problems:
            problems.append("Needs an email or phone number")
        birthday = _parse_birthday(row.get("birthday", ""))
        if isinstance(birthday, str):
            problems.append(birthday)
            birthday = None
        points = 0
        if import_points and row.get("points"):
            raw = row["points"].replace(",", "")
            if not re.fullmatch(r"\d+", raw):
                problems.append("Points must be a whole number of 0 or more")
            else:
                points = int(raw)
                if points > MAX_OPENING_POINTS:
                    problems.append(f"Points cannot exceed {MAX_OPENING_POINTS:,}")
        marketing = False
        if import_consent and "marketing_opt_in" in row:
            value = row["marketing_opt_in"].lower()
            if value in TRUE_VALUES:
                marketing = True
            elif value not in FALSE_VALUES:
                problems.append("Marketing must be yes or no")
        if problems:
            errors.append({"line": row["line"], "name": name or None, "errors": problems})
            continue
        if email and email in existing:
            skipped.append({"line": row["line"], "name": name, "reason": "Already a customer (same email)"})
            continue
        if email and email in seen:
            skipped.append({"line": row["line"], "name": name, "reason": "Duplicate email earlier in the file"})
            continue
        if email:
            seen.add(email)
        to_create.append(
            {
                "line": row["line"],
                "display_name": name,
                "email": email,
                "phone": phone,
                "birth_month": birthday[0] if birthday else None,
                "birth_day": birthday[1] if birthday else None,
                "points": points,
                "marketing_opt_in": marketing,
            }
        )
    limit = billing.limits(business)["customers"]
    current = billing.usage(business)["customers"]
    over_limit = limit is not None and current + len(to_create) > limit
    return {
        "to_create": to_create,
        "skipped": skipped,
        "errors": errors,
        "summary": {
            "rows": len(rows),
            "create": len(to_create),
            "skip": len(skipped),
            "error": len(errors),
            "opening_points": sum(r["points"] for r in to_create),
            "marketing_opt_ins": sum(1 for r in to_create if r["marketing_opt_in"]),
        },
        "limit": {"limit": limit, "current": current, "over_limit": over_limit},
    }


def run(tenant, csv_text: str, import_points: bool, import_consent: bool, dry_run: bool, actor_id: int) -> dict:
    rows, unknown = parse(csv_text)
    if not rows:
        raise ValidationError("The file has a header row but no customers.")
    result = analyse(tenant.business, rows, import_points, import_consent)
    preview = {
        "summary": result["summary"],
        "errors": result["errors"][:200],
        "skipped": result["skipped"][:200],
        "sample": [{k: v for k, v in r.items() if k != "line"} for r in result["to_create"][:10]],
        "unknown_columns": unknown,
        "limit": result["limit"],
        "imported": False,
    }
    if dry_run:
        return preview
    if result["errors"]:
        raise ApiError(
            f"Fix the {len(result['errors'])} row(s) with errors before importing. Nothing was imported.",
            code="import_has_errors",
            status=422,
        )
    if result["limit"]["over_limit"]:
        lim = result["limit"]
        raise billing.PaymentRequired(
            f"This import would bring you to {lim['current'] + result['summary']['create']:,} customers; "
            f"your plan allows {lim['limit']:,}. Upgrade in Billing or import fewer rows.",
            code="plan_limit_reached",
        )
    for r in result["to_create"]:
        customer = customers.enroll(
            tenant.business_id,
            r["display_name"],
            r["email"],
            r["phone"],
            r["marketing_opt_in"],
            source="import",
            actor_id=actor_id,
        )
        customer.birth_month, customer.birth_day = r["birth_month"], r["birth_day"]
        if r["points"]:
            ledger.post_entry(
                customer,
                r["points"],
                "adjustment",
                reason="Opening balance imported from CSV",
                source_type="import",
                actor_id=actor_id,
            )
    audit.record(
        "customers.imported",
        business_id=tenant.business_id,
        created=result["summary"]["create"],
        skipped=result["summary"]["skip"],
        opening_points=result["summary"]["opening_points"],
        marketing_opt_ins=result["summary"]["marketing_opt_ins"],
    )
    current_app.logger.info(
        "customers imported business_id=%s count=%s", tenant.business_id, result["summary"]["create"]
    )
    preview["imported"] = True
    return preview
