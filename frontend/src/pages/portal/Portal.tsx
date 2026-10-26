import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Copy } from "lucide-react";
import { api, ApiError, newIdempotencyKey, setPortalCsrfToken } from "../../api/client";
import type { Envelope, LedgerEntry, Promotion, Redemption, Reward } from "../../api/types";
import { BirthdayFields, birthdayPayload } from "../../components/BirthdayFields";
import { Alert, applyServerErrors, Button, Card, Checkbox, Loading, Status, TextInput } from "../../components/ui";
import { ENTRY_LABELS, formatDate, formatMoney, formatNumber, formatPoints, MONTHS, promotionSchedule, promotionValue } from "../../lib/format";

interface PublicProgram {
  business_name: string;
  slug: string;
  name: string;
  description: string;
  status: string;
  brand_color: string;
  logo_url: string;
  contact_email: string;
  contact_phone: string;
  rules: string[];
  referrals_enabled: boolean;
  is_demo: boolean;
  rewards?: { name: string; points_cost: number; description: string }[];
  redemption_enabled?: boolean;
}

interface PortalData {
  csrf_token: string;
  customer: {
    display_name: string;
    email: string | null;
    points_balance: number;
    enrolled_at: string;
    marketing_opt_in: boolean;
    referral_code: string;
    referral_url: string | null;
    birth_month: number | null;
    birth_day: number | null;
  };
  promotions: Promotion[];
  program: PublicProgram;
  rewards: Reward[];
  ledger: Omit<LedgerEntry, "actor" | "customer_id" | "source_id">[];
  redemptions: Redemption[];
}

function PortalShell({ program, children }: { program?: PublicProgram; children: ReactNode }) {
  return (
    <div className="portal" style={{ "--brand": program?.brand_color } as CSSProperties}>
      <header className="portal-header">
        <div className="portal-header-inner">
          <span className="portal-logo" aria-hidden="true">
            {program?.logo_url ? <img src={program.logo_url} alt="" /> : (program?.business_name ?? "R").trim().charAt(0).toUpperCase()}
          </span>
          <div>
            <h1>{program ? program.name : "Rewards"}</h1>
            {program && <p>{program.business_name}</p>}
            {program?.is_demo && <p>Demo program — sample data only.</p>}
          </div>
        </div>
      </header>
      <main className="portal-body">{children}</main>
    </div>
  );
}

function usePublicProgram(slug: string) {
  return useQuery({
    queryKey: ["public-program", slug],
    queryFn: async () => (await api<Envelope<PublicProgram>>(`/public/programs/${slug}`)).data,
    retry: false,
  });
}

// --------------------------------------------------------- request a link

export function PortalRequestPage() {
  const { slug = "" } = useParams();
  const program = usePublicProgram(slug);
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<{ email: string }>({ resolver: zodResolver(z.object({ email: z.string().trim().email("Enter a valid email") })) });

  async function onSubmit(values: { email: string }) {
    setError(null);
    try {
      const res = await api<Envelope<{ message: string }>>("/customer-portal/request-link", {
        method: "POST",
        body: { business_slug: slug, email: values.email },
      });
      setSent(res.data.message);
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }

  if (program.isLoading) return <Loading />;
  if (program.error) return <PortalShell><Alert kind="error">This rewards program could not be found.</Alert></PortalShell>;
  return (
    <PortalShell program={program.data}>
      <Card title="Sign in to your rewards">
        {sent ? (
          <Alert kind="success">{sent}</Alert>
        ) : (
          <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
            <p className="muted">We'll email you a secure link. No password needed.</p>
            {error && <Alert kind="error">{error}</Alert>}
            <TextInput label="Email" type="email" autoComplete="email" {...form.register("email")} error={form.formState.errors.email?.message} />
            <Button type="submit" variant="primary" block loading={form.formState.isSubmitting}>
              Email me a sign-in link
            </Button>
            <p className="small">
              Not a member? <Link to={`/join/${slug}`}>Join the program</Link>
            </p>
          </form>
        )}
      </Card>
    </PortalShell>
  );
}

// --------------------------------------------------------- exchange token

export function PortalAccessPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return; // single-use token: exchange once
    started.current = true;
    const token = params.get("token") ?? "";
    // Remove the token from the address bar/history as soon as it is read.
    window.history.replaceState(null, "", "/portal/access");
    api<Envelope<{ csrf_token: string; business_slug: string }>>("/customer-portal/session", { method: "POST", body: { token } })
      .then((res) => {
        setPortalCsrfToken(res.data.csrf_token);
        navigate("/portal/me", { replace: true });
      })
      .catch((err) => setError(err instanceof Error ? err.message : "This link is not valid."));
  }, [params, navigate]);

  return (
    <PortalShell>
      {error ? (
        <Alert kind="error" title="Link not valid">
          {error}
        </Alert>
      ) : (
        <Loading label="Signing you in…" />
      )}
    </PortalShell>
  );
}

// --------------------------------------------------------------- home

export function PortalHomePage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [notice, setNotice] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [busyReward, setBusyReward] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const [showQr, setShowQr] = useState(false);
  const query = useQuery({
    queryKey: ["portal-me"],
    queryFn: async () => {
      const res = await api<Envelope<PortalData>>("/customer-portal/me");
      setPortalCsrfToken(res.data.csrf_token);
      return res.data;
    },
    retry: false,
  });

  if (query.isLoading) return <Loading />;
  if (query.error) {
    const unauth = query.error instanceof ApiError && query.error.status === 401;
    return (
      <PortalShell>
        <Alert kind={unauth ? "info" : "error"} title={unauth ? "Please sign in" : "Something went wrong"}>
          {unauth ? "Use the sign-in link from your email, or request a new one from the business's rewards page." : (query.error as Error).message}
        </Alert>
      </PortalShell>
    );
  }
  const d = query.data!;
  const unused = d.redemptions.filter((r) => r.status === "issued");

  async function redeem(reward: Reward) {
    setBusyReward(reward.id);
    setNotice(null);
    try {
      await api("/customer-portal/redemptions", { method: "POST", portal: true, body: { reward_id: reward.id }, idempotencyKey: newIdempotencyKey() });
      setNotice({ kind: "success", text: `Code created for ${reward.name}. Show it to staff at checkout.` });
      qc.invalidateQueries({ queryKey: ["portal-me"] });
    } catch (err) {
      setNotice({ kind: "error", text: (err as Error).message });
    } finally {
      setBusyReward(null);
    }
  }

  async function setConsent(value: boolean) {
    try {
      await api("/customer-portal/consent", { method: "PATCH", portal: true, body: { marketing_opt_in: value } });
      qc.invalidateQueries({ queryKey: ["portal-me"] });
    } catch (err) {
      setNotice({ kind: "error", text: (err as Error).message });
    }
  }

  async function copyLink() {
    if (!d.customer.referral_url) return;
    try {
      await navigator.clipboard.writeText(d.customer.referral_url);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  async function signOut() {
    await api("/customer-portal/signout", { method: "POST", portal: true }).catch(() => undefined);
    setPortalCsrfToken(null);
    navigate(`/portal/${d.program.slug}`);
  }

  return (
    <PortalShell program={d.program}>
      <Card>
        <p className="muted">Hi {d.customer.display_name.split(" ")[0]}, you have</p>
        <div className="portal-balance" style={{ marginTop: 6 }}>
          {formatNumber(d.customer.points_balance)} <span className="muted" style={{ fontSize: 18, fontWeight: 500, letterSpacing: 0 }}>points</span>
        </div>
        {(() => {
          const sorted = [...d.rewards].sort((a, b) => a.points_cost - b.points_cost);
          const next = sorted.find((r) => r.points_cost > d.customer.points_balance);
          if (!next) return sorted.length ? <p className="small text-success" style={{ marginTop: 12 }}>You can redeem any reward. Treat yourself!</p> : null;
          const pct = Math.min(100, Math.round((d.customer.points_balance / next.points_cost) * 100));
          return (
            <>
              <div className="progress" role="progressbar" aria-valuenow={d.customer.points_balance} aria-valuemin={0} aria-valuemax={next.points_cost} aria-label={`Progress to ${next.name}`} style={{ marginTop: 16 }}>
                <span style={{ width: `${pct}%`, background: "var(--brand, var(--color-primary))" }} />
              </div>
              <p className="small muted" style={{ marginTop: 8 }}>
                {formatNumber(next.points_cost - d.customer.points_balance)} more points for <strong style={{ color: "var(--color-text)" }}>{next.name}</strong>
              </p>
            </>
          );
        })()}
        <p className="muted small" style={{ marginTop: 12 }}>Member since {formatDate(d.customer.enrolled_at)}</p>
      </Card>
      {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}

      {unused.length > 0 && (
        <Card title="Your reward codes">
          <ul className="list-plain" style={{ margin: "-20px" }}>
            {unused.map((r) => (
              <li key={r.id}>
                <div className="code-display">{r.code}</div>
                <div className="small">
                  {r.reward.name} · valid until {formatDate(r.expires_at)}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {d.promotions.length > 0 && (
        <Card title="Current promotions">
          <ul className="list-plain" style={{ margin: "-20px" }}>
            {d.promotions.map((p) => (
              <li key={p.id}>
                <strong>{p.name}</strong> — {promotionValue(p)}
                {p.min_spend_cents > 0 && ` on purchases of ${formatMoney(p.min_spend_cents)} or more`}
                <div className="muted small">
                  {p.description ? `${p.description} · ` : ""}
                  {promotionSchedule(p)}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Rewards">
        {d.rewards.length === 0 ? (
          <p className="muted">No rewards available right now.</p>
        ) : (
          <ul className="list-plain" style={{ margin: "-20px" }}>
            {d.rewards.map((r) => {
              const short = r.points_cost - d.customer.points_balance;
              const soldOut = r.stock_remaining !== null && r.stock_remaining <= 0;
              return (
                <li key={r.id} className="row between">
                  <div>
                    <strong>{r.name}</strong>
                    <div className="muted small">
                      {formatNumber(r.points_cost)} points{r.terms ? ` · ${r.terms}` : ""}
                    </div>
                  </div>
                  {d.program.redemption_enabled && (
                    soldOut ? (
                      <span className="muted small">Out of stock</span>
                    ) : short > 0 ? (
                      <span className="muted small">{formatNumber(short)} more points</span>
                    ) : (
                      <Button size="sm" variant="primary" loading={busyReward === r.id} onClick={() => redeem(r)}>
                        Redeem
                      </Button>
                    )
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {d.customer.referral_url && (
        <Card title="Refer a friend">
          <p className="small" style={{ marginBottom: 12 }}>
            {d.program.rules.find((r) => r.startsWith("Refer a friend")) ?? "Share your link with friends."}
          </p>
          <div className="row">
            <input className="input" readOnly value={d.customer.referral_url} aria-label="Your referral link" style={{ flex: 1, minWidth: 0 }} />
            <Button onClick={copyLink}>
              <Copy size={14} aria-hidden="true" /> {copied ? "Copied" : "Copy"}
            </Button>
          </div>
          <div className="row between" style={{ marginTop: 8 }}>
            <p className="muted small">
              Your code: <span className="mono">{d.customer.referral_code}</span>
            </p>
            <Button size="sm" variant="ghost" aria-expanded={showQr} onClick={() => setShowQr((v) => !v)}>
              {showQr ? "Hide QR code" : "Show QR code"}
            </Button>
          </div>
          {showQr && (
            <img
              src="/api/v1/customer-portal/referral-qr.svg"
              alt="QR code of your referral link for a friend to scan"
              width={200}
              height={200}
              style={{ display: "block", margin: "8px auto 0" }}
            />
          )}
        </Card>
      )}

      <Card title="How it works">
        <ul className="rules">
          {d.program.rules.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      </Card>

      <Card title="History" bodyless>
        {d.ledger.length === 0 ? (
          <p className="card-body muted">No activity yet.</p>
        ) : (
          <ul className="list-plain">
            {d.ledger.map((e) => (
              <li key={e.id} className="row between">
                <div>
                  {ENTRY_LABELS[e.entry_type]}
                  <div className="muted small">
                    {formatDate(e.created_at)} · {e.reason}
                  </div>
                </div>
                <strong className={e.points > 0 ? "text-success" : ""}>{formatPoints(e.points, true)}</strong>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <BirthdayCard current={d.customer} onSaved={() => qc.invalidateQueries({ queryKey: ["portal-me"] })} />

      <Card title="Communication preferences">
        <Checkbox
          label="Send me offers and news by email"
          hint="Optional. You'll still receive essential messages about your account, such as sign-in links."
          checked={d.customer.marketing_opt_in}
          onChange={(e) => setConsent(e.target.checked)}
        />
      </Card>

      <div className="row between small">
        <span className="muted">
          Questions? {d.program.contact_email && <a href={`mailto:${d.program.contact_email}`}>{d.program.contact_email}</a>}
        </span>
        <Button size="sm" variant="ghost" onClick={signOut}>
          Sign out
        </Button>
      </div>
      {redemptionStatusLegend(d.redemptions)}
    </PortalShell>
  );
}

function redemptionStatusLegend(redemptions: Redemption[]) {
  const past = redemptions.filter((r) => r.status !== "issued").slice(0, 5);
  if (!past.length) return null;
  return (
    <Card title="Past redemptions">
      <ul className="list-plain" style={{ margin: "-20px" }}>
        {past.map((r) => (
          <li key={r.id} className="row between small">
            <span>
              {r.reward.name} · {formatDate(r.created_at)}
            </span>
            <Status value={r.status} />
          </li>
        ))}
      </ul>
    </Card>
  );
}

// ----------------------------------------------------------------- join

const joinSchema = z.object({
  display_name: z.string().trim().min(1, "Required").max(120),
  email: z.string().trim().email("Enter a valid email"),
  marketing_opt_in: z.boolean(),
  birth_month: z.string(),
  birth_day: z.string(),
});

export function JoinPage() {
  const { slug = "" } = useParams();
  const [params] = useSearchParams();
  const ref = params.get("ref") ?? "";
  const program = usePublicProgram(slug);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof joinSchema>>({
    resolver: zodResolver(joinSchema),
    defaultValues: { marketing_opt_in: false, birth_month: "", birth_day: "" },
  });

  async function onSubmit(values: z.infer<typeof joinSchema>) {
    setError(null);
    try {
      const res = await api<Envelope<{ message: string }>>(`/public/programs/${slug}/join`, {
        method: "POST",
        body: {
          display_name: values.display_name,
          email: values.email,
          marketing_opt_in: values.marketing_opt_in,
          ...birthdayPayload(values.birth_month, values.birth_day),
          ref: ref || undefined,
        },
      });
      setDone(res.data.message);
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }

  if (program.isLoading) return <Loading />;
  if (program.error) return <PortalShell><Alert kind="error">This rewards program could not be found.</Alert></PortalShell>;
  const p = program.data!;
  return (
    <PortalShell program={p}>
      <Card title={`Join ${p.name}`}>
        {done ? (
          <Alert kind="success" title="Almost there">
            {done}
          </Alert>
        ) : p.status !== "active" ? (
          <Alert kind="info">This program isn't accepting new members right now.</Alert>
        ) : (
          <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
            {p.description && <p>{p.description}</p>}
            {ref && p.referrals_enabled && <Alert kind="info">You were referred by a friend. You'll both earn a bonus after your first qualifying purchase.</Alert>}
            {error && <Alert kind="error">{error}</Alert>}
            <TextInput label="Your name" autoComplete="name" {...form.register("display_name")} error={form.formState.errors.display_name?.message} />
            <TextInput label="Email" type="email" autoComplete="email" {...form.register("email")} error={form.formState.errors.email?.message} />
            <BirthdayFields
              month={form.watch("birth_month")}
              day={form.watch("birth_day")}
              onChange={(m, d) => {
                form.setValue("birth_month", m);
                form.setValue("birth_day", d);
              }}
              hint="Optional. Get a treat on your birthday — we don't ask for the year."
            />
            <Checkbox
              label="Send me offers and news by email (optional)"
              hint="You can join without this. You can change it any time."
              {...form.register("marketing_opt_in")}
            />
            <Button type="submit" variant="primary" block loading={form.formState.isSubmitting}>
              Join and get my link
            </Button>
            <p className="small">
              Already a member? <Link to={`/portal/${slug}`}>Sign in</Link>
            </p>
          </form>
        )}
      </Card>
      <Card title="How it works">
        <ul className="rules">
          {p.rules.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
        {p.rewards && p.rewards.length > 0 && (
          <>
            <h3 style={{ marginTop: 16, marginBottom: 8 }}>Rewards</h3>
            <ul className="rules">
              {p.rewards.map((r) => (
                <li key={r.name}>
                  {r.name} — {formatNumber(r.points_cost)} points
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>
    </PortalShell>
  );
}

function BirthdayCard({
  current,
  onSaved,
}: {
  current: { birth_month: number | null; birth_day: number | null };
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [month, setMonth] = useState(current.birth_month ? String(current.birth_month) : "");
  const [day, setDay] = useState(current.birth_day ? String(current.birth_day) : "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api("/customer-portal/profile", { method: "PATCH", portal: true, body: birthdayPayload(month, day) });
      setEditing(false);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Your birthday">
      {editing ? (
        <div className="stack">
          <BirthdayFields month={month} day={day} onChange={(m, d) => { setMonth(m); setDay(d); }} />
          {error && <Alert kind="error">{error}</Alert>}
          <div className="row">
            <Button variant="primary" size="sm" loading={busy} onClick={save}>
              Save
            </Button>
            <Button size="sm" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="row between">
          <span>{current.birth_month && current.birth_day ? `${MONTHS[current.birth_month - 1]} ${current.birth_day}` : "Not set"}</span>
          <Button size="sm" onClick={() => setEditing(true)}>
            {current.birth_month ? "Change" : "Add birthday"}
          </Button>
        </div>
      )}
    </Card>
  );
}
