"""Small, explicit input validation helpers.

Each helper raises ``ValidationError`` with a field-keyed message so the
frontend can render errors next to inputs.
"""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from flask import request

from .errors import ValidationError

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_CENTS = 100_000_000  # $1,000,000 per transaction ceiling


def body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object")
    return data


class Fields:
    """Collects all field errors before raising, so forms can show every problem at once."""

    def __init__(self, data: dict):
        self.data = data
        self.errors: dict[str, str] = {}
        self.out: dict = {}

    def _fail(self, name, message):
        self.errors.setdefault(name, message)

    def present(self, name) -> bool:
        return name in self.data

    def string(self, name, required=True, max_len=255, min_len=1, default=None, strip=True):
        value = self.data.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            if required:
                self._fail(name, "Required")
            else:
                self.out[name] = default
            return self.out.get(name)
        if not isinstance(value, str):
            self._fail(name, "Must be text")
            return None
        value = value.strip() if strip else value
        if len(value) < min_len:
            self._fail(name, f"Must be at least {min_len} characters")
        elif len(value) > max_len:
            self._fail(name, f"Must be at most {max_len} characters")
        self.out[name] = value
        return value

    def email(self, name, required=True):
        value = self.string(name, required=required, max_len=254)
        if value is not None:
            value = normalize_email(value)
            if not EMAIL_RE.match(value):
                self._fail(name, "Enter a valid email address")
            self.out[name] = value
        return value

    def phone(self, name, required=False):
        value = self.string(name, required=required, max_len=32)
        if value is not None:
            normalized = normalize_phone(value)
            if normalized is None:
                self._fail(name, "Enter a valid US phone number")
            self.out[name] = normalized
        return self.out.get(name)

    def password(self, name="password"):
        value = self.data.get(name)
        if not isinstance(value, str) or len(value) < 10:
            self._fail(name, "Use at least 10 characters")
        elif len(value) > 128:
            self._fail(name, "Use at most 128 characters")
        self.out[name] = value
        return value

    def integer(self, name, required=True, min_value=None, max_value=None, default=None):
        value = self.data.get(name)
        if value is None or value == "":
            if required:
                self._fail(name, "Required")
            self.out[name] = default
            return default
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            self._fail(name, "Must be a whole number")
            return None
        try:
            value = int(value)
        except ValueError:
            self._fail(name, "Must be a whole number")
            return None
        if min_value is not None and value < min_value:
            self._fail(name, f"Must be at least {min_value}")
        if max_value is not None and value > max_value:
            self._fail(name, f"Must be at most {max_value}")
        self.out[name] = value
        return value

    def boolean(self, name, required=False, default=None):
        value = self.data.get(name)
        if value is None:
            if required:
                self._fail(name, "Required")
            self.out[name] = default
            return default
        if not isinstance(value, bool):
            self._fail(name, "Must be true or false")
            return None
        self.out[name] = value
        return value

    def choice(self, name, options, required=True, default=None):
        value = self.data.get(name)
        if value is None:
            if required:
                self._fail(name, "Required")
            self.out[name] = default
            return default
        if value not in options:
            self._fail(name, f"Must be one of: {', '.join(options)}")
            return None
        self.out[name] = value
        return value

    def money(self, name, required=True, allow_zero=False):
        """Accepts "12.34" / 12.34 / "12" and returns integer cents using Decimal arithmetic."""
        value = self.data.get(name)
        if value is None or value == "":
            if required:
                self._fail(name, "Required")
            self.out[name] = None
            return None
        cents = parse_money_to_cents(value)
        if cents is None:
            self._fail(name, "Enter an amount like 12.50")
            return None
        if cents < 0 or (cents == 0 and not allow_zero):
            self._fail(name, "Must be greater than zero" if not allow_zero else "Cannot be negative")
        elif cents > MAX_CENTS:
            self._fail(name, "Amount is too large")
        self.out[name] = cents
        return cents

    def color(self, name, required=False):
        value = self.string(name, required=required, max_len=7)
        if value is not None and not HEX_COLOR_RE.match(value):
            self._fail(name, "Use a hex color like #1769aa")
        return value

    def url(self, name, required=False):
        value = self.string(name, required=required, max_len=500)
        if value and not value.startswith("https://"):
            self._fail(name, "Must be an https:// URL")
        return value

    def int_list(self, name, default=None):
        value = self.data.get(name, default)
        if value is None:
            self.out[name] = []
            return []
        if not isinstance(value, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in value):
            self._fail(name, "Must be a list of IDs")
            return []
        self.out[name] = sorted(set(value))
        return self.out[name]

    def check(self) -> dict:
        if self.errors:
            raise ValidationError("Please correct the highlighted fields", fields=self.errors)
        return self.out


def normalize_email(value: str) -> str:
    return value.strip().lower()


def normalize_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"+1{digits}"


def parse_money_to_cents(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        value = repr(value)
    try:
        dec = Decimal(str(value).strip().replace(",", "").lstrip("$"))
    except (InvalidOperation, ValueError):
        return None
    if not dec.is_finite():
        return None
    if dec.as_tuple().exponent < -2:
        return None
    return int((dec * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pagination_args(default_size=25, max_size=100) -> tuple[int, int]:
    try:
        page = max(1, int(request.args.get("page", 1)))
        size = min(max_size, max(1, int(request.args.get("page_size", default_size))))
    except ValueError:
        raise ValidationError("Invalid pagination parameters")
    return page, size


def paginate(query, serializer, default_size=25):
    page, size = pagination_args(default_size)
    total = query.order_by(None).count()
    items = query.limit(size).offset((page - 1) * size).all()
    return {
        "data": [serializer(item) for item in items],
        "meta": {"page": page, "page_size": size, "total": total, "pages": max(1, -(-total // size))},
    }
