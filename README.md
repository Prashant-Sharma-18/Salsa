# LoyalLoop

LoyalLoop is a multi-tenant loyalty and referral MVP for independent US retailers, salons, gyms, cafés and small chains. Merchants use it to run a points program, issue and redeem rewards, track referrals, manage staff across locations, and review analytics. Customers get a mobile-friendly rewards page, reached through a secure emailed link.

> The name is a working title and is configurable through `APP_NAME`. Trademark availability has not been checked.

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, Flask 3 (app factory + Blueprints), SQLAlchemy 2, Flask-Migrate/Alembic, Argon2, Flask-Limiter |
| Database | PostgreSQL in production. SQLite for local development and tests. |
| Frontend | React 18, TypeScript, Vite 5, React Router 6, TanStack Query 5, React Hook Form + Zod, SCSS design tokens, lucide-react icons |
| Tests | Pytest (backend), Vitest + React Testing Library (frontend), Playwright and a Python HTTP smoke script (end-to-end) |

```
backend/   Flask API (app/api = routes, app/services = business logic, app/models.py, migrations/, tests/)
frontend/  React app (src/pages, src/components, src/styles, e2e/)
docs/      API reference, privacy notice template
```

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), [SECURITY.md](SECURITY.md) and [docs/API.md](docs/API.md).

## Local setup

Prerequisites: Python 3.12, Node 20. PostgreSQL is optional locally. The default is SQLite.

```bash
cp .env.example .env            # placeholders; DEMO_MODE=true for local use

# Backend
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows (Git Bash: source .venv/Scripts/activate); macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
flask db upgrade                # creates backend/instance/loyalloop.db
flask seed-demo                 # optional, clearly labelled sample data
flask run --port 5000

# Frontend (second terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173 (proxies /api to :5000)
```

### Demo mode (local only)

`flask seed-demo` creates **Maple Street Coffee (Demo)**. It has two locations, 14 customers, four rewards, 90 days of ledger history, redemptions in several states and referrals. The sign-in page has one-click **Demo owner / manager / staff** buttons. You can also sign in with these accounts:

| Role | Email | Password |
|---|---|---|
| Owner | owner@demo.loyalloop.test | `DemoPass-2024!` |
| Manager | manager@demo.loyalloop.test | `DemoPass-2024!` |
| Staff (Downtown only) | staff@demo.loyalloop.test | `DemoPass-2024!` |
| Platform admin | admin@demo.loyalloop.test | `DemoPass-2024!` |

- Demo data carries visible labels in the UI.
- Run `flask seed-demo --reset` to rebuild it. This deletes only demo records.
- Seeding, demo login and demo accounts are all refused when `APP_ENV=production` or `DEMO_MODE` is off.

**Dev mailbox:** emails go to an outbox table instead of being sent. In demo mode, open <http://localhost:5173/dev/mailbox> to follow verification, invitation, password-reset and customer sign-in links.

### Trying the customer side

1. From a customer's page, click **Email loyalty page link**, then open the link from the dev mailbox.
2. The public join page is at `/join/<business-slug>`. Referral links look like `/join/<slug>?ref=CODE`.
3. To request a sign-in link, use `/portal/<business-slug>`.

## Commands

| Purpose | Command (from `backend/`) |
|---|---|
| Apply migrations | `flask db upgrade` |
| Create migration after model change | `flask db migrate -m "message"` and review the generated file |
| Check models match migrations | `flask db check` |
| Seed / reset demo data | `flask seed-demo [--reset]` |
| Expire inactive balances and stale codes | `flask expire-points` (schedule daily via cron) |
| Award today's birthday bonuses | `flask birthday-bonuses` (schedule daily; safe to re-run) |
| Grant platform admin | `flask make-admin EMAIL [--revoke]` |
| Verify cached balances against the ledger | `flask reconcile` (exit 1 on mismatch) |
| Send queued emails continuously (worker process) | `flask email-worker [--interval 10]` |
| Send one batch of queued emails | `flask deliver-emails` |
| Backend tests (SQLite) | `python -m pytest -q` |
| Backend tests (PostgreSQL) | `TEST_DATABASE_URL=postgresql+psycopg2://user:pw@host/db python -m pytest -q` |
| Lint | `ruff check .` |

| Purpose | Command (from `frontend/`) |
|---|---|
| Dev server | `npm run dev` |
| Unit/component tests | `npm test` |
| Type check | `npm run typecheck` |
| Production build | `npm run build` |
| Browser E2E (needs server, see below) | `npm run e2e` |

### End-to-end tests

The E2E tests run against Flask serving the built frontend, with the demo seeded:

```bash
cd frontend && npm run build
cd ../backend && flask seed-demo --reset && DEMO_MODE=true flask run --port 5000
# another terminal:
python backend/scripts/smoke_e2e.py http://127.0.0.1:5000     # HTTP journey: MVP criteria 1–8 + portal
cd frontend && npm run e2e                                     # Playwright, uses installed Chrome (E2E_BROWSER_CHANNEL=msedge for Edge)
```

## Verification results

All results below come from runs on 2026-10-23 on Windows 10 with Python 3.12.7, Node 20.19.6 and PostgreSQL 16.2. Postgres ran locally through the `pgserver` package.

| Check | Command | Result |
|---|---|---|
| Backend tests on SQLite | `python -m pytest -q` | **110 passed** |
| Backend tests on PostgreSQL 16 | `TEST_DATABASE_URL=… pytest -q` | **110 passed**, including the 6-thread concurrent-redemption test |
| Backend lint | `ruff check .`, `ruff format --check` | Clean |
| Migrations on PostgreSQL | `db upgrade` → `db check` → `db downgrade base` → `db upgrade` → `seed-demo` → `seed-demo --reset` → `reconcile` | All clean |
| Production guards | `create_app()` with `APP_ENV=production` | Refuses to start with demo mode on, with SQLite, without `SECRET_KEY`, or with insecure SMTP |
| Email over SMTP | `tests/test_email.py` against a real local SMTP server (aiosmtpd), plus `flask deliver-emails` on the dev database | Delivered. Headers and links correct, no duplicate sends, retries then marks failed, logs are redacted. |
| Frontend tests | `npm test` | **38 passed** |
| Type check and build | `npm run typecheck`, `npm run build` | Clean |
| HTTP E2E on PostgreSQL | `scripts/smoke_e2e.py` | Passed (MVP criteria 1–8 plus customer portal) |
| Browser E2E | `npm run e2e` (Chrome) | **8 passed**: all main pages, staff purchase and redemption, enrollment, mobile layout, two-factor with real TOTP codes, counter-sign QR, admin suspend/reinstate, promotion applied at checkout |
| Two-factor / lockout | `tests/test_security_hardening.py` | RFC 6238 test vectors, enrolment, replay rejected, recovery codes single use, challenge expiry, lockout and unlock, require-two-factor policy, trusted-proxy IP handling |
| Dependency scan | `pip-audit -r requirements.txt`, `npm audit` | **0 known vulnerabilities** (after upgrading Flask, Flask-Cors, python-dotenv, react-router, Vite, Vitest and Playwright) |

**Not run locally:** the Docker image and docker-compose, because Docker isn't installed on this machine. The GitHub Actions `docker` job builds the image, starts the stack with PostgreSQL and the email worker, and runs the smoke test against the container. Check that job's result on GitHub.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and on every pull request:

| Job | What it does |
|---|---|
| Dependency scan | `pip-audit` and `npm audit`. Dependabot also opens weekly update PRs. |
| Backend (sqlite / postgres) | Lint, format check, full pytest on both databases. On Postgres it also runs migrations up, down and up again, a migration/model drift check, seed and reconcile. |
| Frontend | Type check, Vitest, production build |
| End-to-end | PostgreSQL service, built SPA served by Flask, HTTP smoke test and Playwright on Chromium |
| Docker | `docker compose up --build` (app, worker, PostgreSQL), then the smoke test against the container |

## Plans and billing

Plans, prices and limits are defined in `backend/app/billing.py` (`PLANS`). The prices are placeholders, so set your own.

| Plan | Price (placeholder) | Locations | Customers | Team members |
|---|---|---|---|---|
| Free trial (14 days) | — | 3 | 5,000 | 10 |
| Starter | $29/mo | 1 | 500 | 3 |
| Growth | $79/mo | 3 | 5,000 | 10 |
| Pro | $199/mo | Unlimited | Unlimited | Unlimited |

- Limits are enforced on the server and return HTTP 402 `plan_limit_reached`. Pending invitations count toward the team-member limit.
- When a trial ends or a subscription is cancelled, the business becomes **read-only**. Owners can still view data, export, handle privacy requests, edit settings, remove team members and pay. Purchases, enrollments and redemptions return 402 until they choose a plan. The public join page closes, and no data is deleted.
- `past_due` keeps full access, with a warning, while Stripe retries the payment.
- **Providers** (`BILLING_PROVIDER`):
  - `dev` simulates plan changes locally and is refused in production.
  - `stripe` uses Checkout, the Customer Portal and signed, idempotent webhooks. Setup steps are in `.env.example`.
  - `none` turns off self-serve plan changes.
- The Stripe integration is tested against signed webhook payloads and a mocked API. It has **not** been run against a live Stripe account. Test it in Stripe test mode before launch.

## Monitoring and logs

- **Request IDs:** every response carries an `X-Request-ID` header. An incoming ID from a load balancer is reused if it's well-formed. Server errors (500) show this ID to the user as a support reference, and log it alongside the stack trace.
- **Access log:** one line per API request (`loyalloop.request`), with method, path, status, duration, request ID and user ID. Query strings are never logged, because they can contain one-time tokens.
- **Sentry (optional):** set `SENTRY_DSN` to turn it on. Before an event leaves the server, `observability.scrub_event` removes cookies, auth, CSRF, idempotency and signature headers, request bodies and query strings, and replaces emails and token-like strings with placeholders. Users appear by internal ID only.
- **Frontend:** an error boundary shows a recovery screen instead of a blank page. No frontend telemetry is sent.

## Platform administration

The `/admin` console is for the people who run LoyalLoop, not for merchants.

- **Access:** grant it to an existing user with `flask make-admin you@example.com`, and revoke it with `--revoke`. In production, admins must turn on two-factor before the console opens.
- **What admins can see:** business-level metadata only: plan, billing status, usage, owner contact, and admin/billing history. Admins **cannot** see customer records, ledgers or analytics. They also have no tenant access.
- **What admins can do:** each action requires a reason and is written to the business's audit log with the admin as actor.
  - Suspend or reinstate a business. While suspended, its team, public join page and customer portal are blocked, and nothing is deleted.
  - Set a plan manually, for example for invoiced customers.
  - Extend a trial.

## How points work

- **Earning:** `floor(eligible_cents × points_per_dollar / 100)`, using integer maths only. Purchases below the program's minimum spend earn nothing.
- **Money:** stored as integer cents and parsed with `Decimal`. Floating-point arithmetic is never used for currency.
- **Balance:** `customers.points_balance` is a cached balance. It changes in the same transaction as each ledger insert, through a guarded atomic `UPDATE … WHERE points_balance + delta >= 0`. Each ledger row stores `balance_after`. `flask reconcile` checks that the cache equals `SUM(points)` for every customer.
- **Corrections:** ledger rows are never edited or deleted. Reversals and manual adjustments are new rows, each with an actor and a reason, and they are audited.
- **Expiry policy (optional):** a whole balance expires after N days with no earning or redemption activity. The expiry runs from `flask expire-points` or the owner's **Run expiry now** button. It is idempotent.
- **Redemptions:** points are debited when a code is issued. A code moves from `issued` to `redeemed`, `cancelled` or `expired`. Cancelled and expired codes refund points. The app does **not** connect to a POS or payment terminal. Staff apply the reward at their register.
- **Promotions:** these add points to purchases that already earn points.
  - A *multiplier* (for example 2x) applies the single best multiplier: extra = floor(base × (multiplier − 100%)).
  - A *bonus* adds a flat amount, and multiple bonuses add together.
  - Each promotion can be limited by date range, weekday, location and minimum spend, using the business's time zone.
  - The applied promotions are stored on the purchase and named in the ledger reason, so reversing the purchase also removes them.
- **Birthday bonus:** customers can optionally share a birth month and day (no year). `flask birthday-bonuses` awards the configured points once per customer per year. A Feb 29 birthday is celebrated on Feb 28 in non-leap years. The bonus doesn't count as customer activity for inactivity expiry.
- **Referrals:** a referral moves from `created` (staff-recorded invite) to `signed_up`, `qualified` and `rewarded`, or to `rejected`. A referral qualifies on the friend's first staff-recorded purchase at or above the configured minimum.

## Deployment

**Render:** see [docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md). `render.yaml` creates the web app, email worker, daily jobs, PostgreSQL and Redis in one Blueprint.

The `Dockerfile` builds the frontend, then runs Flask and gunicorn. That one container serves both `/api/v1` and the SPA from a single origin, which keeps cookies same-site and lets CORS stay off. `docker-compose.yml` starts the app with PostgreSQL for local trials. Neither file has been executed (see above).

A typical production setup:
1. A managed PostgreSQL instance with daily automated backups and point-in-time recovery. Test restores regularly.
2. The container on any platform that can run it (Render, Fly.io, ECS, Cloud Run), with HTTPS terminated at the platform.
3. Environment variables: `APP_ENV=production`, `SECRET_KEY`, `DATABASE_URL`, `COOKIE_SECURE=true`, `PUBLIC_BASE_URL`, `RATELIMIT_STORAGE_URI=redis://…`.
4. Migrations run on start (`flask db upgrade`). For zero-downtime deploys, run them as a separate release step.
5. A second process running `flask email-worker`, using the same image with a different command, as in `docker-compose.yml`.
6. Scheduled jobs: `flask expire-points` and `flask birthday-bonuses` daily, and `flask reconcile` daily with alerting.

## External services still required

| Need | Status |
|---|---|
| Email delivery | Set `EMAIL_PROVIDER=smtp` with credentials from any SMTP relay (SendGrid, Postmark, SES, Mailgun; see `.env.example`), and run `flask email-worker` as a second process. The provider also needs SPF/DKIM records on your sending domain. |
| Redis (production rate limiting) | Optional locally. Recommended in production. |
| Billing | Not implemented. `businesses.plan` marks where Stripe would connect. |
| POS / payment terminal | Out of scope. Purchases are entered manually. |

## Known limitations

- Docker has only been verified through CI. It was not run locally.
- Email delivery has been tested against a local SMTP server, not against a commercial provider account.
- Two-factor sign-in is optional per user. Owners can require it for owners and managers.
- Analytics daily series are grouped in Python, which is fine at MVP scale. Move this into SQL for large tenants.
- Link-click referral tracking (`clicked` state) is not recorded. This is deliberate, to avoid collecting unnecessary data.
- The P1 items not built are QR codes, webhooks, promotion campaigns and scheduled-job infrastructure.
- The UI was designed against WCAG 2.2 AA (labels, focus states, contrast tokens, reduced motion, keyboard-operable dialogs). It has not had an accessibility audit and does not claim compliance.
- See [SECURITY.md](SECURITY.md) for security limitations.
