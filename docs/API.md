# LoyalLoop API (v1)

Base path: `/api/v1`. All requests and responses are JSON.

## Conventions

| Topic | Rule |
|---|---|
| Success | `{"data": ...}`; lists add `"meta": {"page", "page_size", "total", "pages"}` |
| Errors | `{"error": {"code": "...", "message": "...", "fields": {"field": "message"}}}` |
| Status codes | 400 bad request · 401 not signed in · 403 not permitted / bad CSRF · 404 not found (also used for other tenants' IDs) · 409 conflict (duplicate, insufficient points, invalid transition) · 415 non-JSON write · 422 validation · 429 rate limited |
| Auth | Session cookie `ll_session` (HttpOnly, SameSite=Lax, Secure in production) |
| CSRF | Every authenticated `POST/PATCH/DELETE` must send `X-CSRF-Token` (value from `/auth/me` or any auth response) |
| Idempotency | `POST /purchases`, `POST /redemptions` and `POST /customer-portal/redemptions` require an `Idempotency-Key` header (8–64 chars). Repeating a key returns the original result with `200` instead of creating a duplicate. |
| Money | Send amounts as decimal strings (`"12.50"`); responses use integer cents (`amount_cents`) |
| Points | Integers |
| Time | UTC ISO-8601 with `Z`; analytics `start`/`end` are `YYYY-MM-DD` in the business time zone |
| Pagination | `?page=1&page_size=25` (max 100) |

The business is **never** taken from the request. It is the session's active business, re-verified against an active membership on every request.

## Endpoints

Permission names come from `backend/app/security.py` (`ROLE_PERMISSIONS`).

### Auth — `/auth`
| Method | Path | Notes |
|---|---|---|
| GET | `/auth/me` | Current session (`data: null` when signed out) |
| POST | `/auth/signup` | `display_name, email, password` |
| POST | `/auth/signin` | `email, password`. Returns a session, or `{mfa_required, mfa_token}` when two-factor is on. `423 account_locked` after repeated failures. |
| POST | `/auth/signout` | |
| POST | `/auth/demo-login` | `role` — only when `DEMO_MODE` and not production |
| POST | `/auth/switch-business` | `business_id` (must be a member) |
| POST | `/auth/verify-email` · `/auth/verify-email/resend` | |
| POST | `/auth/password-reset/request` · `/auth/password-reset/confirm` | Request always returns 200 |
| POST | `/auth/mfa/verify` | Second sign-in step: `mfa_token` plus `code` or `recovery_code` |
| GET | `/auth/mfa` | Two-factor status and unused recovery-code count |
| POST | `/auth/mfa/setup` | Returns `secret`, `otpauth_uri`, `qr_svg` (not enabled until confirmed) |
| POST | `/auth/mfa/enable` | `code` — turns two-factor on, returns 10 recovery codes once |
| POST | `/auth/mfa/disable` | `password` + `code`/`recovery_code` |
| POST | `/auth/mfa/recovery-codes` | `password` + `code`/`recovery_code` — replaces recovery codes |
| PATCH | `/auth/account` | `display_name, timezone` |
| POST | `/auth/change-password` | Revokes other sessions |
| GET | `/auth/invitations/{token}` | Invitation preview |
| POST | `/auth/invitations/{token}/accept` | New user: `display_name, password` |

### Business, team, locations, program
| Method | Path | Permission |
|---|---|---|
| POST | `/businesses` | signed in (onboarding: business + owner + location + program) |
| GET/PATCH | `/businesses/current` | member / `business.manage` (`name, timezone, require_mfa`) |
| GET | `/members` | `members.view` |
| POST | `/members/invitations` | `members.manage` (verified email required; roles manager/staff only) |
| DELETE | `/members/invitations/{id}` | `members.manage` |
| PATCH | `/members/{id}` | `members.manage` (`role, status, all_locations, location_ids`; not self, not owners) |
| GET | `/locations` | `locations.view` (includes `accessible`) |
| POST · PATCH | `/locations` · `/locations/{id}` | `locations.manage` |
| GET · PATCH | `/programs/current` | `program.view` · `program.manage` |
| GET | `/programs/current/join-qr.svg` | `program.view` — QR code (SVG) for the public join page |
| GET | `/programs/current/sign` | `program.view` — data for the printable counter sign |
| POST | `/programs/current/run-expiry` | `expiry.run` |
| GET | `/audit-logs?action=` | `audit.view` |

### Customers, ledger, purchases
| Method | Path | Permission |
|---|---|---|
| GET | `/customers?q=&status=` | `customers.view` |
| POST | `/customers` | `customers.create` (`display_name`, `email` and/or `phone`, `location_id`, `referral_code`, `marketing_opt_in`) |
| POST | `/customers/import` | `customers.import` (owner, manager): `csv` (text, ≤2 MB / 5,000 rows), `dry_run` (default true), `import_points`, `import_consent`. Preview returns create/skip/error counts and per-row errors; a real import is all-or-nothing and refuses while any row has errors. |
| GET · PATCH | `/customers/{id}` | `customers.view` · `customers.edit` |
| POST | `/customers/{id}/consent` | `customers.create` |
| GET | `/customers/{id}/ledger` | `customers.view` |
| POST | `/customers/{id}/adjustments` | `ledger.adjust` (`points`, `reason` required) |
| GET | `/customers/{id}/reconcile` | `ledger.adjust` |
| GET | `/customers/{id}/privacy-export` | `customers.privacy` |
| POST | `/customers/{id}/anonymize` | `customers.privacy` (`confirm: "DELETE"`) |
| POST | `/customers/{id}/portal-link` | `customers.view` |
| GET | `/ledger?type=&location_id=` | `analytics.view` |
| POST | `/ledger/{id}/reverse` | `ledger.reverse` (`reason`) |
| POST | `/purchases` | `purchases.create` + `Idempotency-Key` (`customer_id, location_id, amount, eligible_amount?, external_ref?`) |

### Rewards, redemptions, referrals
| Method | Path | Permission |
|---|---|---|
| GET | `/rewards?status=` | `rewards.view` |
| POST · PATCH · DELETE | `/rewards` · `/rewards/{id}` | `rewards.manage` (delete only if never redeemed) |
| GET | `/redemptions?status=&customer_id=` | `redemptions.issue` |
| POST | `/redemptions` | `redemptions.issue` + `Idempotency-Key` |
| GET | `/redemptions/lookup?code=` | `redemptions.complete` |
| POST | `/redemptions/{id}/complete` | `redemptions.complete` (`location_id`) |
| POST | `/redemptions/{id}/cancel` | `redemptions.cancel` (`reason`, refunds points) |
| GET | `/referrals?status=` | `referrals.view` |
| POST | `/referrals` | `referrals.manage` (`referrer_customer_id, email`) |
| POST | `/referrals/{id}/reject` | `referrals.manage` |

### Analytics and exports
| Method | Path | Permission |
|---|---|---|
| GET | `/dashboard?start=&end=&location_id=` | `customers.view` (metrics only with `analytics.view`) |
| GET | `/analytics/summary?start=&end=&location_id=` | `analytics.view` — metrics, daily series, definitions |
| GET | `/exports/customers.csv` | `exports.run` (audited) |
| GET | `/exports/ledger.csv?start=&end=&location_id=` | `exports.run` (audited) |

### Customer-facing
| Method | Path | Notes |
|---|---|---|
| GET | `/public/programs/{slug}` | Public program info and rewards |
| POST | `/public/programs/{slug}/join` | `display_name, email, marketing_opt_in, ref?` — same response whether or not the email exists |
| POST | `/customer-portal/request-link` | `business_slug, email` — same response whether or not the email exists |
| POST | `/customer-portal/session` | Exchange single-use link token for the `ll_portal` cookie |
| GET | `/customer-portal/me` | The signed-in customer's own data only |
| POST | `/customer-portal/redemptions` | `reward_id` + `Idempotency-Key` |
| GET | `/customer-portal/referral-qr.svg` | QR code of the customer's own referral link |
| PATCH | `/customer-portal/consent` | `marketing_opt_in` |
| POST | `/customer-portal/signout` | |

### Promotions
| Method | Path | Permission |
|---|---|---|
| GET | `/promotions?status=` | `promotions.view` (all roles) |
| GET | `/promotions/active?location_id=` | `promotions.view` — promotions running today (for the checkout preview) |
| POST · PATCH | `/promotions` · `/promotions/{id}` | `promotions.manage` (owner, manager): `name, description, promo_type (multiplier/bonus), multiplier_percent (101–1000) or bonus_points, starts_on, ends_on?, days_of_week [0=Mon..6], location_ids, min_spend, status` |
| PATCH | `/customer-portal/profile` | Customer sets `birth_month` + `birth_day` |

Customers (`POST/PATCH /customers`) and public join also accept optional `birth_month` + `birth_day`. Program settings accept `birthday_bonus_points`.

### Billing
| Method | Path | Notes |
|---|---|---|
| GET | `/billing` | `billing.manage` (owner): plan, status, limits, usage, plan catalog |
| POST | `/billing/checkout` | `plan` → Stripe Checkout URL (stripe provider) |
| POST | `/billing/portal` | Stripe Customer Portal URL |
| POST | `/billing/dev/switch` | `plan` — simulated change (dev provider, non-production only) |
| POST | `/billing/stripe/webhook` | Stripe events, verified with `Stripe-Signature`; idempotent by event id |

Writes from a business that is not in good standing return `402 subscription_inactive`. Exceeding a plan limit returns `402 plan_limit_reached`.

### System
| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{"status","database"}` only |
| GET | `/meta` | App name and demo flags |
| GET | `/dev/outbox` | Demo mode only; 404 otherwise |
| GET | `/admin/overview` | Platform admin: business counts by status, MRR, users, customers |
| GET | `/admin/businesses?q=&status=` | Platform admin: business list (no customer data) |
| GET | `/admin/businesses/{id}` | Owners, usage, limits, admin/billing history |
| POST | `/admin/businesses/{id}/suspend` · `/unsuspend` | `reason` required, audit-logged |
| POST | `/admin/businesses/{id}/plan` | `plan` + `status`, or `extend_trial_days`; `reason` required |
