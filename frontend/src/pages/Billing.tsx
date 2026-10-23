import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { api } from "../api/client";
import type { BillingSummary, Envelope } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Alert, Button, Card, ErrorMessage, Loading, PageHeader } from "../components/ui";
import { formatDate, formatMoney, formatNumber } from "../lib/format";

type Limits = { locations: number | null; customers: number | null; members: number | null };

interface Overview extends BillingSummary {
  provider: "dev" | "stripe" | "none";
  has_billing_account: boolean;
  limits: Limits;
  usage: { locations: number; customers: number; members: number };
  trial_days: number;
  plans: { id: string; name: string; price_cents: number; description: string; limits: Limits }[];
}

const RESOURCE_LABELS: Record<keyof Limits, string> = {
  customers: "Customers",
  locations: "Active locations",
  members: "Team members (incl. pending invites)",
};

const STATUS_TEXT: Record<BillingSummary["status"], string> = {
  trialing: "Free trial",
  active: "Active",
  past_due: "Payment overdue",
  canceled: "Cancelled",
  trial_expired: "Trial ended",
};

function UsageBar({ used, limit }: { used: number; limit: number | null }) {
  const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  const color = pct >= 100 ? "var(--color-danger)" : pct >= 80 ? "var(--color-warning)" : "var(--color-primary)";
  return (
    <div>
      <div className="row between small">
        <span>
          {formatNumber(used)} of {limit === null ? "unlimited" : formatNumber(limit)}
        </span>
        {limit !== null && <span className="muted">{pct}%</span>}
      </div>
      {limit !== null && (
        <div
          role="progressbar"
          aria-valuenow={used}
          aria-valuemin={0}
          aria-valuemax={limit}
          style={{ height: 8, background: "var(--color-border)", borderRadius: 4, marginTop: 4, overflow: "hidden" }}
        >
          <div style={{ width: `${pct}%`, height: "100%", background: color }} />
        </div>
      )}
    </div>
  );
}

export function BillingPage() {
  const { session, refresh } = useAuth();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["billing"],
    queryFn: async () => (await api<Envelope<Overview>>("/billing")).data,
  });
  const tz = session?.user.timezone;

  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorMessage error={query.error} />;
  const b = query.data!;

  async function choose(plan: string) {
    setBusy(plan);
    setError(null);
    try {
      if (b.provider === "stripe") {
        const res = await api<Envelope<{ url: string }>>("/billing/checkout", { method: "POST", body: { plan } });
        window.location.assign(res.data.url);
        return;
      }
      await api("/billing/dev/switch", { method: "POST", body: { plan } });
      await qc.invalidateQueries({ queryKey: ["billing"] });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change plan");
    } finally {
      setBusy(null);
    }
  }

  async function openPortal() {
    setBusy("portal");
    setError(null);
    try {
      const res = await api<Envelope<{ url: string }>>("/billing/portal", { method: "POST" });
      window.location.assign(res.data.url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open billing portal");
      setBusy(null);
    }
  }

  const checkout = params.get("checkout");

  return (
    <>
      <PageHeader
        title="Billing"
        description="Your plan, usage and payment details."
        actions={
          b.provider === "stripe" &&
          b.has_billing_account && (
            <Button loading={busy === "portal"} onClick={openPortal}>
              Manage payment & invoices
            </Button>
          )
        }
      />
      <div className="stack" style={{ marginBottom: 16 }}>
        {checkout === "success" && (
          <Alert kind="success">Thanks! Your subscription is being activated. This page updates once payment is confirmed.</Alert>
        )}
        {checkout === "cancelled" && <Alert kind="info">Checkout was cancelled. No charge was made.</Alert>}
        {b.provider === "dev" && (
          <Alert kind="warning" title="Simulated billing">
            Payments are not connected in this environment. Choosing a plan switches it immediately without charging. Set
            BILLING_PROVIDER=stripe to take real payments.
          </Alert>
        )}
        {error && <Alert kind="error">{error}</Alert>}
      </div>

      <div className="grid grid-2">
        <Card title="Current plan">
          <p style={{ fontSize: 20, fontWeight: 600 }}>{b.plan_name}</p>
          <p className="muted">
            {STATUS_TEXT[b.status]}
            {b.status === "trialing" && b.trial_ends_at && ` · ends ${formatDate(b.trial_ends_at, tz)}`}
            {b.status === "active" && b.current_period_end && ` · renews ${formatDate(b.current_period_end, tz)}`}
          </p>
          {!b.in_good_standing && (
            <div style={{ marginTop: 12 }}>
              <Alert kind="error">
                Your account is read-only: you can view data and handle privacy requests, but not record purchases, enroll
                customers or issue rewards until you choose a plan.
              </Alert>
            </div>
          )}
        </Card>
        <Card title="Usage">
          <div className="stack">
            {(Object.keys(RESOURCE_LABELS) as (keyof Limits)[]).map((k) => (
              <div key={k}>
                <div className="small" style={{ fontWeight: 500, marginBottom: 2 }}>
                  {RESOURCE_LABELS[k]}
                </div>
                <UsageBar used={b.usage[k]} limit={b.limits[k]} />
              </div>
            ))}
          </div>
        </Card>
      </div>

      <h2 style={{ margin: "24px 0 12px" }}>Plans</h2>
      <div className="grid grid-3">
        {b.plans.map((p) => {
          const current = b.plan === p.id && b.status !== "canceled";
          return (
            <section key={p.id} className="card" aria-label={`${p.name} plan`} style={current ? { borderColor: "var(--color-primary)", borderWidth: 2 } : undefined}>
              <div className="card-body stack">
                <div>
                  <h3 style={{ fontSize: 18 }}>{p.name}</h3>
                  <p className="muted small">{p.description}</p>
                </div>
                <p>
                  <span style={{ fontSize: 28, fontWeight: 700 }}>{formatMoney(p.price_cents)}</span>
                  <span className="muted"> / month</span>
                </p>
                <ul className="small" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                  {(Object.keys(RESOURCE_LABELS) as (keyof Limits)[]).map((k) => (
                    <li key={k} className="row" style={{ marginBottom: 4 }}>
                      <Check size={14} className="text-success" aria-hidden="true" />
                      {p.limits[k] === null ? "Unlimited" : formatNumber(p.limits[k])} {k === "members" ? "team members" : k}
                    </li>
                  ))}
                </ul>
                {current ? (
                  <Button disabled block>
                    Current plan
                  </Button>
                ) : b.provider === "none" ? (
                  <p className="muted small">Contact us to change plans.</p>
                ) : (
                  <Button variant="primary" block loading={busy === p.id} onClick={() => choose(p.id)}>
                    {b.provider === "dev" ? `Switch to ${p.name} (simulated)` : `Choose ${p.name}`}
                  </Button>
                )}
              </div>
            </section>
          );
        })}
      </div>
      <p className="muted small" style={{ marginTop: 16 }}>
        Prices in USD, excluding applicable taxes. New businesses get a {b.trial_days}-day free trial with Growth limits.
      </p>
    </>
  );
}
