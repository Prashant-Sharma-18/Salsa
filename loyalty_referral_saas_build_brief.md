# Build Brief: Loyalty and Referral SaaS for US Small Businesses

## Role

Act as a senior product engineer, SaaS architect, security-minded full-stack developer, and product designer. Build a production-minded MVP for a multi-tenant loyalty and referral platform aimed at independent US retailers, salons, gyms, cafés, and small multi-location businesses.

The product helps a merchant launch a branded customer loyalty program, issue and redeem points, encourage referrals, and understand customer engagement.

**Product working name:** LoyalLoop (keep the name configurable; do not assume trademark availability).

## How to use this brief

Use this file as the source of truth when working in Claude Code or Antigravity. First inspect the existing repository and its instructions. Preserve useful existing code and conventions. If the repository is empty, scaffold the application. Do not merely produce a plan: implement the working product in small, verifiable steps.

Before making broad changes:
1. Inspect the repository, package files, and current app structure.
2. Summarize the detected stack and implementation plan.
3. Create or update `IMPLEMENTATION_PLAN.md` and a task checklist.
4. Then implement the application and run the available checks.

If a requirement cannot be completed because credentials or external services are unavailable, implement a safe local/demo adapter and document the exact setup needed. Never claim an integration works unless it has been tested.

---

## 1. Product goals

Build a simple, trustworthy SaaS that lets a merchant:

- Create and configure a loyalty program.
- Enroll customers and look them up quickly at checkout.
- Award points for eligible purchases.
- Redeem points against a configured reward.
- Create and track customer referral codes.
- View customer activity, balances, and program analytics.
- Operate one or more business locations.
- Invite staff with limited permissions.
- Export relevant data and manage privacy-related requests.

Customers should be able to access a simple mobile-friendly loyalty page using a secure link or account flow, view their points, see available rewards, and share their referral link.

### MVP success criteria

A merchant can complete this end-to-end flow without developer intervention:

1. Create a business account.
2. Configure a program and its earning/redemption rules.
3. Add a location and invite or create a staff account.
4. Enroll a customer.
5. Record a purchase and award points.
6. Redeem a reward.
7. Create a referral and see its status.
8. Review transaction history and basic analytics.

Build a functional MVP, not just a static dashboard or UI mockup.

---

## 2. Target users

### Primary users
- Independent US retailers
- Salons and barbershops
- Cafés and quick-service restaurants
- Gyms and boutique fitness studios
- Small local chains with multiple locations

### User roles
- **Platform administrator:** platform-level operational access.
- **Business owner:** manages the business, program, locations, staff, customers, rewards, and reports.
- **Manager:** manages day-to-day program activity and permitted reports.
- **Staff:** enrolls customers, records purchases, and processes permitted redemptions.
- **Customer:** views their own points, rewards, and referral information.

Enforce permissions on the server, not just by hiding interface elements.

---

## 3. Scope

### P0 — required MVP

#### Authentication and onboarding
- Sign up, sign in, sign out, password reset, and email verification flow.
- Business onboarding wizard.
- Multi-tenant business separation.
- Owner, manager, and staff roles.
- Invite staff by email, with expiring single-use invitation tokens.
- Demo mode that works locally without third-party credentials.
- Never store plain-text passwords or expose secrets to the browser.

#### Merchant dashboard
- Summary cards: enrolled customers, points issued, points redeemed, rewards redeemed, referral conversions.
- Activity feed with meaningful empty states.
- Date-range filters.
- Location filter where applicable.
- Loading, error, empty, and success states.

#### Loyalty program settings
- Program name, description, status, brand color, logo, and contact information.
- Earning rule: configurable points per eligible currency unit spent.
- Optional minimum spend.
- Redemption rules: configured point cost and reward value/type.
- Optional points expiry setting; if enabled, record the expiry policy and implement it consistently.
- Enable/disable earning, redemption, and referrals independently.
- Explain rules in plain language to merchant and customer.
- Use integer points and decimal-safe money handling. Store monetary values in cents (integer) where practical; never use binary floating-point arithmetic for currency.

#### Customer management
- Customer list, search, filters, pagination, and customer detail view.
- Fields: display name, email, phone (optional), enrollment date, status, points balance, referral code.
- Deduplicate customers by normalized email within a business where email is provided.
- Validate and normalize user inputs.
- Record customer consent and its timestamp for optional marketing communications.
- Do not require marketing consent just to participate in a loyalty program.
- Support customer data export and a documented deletion/anonymization workflow.

#### Points ledger
- Immutable ledger of point awards, redemptions, reversals, adjustments, and expirations.
- Each entry includes business, customer, location (when relevant), actor, reason, source/reference, timestamp, and idempotency key where relevant.
- Derive the displayed balance from ledger entries or maintain a cached balance that is updated transactionally and reconciled against the ledger.
- Never allow a customer to spend more points than their available balance.
- Prevent duplicate purchase awards and duplicate redemption requests.
- Use database transactions for purchase awards and redemptions.
- Include an auditable manager adjustment flow with a mandatory reason.
- Staff cannot silently edit or delete ledger entries. Correct mistakes with reversal entries.

#### Rewards and redemption
- CRUD for reward catalog items.
- Reward types may include fixed-value discount, free item/service, and merchant-defined reward.
- Configurable point cost, status, optional stock/quantity limit, and terms.
- Redemption flow that atomically checks balance, records the debit, and creates a unique redemption code.
- Redemption status: issued, redeemed, expired, or cancelled, with permitted transitions enforced server-side.
- A staff screen to validate and complete a redemption.
- Do not integrate with a payment terminal in the MVP; make the redemption workflow explicit and honest about this limitation.

#### Referrals
- Generate unique referral codes and shareable URLs.
- Track referrer, referred customer, creation time, status, and attribution source where available.
- Referral states: created, clicked (if tracked), signed up, qualified, rewarded, rejected.
- Configurable reward for referrer and optional referred-customer reward.
- Award referral points only after a configurable qualification event, such as a first eligible purchase.
- Prevent self-referrals and duplicate referral rewards.
- Apply rate limits and abuse checks; do not trust a referral code supplied by the client without server validation.
- Avoid fingerprinting. Collect only the information needed to operate the referral program.

#### Locations and staff
- Multiple locations per business.
- Associate staff, purchases, redemptions, and reports with locations.
- Enforce each staff member's location permissions.
- Owners can invite, deactivate, and change roles for team members.
- Protect against privilege escalation.

#### Analytics and exports
- Date-range metrics: enrollments, active customers, points issued, points redeemed, rewards redeemed, referrals, and qualified referrals.
- Clearly define each metric and how it is calculated.
- CSV export for customers and ledger transactions, restricted by permissions.
- Apply the same tenant and location authorization to export endpoints as to ordinary pages.
- Use sample data in demo mode, visibly labelled as demo data.

#### Customer loyalty page
- Mobile-first, accessible customer page.
- Show available points, ledger history, rewards, program rules, and referral link.
- Customer authentication or expiring secure access links; do not expose customer records through guessable IDs.
- Customers can only access their own information.
- Make marketing opt-in separate from essential program messages.

### P1 — implement only after P0 works
- Branded customer-facing program page.
- QR code for enrollment and referral sharing.
- Email notifications through a provider adapter.
- Scheduled expiry processing.
- Webhook events for key loyalty actions, signed and retried safely.
- Basic coupon/promotion campaigns.
- Audit log search and downloadable reports.

### Explicitly out of scope for MVP
- Native iOS or Android applications.
- Payment processing or card storage.
- POS integrations unless one is selected and credentials are available.
- SMS marketing campaigns.
- Complex tier systems, paid memberships, gift cards, and marketplace integrations.
- Claims of guaranteed sales uplift or legal compliance.

Do not build P1 or out-of-scope features at the expense of the working P0 journey.

---

## 4. Recommended technical architecture

Prefer a maintainable modular monolith over premature microservices.

### Default stack for an empty repository

- **Frontend:** React + TypeScript + Vite.
- **Styling:** SCSS modules or organized SCSS partials, using design tokens and reusable components.
- **Routing:** React Router.
- **Server-state/data fetching:** TanStack Query or a similarly maintained solution.
- **Forms and validation:** React Hook Form + Zod, or an equivalent consistent approach.
- **Backend:** Python Flask with application factory and Blueprints, or retain the existing backend if the repository already has a coherent stack.
- **Database:** PostgreSQL in production; SQLite may be supported for lightweight local development if migrations and behavior remain compatible.
- **ORM/migrations:** SQLAlchemy + Flask-Migrate/Alembic if using Flask.
- **Authentication:** Secure server-side session cookies preferred for a same-origin web application. If using tokens, implement secure refresh, rotation, storage, expiry, and revocation rather than putting long-lived tokens in localStorage.
- **Testing:** Pytest for backend; Vitest and React Testing Library for frontend; Playwright for core end-to-end flows where practical.
- **Deployment:** Dockerfile and Docker Compose for local development; document a production deployment option.
- **Email:** provider interface with a console/logging adapter for local development.
- **Billing:** defer real billing until core workflows are stable; define a clean subscription/billing boundary for later Stripe integration.

If the repository already uses Node.js/Express, Django, or another established stack, keep that stack unless there is a concrete reason to migrate. Do not rewrite a working application just to match this default.

### Architecture boundaries
- Frontend communicates with the backend through a documented API.
- Business logic lives in service/domain modules, not route handlers or React components.
- Authorization and validation happen server-side.
- External integrations sit behind provider adapters.
- Use explicit configuration from environment variables.
- Include `.env.example` with placeholders only.
- Never commit real API keys, passwords, or production customer data.

---

## 5. Data model

Design normalized tables/models with foreign keys, indexes, timestamps, and appropriate constraints. Adjust names to match the chosen framework.

At minimum consider:

- `users`
- `businesses`
- `business_memberships` (user, business, role, status)
- `business_invitations`
- `locations`
- `location_memberships` or equivalent access mapping
- `loyalty_programs`
- `customers`
- `customer_auth_methods` or secure customer access tokens
- `rewards`
- `point_ledger_entries`
- `purchases` or purchase references
- `redemptions`
- `referrals`
- `consent_records`
- `audit_logs`
- `notification_outbox` (if notifications are implemented)

### Tenant isolation
Every business-owned record must be scoped to a business. Every query must derive the authorized business from the authenticated membership/context, not blindly trust a client-supplied `business_id`.

Add tests proving that a user from Business A cannot read or mutate Business B's customers, ledger entries, rewards, referrals, exports, or reports—even when they guess valid IDs.

### Ledger integrity
- Use integer points.
- Use integer cents for money.
- Make ledger entries append-only at the application level.
- Add unique constraints for idempotency keys and any source reference that must only be processed once.
- Use database transactions and row locking or an equivalent safe concurrency strategy when awarding or redeeming points.
- Ensure the balance cannot become negative under concurrent redemption requests.
- Store timestamps in UTC and render them in the user's chosen timezone.
- Record the actor and a reason for manual adjustments and reversals.

Document how balances are computed and how reconciliation works.

---

## 6. API design

Create a versioned API such as `/api/v1`. Use consistent JSON responses, validation errors, pagination, and appropriate HTTP status codes.

Suggested endpoint groups:

- `/auth/*`
- `/businesses/*`
- `/members/*`
- `/locations/*`
- `/programs/*`
- `/customers/*`
- `/ledger/*`
- `/purchases/*`
- `/rewards/*`
- `/redemptions/*`
- `/referrals/*`
- `/analytics/*`
- `/exports/*`
- `/customer-portal/*`
- `/health`

Provide API documentation (OpenAPI if practical). Never expose internal stack traces, password hashes, invitation tokens, or secret configuration in responses.

---

## 7. UI and visual design requirements

Create a clean, modern, professional B2B interface.

### Visual rules
- **No gradients anywhere.**
- Use a restrained solid-color palette, generous whitespace, clear hierarchy, subtle borders, and limited shadows.
- Avoid excessive rounded pills and badge-like decoration.
- Avoid emoji in the production interface.
- Use SVG icons or a consistent icon library.
- Build responsive layouts for desktop, tablet, and mobile.
- Ensure visible keyboard focus, keyboard navigation, accessible form labels, semantic headings, and sufficient color contrast.
- Support reduced-motion preferences.
- Use WCAG 2.2 AA as a design target; do not claim full compliance without testing.

### Suggested design tokens

```scss
:root {
  --color-primary: #1769aa;
  --color-primary-hover: #12558b;
  --color-text: #182230;
  --color-text-muted: #667085;
  --color-surface: #ffffff;
  --color-page: #f6f8fb;
  --color-border: #dfe5ec;
  --color-success: #16794b;
  --color-warning: #946200;
  --color-danger: #b42318;

  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;

  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;

  --shadow-card: 0 1px 3px rgba(16, 24, 40, 0.08);
}
```

You may refine tokens for contrast and usability, but do not use gradients.

### Main screens
1. Sign in / sign up / password reset
2. Business onboarding
3. Dashboard
4. Customers list
5. Customer details and point ledger
6. Enroll customer
7. Record purchase / award points
8. Rewards catalog management
9. Redemption validation
10. Referrals
11. Analytics and exports
12. Locations
13. Staff and permissions
14. Loyalty program settings
15. Customer-facing loyalty page
16. Account and privacy settings

Use realistic sample data and useful empty states. Demo data must be clearly identified. Do not fill the interface with fake live integrations, misleading charts, or buttons that do nothing.

---

## 8. Security and privacy requirements

Treat customer contact details and loyalty balances as private data.

- Hash passwords with a modern password hashing algorithm through a trusted library.
- Use secure, HttpOnly, SameSite cookies for session authentication where applicable; enable Secure in production.
- Add CSRF protection where cookie-based state-changing requests require it.
- Apply rate limiting to authentication, invitations, referral endpoints, and sensitive operations.
- Validate all input server-side and use parameterized database access.
- Configure security headers and a restrictive Content Security Policy suitable for the application.
- Restrict CORS to explicitly configured origins.
- Avoid logging passwords, access tokens, invitation links, full customer contact details, or secrets.
- Use expiring, single-use tokens for password reset and invitations; store token hashes where practical.
- Add audit records for role changes, exports, point adjustments, redemptions, and sensitive settings.
- Use least-privilege authorization.
- Add retention/deletion procedures and a privacy notice template for merchant review.
- Do not claim compliance with CCPA, other privacy laws, PCI DSS, or any certification without qualified review.
- Marketing consent must be explicit, separately recorded, and revocable.
- Avoid collecting payment card data.

Add a concise `SECURITY.md` describing the threat model, sensitive data, secrets management, and known limitations.

---

## 9. Reliability and error handling

- Use database migrations from the beginning.
- Add a health endpoint that does not expose secrets.
- Provide consistent error responses and useful server-side logs.
- Use database transactions for all multi-step financial/points operations.
- Use idempotency keys for purchase awards, redemptions, and referral reward processing.
- Avoid duplicate notification sends; use an outbox/retry pattern if notifications are included.
- Provide clear user-facing messages for expired invitations, insufficient points, duplicate transactions, and unauthorized actions.
- Include seed/demo data that can be reset safely.
- Make development setup reproducible from documented commands.

---

## 10. Testing requirements

Create automated tests for at least the following:

### Authentication and authorization
- Unauthenticated users cannot access protected endpoints.
- Staff cannot perform owner-only operations.
- Cross-tenant access is denied for all major resource types.
- Invitation tokens expire and cannot be reused.

### Loyalty logic
- Purchase earns the correct number of points.
- Invalid or ineligible purchases earn no points.
- Duplicate requests do not award points twice.
- Redemption succeeds with sufficient points.
- Redemption fails with insufficient points.
- Concurrent redemptions cannot overdraw a balance.
- A reversal restores the appropriate points through a new ledger entry.
- Manual adjustments require an authorized actor and reason.
- Expiry, if implemented, is handled consistently.

### Referrals
- Valid qualified referrals award the configured reward.
- Self-referrals and duplicate rewards are rejected.
- Client input cannot bypass referral qualification rules.

### Frontend and end-to-end
- Main pages render without runtime errors.
- Forms show validation feedback.
- Core owner journey can be completed using demo data.
- Core staff purchase and redemption journey works.
- Customer portal cannot view another customer's data.

Do not claim tests pass unless you ran them. Report commands and actual results.

---

## 11. Seed data and demo experience

Provide a safe, clearly labelled demo experience with:
- One demo business.
- Two locations.
- Owner, manager, and staff demo users.
- At least 10 sample customers.
- Several rewards.
- Point ledger history.
- A few referrals in different states.
- Enough data for useful charts and filters.

Document demo credentials for local development only. Never ship a known demo password enabled in production. Add a production guard that prevents unsafe demo seeding or demo login unless explicitly enabled in a non-production environment.

---

## 12. Suggested implementation sequence

Work in small vertical slices and keep the application runnable after each phase.

### Phase 1 — inspect and scaffold
- Inspect repository.
- Confirm stack and commands.
- Create plan and task checklist.
- Set up frontend/backend, configuration, linting, and tests.
- Add `.env.example`, README, and migrations.

### Phase 2 — database and authentication
- Implement models and migrations.
- Implement sign-up/sign-in/sign-out and protected routes.
- Implement business membership and tenant authorization.
- Seed safe demo data.

### Phase 3 — loyalty core
- Implement program settings.
- Implement customer enrollment and search.
- Implement immutable point ledger.
- Implement purchase awarding with idempotency and transactions.
- Implement rewards and safe redemption.

### Phase 4 — referrals and staff workflows
- Implement referral attribution and qualification.
- Implement locations and staff roles.
- Implement audit logs.

### Phase 5 — dashboard and customer portal
- Implement analytics from real database queries.
- Implement customer-facing points/rewards/referrals view.
- Implement CSV exports and permission checks.

### Phase 6 — polish and verification
- Responsive SCSS and accessibility pass.
- Security and tenant-isolation tests.
- Run backend/frontend tests, lint, and build.
- Fix observed errors.
- Document local setup, deployment, backups, migrations, demo mode, and known limitations.

Do not skip core business logic to polish the dashboard.

---

## 13. Definition of done

The MVP is done only when:

- A new developer can run it using the README.
- Database migrations apply cleanly.
- Demo data can be seeded safely.
- The end-to-end owner and staff journeys work.
- Points cannot be duplicated or overdrawn under tested conditions.
- Redemptions and referrals are validated on the server.
- Tenant isolation is covered by automated tests.
- Main pages are responsive and keyboard-accessible.
- There are no knowingly broken primary actions or fake integrations.
- Tests and build have been run, and actual results are documented.
- `.env.example`, `README.md`, `SECURITY.md`, and `IMPLEMENTATION_PLAN.md` are present.
- Production secrets are not committed.

## 14. Final response after implementation

When finished, report:
1. What was implemented.
2. The actual tech stack detected/used.
3. Exact setup and run commands.
4. Environment variables and external services still required.
5. Tests, lint, and build commands that were run, with actual results.
6. Known limitations and security considerations.
7. The next three recommended tasks.

Start by inspecting the repository, then build the application. Do not stop after producing mockups or a plan.
