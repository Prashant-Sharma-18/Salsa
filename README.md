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
| Backend tests on SQLite | `python -m pytest -q` | **53 passed** |
| Backend tests on PostgreSQL 16 | `TEST_DATABASE_URL=… pytest -q` | **53 passed**, including the 6-thread concurrent-redemption test |
| Backend lint | `ruff check .`, `ruff format --check` | Clean |
| Migrations on PostgreSQL | `db upgrade` → `db check` → `db downgrade base` → `db upgrade` → `seed-demo` → `seed-demo --reset` → `reconcile` | All clean |
| Production guards | `create_app()` with `APP_ENV=production` | Refuses to start with demo mode on, with SQLite, without `SECRET_KEY`, or with insecure SMTP |
| Email over SMTP | `tests/test_email.py` against a real local SMTP server (aiosmtpd), plus `flask deliver-emails` on the dev database | Delivered. Headers and links correct, no duplicate sends, retries then marks failed, logs are redacted. |
| Frontend tests | `npm test` | **23 passed** |
| Type check and build | `npm run typecheck`, `npm run build` | Clean |
| HTTP E2E on PostgreSQL | `scripts/smoke_e2e.py` | Passed (MVP criteria 1–8 plus customer portal) |
| Browser E2E on PostgreSQL | `npm run e2e` (Chrome) | **4 passed** |

**Not run locally:** the Docker image and docker-compose, because Docker isn't installed on this machine. The GitHub Actions `docker` job builds the image, starts the stack with PostgreSQL and the email worker, and runs the smoke test against the container. Check that job's result on GitHub.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and on every pull request:

| Job | What it does |
|---|---|
| Backend (sqlite / postgres) | Lint, format check, full pytest on both databases. On Postgres it also runs migrations up, down and up again, a migration/model drift check, seed and reconcile. |
| Frontend | Type check, Vitest, production build |
| End-to-end | PostgreSQL service, built SPA served by Flask, HTTP smoke test and Playwright on Chromium |
| Docker | `docker compose up --build` (app, worker, PostgreSQL), then the smoke test against the container |

## How points work

- **Earning:** `floor(eligible_cents × points_per_dollar / 100)`, using integer maths only. Purchases below the program's minimum spend earn nothing.
- **Money:** stored as integer cents and parsed with `Decimal`. Floating-point arithmetic is never used for currency.
- **Balance:** `customers.points_balance` is a cached balance. It changes in the same transaction as each ledger insert, through a guarded atomic `UPDATE … WHERE points_balance + delta >= 0`. Each ledger row stores `balance_after`. `flask reconcile` checks that the cache equals `SUM(points)` for every customer.
- **Corrections:** ledger rows are never edited or deleted. Reversals and manual adjustments are new rows, each with an actor and a reason, and they are audited.
- **Expiry policy (optional):** a whole balance expires after N days with no earning or redemption activity. The expiry runs from `flask expire-points` or the owner's **Run expiry now** button. It is idempotent.
- **Redemptions:** points are debited when a code is issued. A code moves from `issued` to `redeemed`, `cancelled` or `expired`. Cancelled and expired codes refund points. The app does **not** connect to a POS or payment terminal. Staff apply the reward at their register.
- **Referrals:** a referral moves from `created` (staff-recorded invite) to `signed_up`, `qualified` and `rewarded`, or to `rejected`. A referral qualifies on the friend's first staff-recorded purchase at or above the configured minimum.

## Deployment

The `Dockerfile` builds the frontend, then runs Flask and gunicorn. That one container serves both `/api/v1` and the SPA from a single origin, which keeps cookies same-site and lets CORS stay off. `docker-compose.yml` starts the app with PostgreSQL for local trials. Neither file has been executed (see above).

A typical production setup:
1. A managed PostgreSQL instance with daily automated backups and point-in-time recovery. Test restores regularly.
2. The container on any platform that can run it (Render, Fly.io, ECS, Cloud Run), with HTTPS terminated at the platform.
3. Environment variables: `APP_ENV=production`, `SECRET_KEY`, `DATABASE_URL`, `COOKIE_SECURE=true`, `PUBLIC_BASE_URL`, `RATELIMIT_STORAGE_URI=redis://…`.
4. Migrations run on start (`flask db upgrade`). For zero-downtime deploys, run them as a separate release step.
5. A second process running `flask email-worker`, using the same image with a different command, as in `docker-compose.yml`.
6. Scheduled jobs: `flask expire-points` daily, and `flask reconcile` daily with alerting.

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
- No staff MFA.
- Analytics daily series are grouped in Python, which is fine at MVP scale. Move this into SQL for large tenants.
- Link-click referral tracking (`clicked` state) is not recorded. This is deliberate, to avoid collecting unnecessary data.
- The P1 items not built are QR codes, webhooks, promotion campaigns and scheduled-job infrastructure.
- The UI was designed against WCAG 2.2 AA (labels, focus states, contrast tokens, reduced motion, keyboard-operable dialogs). It has not had an accessibility audit and does not claim compliance.
- See [SECURITY.md](SECURITY.md) for security limitations.
