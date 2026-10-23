# Security

This file covers the threat model, sensitive data, secrets handling and known limitations of the LoyalLoop MVP. It has had no independent security review or penetration test. Do not describe it as compliant with any standard or law (CCPA, PCI DSS, SOC 2 and so on) until a qualified reviewer has assessed it.

## Sensitive data

| Data | Where | Protection |
|---|---|---|
| Staff passwords | `users.password_hash` | Argon2id (`argon2-cffi`). Plain-text passwords are never stored or logged. |
| Sessions | `user_sessions`, `customer_sessions` | Random 256-bit token sent as an HttpOnly, SameSite=Lax cookie (Secure in production). Only the SHA-256 hash is stored. Sessions can be revoked. |
| Reset, verification, invitation and customer link tokens | `auth_tokens`, `business_invitations`, `customer_access_tokens` | Single-use and expiring. Only hashes are stored. |
| Customer contact details | `customers` | Scoped to one business. Full addresses are not logged; email logs are redacted (`a***@example.com`). |
| Points balances and history | `customers`, `point_ledger_entries` | Scoped to one business. The ledger is append-only. |
| Payment cards | — | Not collected. |

## Threat model and mitigations

| Threat | Mitigation |
|---|---|
| Cross-tenant data access (guessing IDs) | The business comes from the session's active membership and is re-checked on every request. It is never read from the request body. Every query filters by `business_id`, and other tenants' IDs return 404. Covered by `tests/test_tenancy_and_permissions.py`. |
| Privilege escalation | Server-side permission matrix (`ROLE_PERMISSIONS`). Invitations can only grant manager or staff. Nobody can change their own role. Owner memberships cannot be changed from the team screen. Role and status changes apply on the next request. |
| Location bypass | `TenantContext.require_location` checks staff location access for purchases, redemptions, completions, analytics and exports. |
| Duplicate or overdrawn points | Idempotency keys, unique receipt references, a guarded atomic balance update (`points_balance + delta >= 0`), a DB CHECK constraint and unique keys on ledger idempotency and reversals. A concurrency test covers it. |
| Ledger tampering | ORM hooks block UPDATE and DELETE on ledger rows. Corrections are reversal or adjustment entries with a mandatory reason, the actor and an audit log entry. |
| CSRF | State-changing requests from a signed-in session need an `X-CSRF-Token` header that matches that session. All API writes must be `application/json` (cross-site forms cannot send that). Cookies are SameSite=Lax. |
| XSS | React escapes output. CSP is `default-src 'self'; script-src 'self'` with no inline scripts. User content is never rendered as HTML. |
| Clickjacking | `X-Frame-Options: DENY` and `frame-ancestors 'none'`. |
| Brute force and enumeration | Flask-Limiter on auth, reset, invitation, join, portal-link, referral and export endpoints. Password reset, portal-link requests and public join return the same response whether or not the email exists. Sign-in uses a dummy hash so timing is constant. |
| Referral abuse | Referral codes are checked on the server. Self-referrals (same customer, email or phone) are rejected. There is a daily limit per referrer. Only a staff-recorded purchase can qualify a referral, and reward keys prevent double payment. No device fingerprinting. |
| Customer portal data leaks | Portal endpoints read the customer only from the portal session and never accept a customer ID. Links are single-use, expire after 24 hours, and the token is removed from the browser URL right away. |
| CSV formula injection | Exported cells that start with `= + - @` are prefixed with `'`. |
| Error leakage | One error handler returns generic messages. Stack traces go to server logs only. `/health` shows only DB reachability. |
| Unsafe demo data in production | The app refuses to start with `DEMO_MODE=true` and `APP_ENV=production`. The seed command and demo login refuse too. Demo users cannot sign in when demo mode is off. |

## Secrets management

- All configuration comes from environment variables. `.env.example` contains placeholders only, and `.env` is git-ignored.
- In production the app refuses to start without a `SECRET_KEY`, with `COOKIE_SECURE` off, with a SQLite database, or with demo mode on.
- Keep secrets in your platform's secret manager. Do not put them in images or compose files.

## Production checklist

1. Set `APP_ENV=production`, a strong `SECRET_KEY`, `COOKIE_SECURE=true` and a PostgreSQL `DATABASE_URL`.
2. Serve over HTTPS only. HSTS is sent when `APP_ENV=production`.
3. Set `RATELIMIT_STORAGE_URI` to Redis so rate limits are shared across workers.
4. Set `EMAIL_PROVIDER=smtp` with TLS (`starttls` or `ssl`) and run `flask email-worker`. Configure SPF and DKIM for the sending domain.
5. Back up PostgreSQL daily and test restores.
6. Restrict database network access. Use a least-privilege DB user.
7. Run `flask reconcile` on a schedule and alert on a non-zero exit.

## Known limitations

- No MFA for staff accounts.
- No account lockout beyond IP-based rate limits.
- The rate limiter keys on the client IP. Behind a proxy, configure `ProxyFix` so the real client IP is used.
- No automated retention or purge job. Anonymization is a manual owner action.
- Email delivery is at-least-once. A worker that crashes mid-send may resend that message after 10 minutes.
- Sign-in links travel by email, so a compromised inbox gives access to the matching rewards page.
- The audit log is append-only by convention, not by database permissions.
- CI does not scan dependencies for vulnerabilities. Consider enabling Dependabot.

## Reporting a vulnerability

Email the maintainers privately (add a contact address here). Do not open a public issue.
