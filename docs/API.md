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
| POST | `/auth/signin` | `email, password` |
| POST | `/auth/signout` | |
| POST | `/auth/demo-login` | `role` — only when `DEMO_MODE` and not production |
| POST | `/auth/switch-business` | `business_id` (must be a member) |
| POST | `/auth/verify-email` · `/auth/verify-email/resend` | |
| POST | `/auth/password-reset/request` · `/auth/password-reset/confirm` | Request always returns 200 |
| PATCH | `/auth/account` | `display_name, timezone` |
| POST | `/auth/change-password` | Revokes other sessions |
| GET | `/auth/invitations/{token}` | Invitation preview |
| POST | `/auth/invitations/{token}/accept` | New user: `display_name, password` |

### Business, team, locations, program
| Method | Path | Permission |
|---|---|---|
| POST | `/businesses` | signed in (onboarding: business + owner + location + program) |
| GET/PATCH | `/businesses/current` | member / `business.manage` |
| GET | `/members` | `members.view` |
| POST | `/members/invitations` | `members.manage` (verified email required; roles manager/staff only) |
| DELETE | `/members/invitations/{id}` | `members.manage` |
| PATCH | `/members/{id}` | `members.manage` (`role, status, all_locations, location_ids`; not self, not owners) |
| GET | `/locations` | `locations.view` (includes `accessible`) |
| POST · PATCH | `/locations` · `/locations/{id}` | `locations.manage` |
| GET · PATCH | `/programs/current` | `program.view` · `program.manage` |
| POST | `/programs/current/run-expiry` | `expiry.run` |
| GET | `/audit-logs?action=` | `audit.view` |

### Customers, ledger, purchases
| Method | Path | Permission |
|---|---|---|
| GET | `/customers?q=&status=` | `customers.view` |
| POST | `/customers` | `customers.create` (`display_name`, `email` and/or `phone`, `location_id`, `referral_code`, `marketing_opt_in`) |
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
| PATCH | `/customer-portal/consent` | `marketing_opt_in` |
| POST | `/customer-portal/signout` | |

### System
| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{"status","database"}` only |
| GET | `/meta` | App name and demo flags |
| GET | `/dev/outbox` | Demo mode only; 404 otherwise |
| GET | `/admin/businesses` | Platform administrators only |
