import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { CheckCircle2, UserPlus } from "lucide-react";
import { api, newIdempotencyKey } from "../api/client";
import { rememberedLocation, rememberLocation, useAccessibleLocations, useProgram, useRewards } from "../api/hooks";
import type { Customer, CustomerDetail, Envelope, Promotion, Redemption } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Alert, applyServerErrors, Avatar, Button, Card, Loading, PageHeader, Select, TextInput } from "../components/ui";
import { formatDate, formatMoney, formatNumber, promotionValue } from "../lib/format";
import { useCustomerSearch } from "./Customers";

/** Location picker bound to the device's remembered checkout location. */
export function useCheckoutLocation() {
  const locations = useAccessibleLocations();
  const [locationId, setLocationId] = useState<number | null>(rememberedLocation());
  useEffect(() => {
    if (locations.data.length && !locations.data.some((l) => l.id === locationId)) {
      setLocationId(locations.data[0].id);
    }
  }, [locations.data, locationId]);
  const select = (id: number) => {
    setLocationId(id);
    rememberLocation(id);
  };
  return { locations: locations.data, locationId, select, loading: locations.isLoading };
}

function LocationPicker({ value, options, onChange }: { value: number | null; options: { id: number; name: string }[]; onChange: (id: number) => void }) {
  return (
    <Select label="Location" value={value ?? ""} onChange={(e) => onChange(Number(e.target.value))}>
      {options.map((l) => (
        <option key={l.id} value={l.id}>
          {l.name}
        </option>
      ))}
    </Select>
  );
}

const moneyRe = /^\$?\d{1,7}(\.\d{1,2})?$/;
const purchaseSchema = z
  .object({
    amount: z.string().trim().regex(moneyRe, "Enter an amount like 12.50").refine((v) => Number(v.replace("$", "")) > 0, "Must be greater than zero"),
    eligible_amount: z.union([z.literal(""), z.string().trim().regex(moneyRe, "Enter an amount like 10.00")]),
    external_ref: z.string().trim().max(64),
  })
  .refine((v) => !v.eligible_amount || Number(v.eligible_amount.replace("$", "")) <= Number(v.amount.replace("$", "")), {
    message: "Cannot exceed the purchase total",
    path: ["eligible_amount"],
  });
type PurchaseValues = z.infer<typeof purchaseSchema>;

interface PurchaseResult {
  purchase: {
    points_awarded: number;
    amount_cents: number;
    external_ref: string | null;
    promotion_points: number;
    promotions_applied: { id: number; name: string; points: number }[];
  };
  duplicate: boolean;
  message: string;
  customer: Customer;
}

export function CheckoutPage() {
  const [params, setParams] = useSearchParams();
  const preselected = Number(params.get("customer")) || null;
  const { can } = useAuth();
  const qc = useQueryClient();
  const program = useProgram();
  const { locations, locationId, select, loading } = useCheckoutLocation();
  const [q, setQ] = useState("");
  const [customerId, setCustomerId] = useState<number | null>(preselected);
  const [result, setResult] = useState<PurchaseResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const idemKey = useRef(newIdempotencyKey());
  const search = useCustomerSearch(q, 1, "active", 8);
  const activePromos = useQuery({
    queryKey: ["promotions-active", locationId],
    queryFn: async () => (await api<Envelope<Promotion[]>>(`/promotions/active?location_id=${locationId}`)).data,
    enabled: !!locationId && can("promotions.view"),
  });
  const customer = useQuery({
    queryKey: ["customer", customerId],
    queryFn: async () => (await api<Envelope<CustomerDetail>>(`/customers/${customerId}`)).data,
    enabled: !!customerId,
  });
  const form = useForm<PurchaseValues>({
    resolver: zodResolver(purchaseSchema),
    defaultValues: { amount: "", eligible_amount: "", external_ref: "" },
  });

  function pick(id: number) {
    setCustomerId(id);
    setResult(null);
    setParams(id ? { customer: String(id) } : {}, { replace: true });
  }

  async function onSubmit(values: PurchaseValues) {
    if (!customerId || !locationId) return;
    setError(null);
    try {
      const res = await api<Envelope<PurchaseResult>>("/purchases", {
        method: "POST",
        idempotencyKey: idemKey.current,
        body: {
          customer_id: customerId,
          location_id: locationId,
          amount: values.amount.replace("$", ""),
          eligible_amount: values.eligible_amount ? values.eligible_amount.replace("$", "") : undefined,
          external_ref: values.external_ref || undefined,
        },
      });
      setResult(res.data);
      idemKey.current = newIdempotencyKey();
      form.reset();
      qc.invalidateQueries({ queryKey: ["customer", customerId] });
      qc.invalidateQueries({ queryKey: ["customer-ledger", customerId] });
      qc.invalidateQueries({ queryKey: ["customers"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }

  const errors = form.formState.errors;
  const p = program.data;
  const amountPreview = form.watch("amount");
  const eligiblePreview = form.watch("eligible_amount");
  const previewCents = Math.round(Number((eligiblePreview || amountPreview || "0").replace("$", "")) * 100) || 0;
  const basePoints =
    p && p.earning_enabled && p.status === "active" && previewCents >= p.min_spend_cents
      ? Math.floor((previewCents * p.points_per_dollar) / 100)
      : 0;
  const todaysPromos = (activePromos.data ?? []).filter((x) => previewCents >= x.min_spend_cents);
  const bestMultiplier = Math.max(100, ...todaysPromos.filter((x) => x.promo_type === "multiplier").map((x) => x.multiplier_percent ?? 100));
  const bonusTotal = todaysPromos.filter((x) => x.promo_type === "bonus").reduce((sum, x) => sum + (x.bonus_points ?? 0), 0);
  const previewPoints = basePoints ? basePoints + Math.floor((basePoints * (bestMultiplier - 100)) / 100) + bonusTotal : 0;

  if (loading) return <Loading />;
  if (!locations.length)
    return <Alert kind="warning">You are not assigned to any active location. Ask the owner to grant location access.</Alert>;

  return (
    <>
      <PageHeader
        title="Record purchase"
        description="Find the customer, enter the purchase total, and award points. No card data is collected."
        actions={
          can("customers.create") && (
            <Link className="btn" to="/customers/new">
              <UserPlus size={16} aria-hidden="true" /> Enroll new customer
            </Link>
          )
        }
      />
      <div className="grid grid-2">
        <Card title="1. Customer" bodyless>
          <div className="card-body" style={{ paddingBottom: 12 }}>
            <TextInput label="Find customer" type="search" placeholder="Name, email, phone or code" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {search.data && search.data.data.length === 0 && <p className="card-body muted small">No active customers match.</p>}
          <div role="list" aria-label="Matching customers">
            {search.data?.data.map((c) => (
              <div role="listitem" key={c.id}>
                <button type="button" className="customer-pick" aria-pressed={customerId === c.id} onClick={() => pick(c.id)}>
                  <span className="person">
                    <Avatar name={c.display_name} />
                    <span className="person-text">
                      <span className="person-name" style={{ display: "block" }}>
                        {c.display_name}
                      </span>
                      <span className="person-sub" style={{ display: "block" }}>
                        {c.email ?? c.phone}
                      </span>
                    </span>
                  </span>
                  <span className="small">{formatNumber(c.points_balance)} pts</span>
                </button>
              </div>
            ))}
          </div>
        </Card>

        <Card title="2. Purchase">
          <div className="form">
            <LocationPicker value={locationId} options={locations} onChange={select} />
            {!customerId ? (
              <p className="muted">Select a customer to continue.</p>
            ) : customer.isLoading ? (
              <Loading />
            ) : customer.data ? (
              <>
                <div className="result-panel row between">
                  <div>
                    <Link to={`/customers/${customer.data.id}`}>
                      <strong>{customer.data.display_name}</strong>
                    </Link>
                    <div className="muted small">{customer.data.email ?? customer.data.phone}</div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div className="stat-value" style={{ fontSize: 20 }}>{formatNumber(customer.data.points_balance)}</div>
                    <div className="muted small">points</div>
                  </div>
                </div>
                {customer.data.status !== "active" && <Alert kind="warning">This customer is {customer.data.status} and cannot earn points.</Alert>}
                <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
                  {error && <Alert kind="error">{error}</Alert>}
                  <TextInput label="Purchase total ($)" inputMode="decimal" className="input-lg" autoComplete="off" {...form.register("amount")} error={errors.amount?.message} />
                  <div className="grid grid-2">
                    <TextInput
                      label="Eligible amount (optional)"
                      inputMode="decimal"
                      hint="If part of the purchase doesn't earn points."
                      {...form.register("eligible_amount")}
                      error={errors.eligible_amount?.message}
                    />
                    <TextInput label="Receipt number (optional)" hint="Prevents recording the same receipt twice." {...form.register("external_ref")} error={errors.external_ref?.message} />
                  </div>
                  {(activePromos.data?.length ?? 0) > 0 && (
                    <Alert kind="info" title="Promotions today">
                      {activePromos.data!.map((x) => `${x.name} (${promotionValue(x)}${x.min_spend_cents ? ` on ${formatMoney(x.min_spend_cents)}+` : ""})`).join(" · ")}
                    </Alert>
                  )}
                  {p && (
                    <p className="small muted" aria-live="polite">
                      {p.earning_enabled && p.status === "active"
                        ? `Estimated: ${formatNumber(previewPoints)} points (${p.points_per_dollar} per $1${p.min_spend_cents ? `, minimum ${formatMoney(p.min_spend_cents)}` : ""}).`
                        : "Earning is turned off in program settings, so no points will be awarded."}
                    </p>
                  )}
                  <Button type="submit" variant="primary" block loading={form.formState.isSubmitting} disabled={customer.data.status !== "active"}>
                    Award points
                  </Button>
                </form>
              </>
            ) : null}
            {result && (
              <Alert kind={result.duplicate ? "warning" : "success"} title={result.duplicate ? "Already recorded" : "Purchase recorded"}>
                {result.message} New balance: <strong>{formatNumber(result.customer.points_balance)}</strong> points.
                {result.purchase.promotions_applied?.length > 0 && (
                  <span style={{ display: "block" }}>
                    Includes {result.purchase.promotions_applied.map((a) => `${a.name} (+${formatNumber(a.points)})`).join(", ")}.
                  </span>
                )}
              </Alert>
            )}
          </div>
        </Card>
      </div>
      {customer.data && customer.data.status === "active" && can("redemptions.issue") && (
        <div style={{ marginTop: 16 }}>
          <Card title="3. Redeem a reward (optional)">
            <RedeemForm customer={customer.data} onDone={() => qc.invalidateQueries({ queryKey: ["customer", customerId] })} />
          </Card>
        </div>
      )}
    </>
  );
}

/** Issue a redemption code for a customer and optionally complete it immediately at the counter. */
export function RedeemForm({ customer, onDone }: { customer: CustomerDetail | Customer; onDone: () => void }) {
  const { can, session } = useAuth();
  const rewards = useRewards("active");
  const program = useProgram();
  const { locations, locationId, select } = useCheckoutLocation();
  const [rewardId, setRewardId] = useState<number | null>(null);
  const [issued, setIssued] = useState<Redemption | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const idemKey = useRef(newIdempotencyKey());

  if (rewards.isLoading) return <Loading />;
  if (program.data && !program.data.redemption_enabled) return <Alert kind="info">Redemptions are turned off in program settings.</Alert>;
  const list = rewards.data ?? [];
  if (!list.length) return <p className="muted">No active rewards. Add rewards in the catalog first.</p>;

  async function issue() {
    if (!rewardId || !locationId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api<Envelope<Redemption>>("/redemptions", {
        method: "POST",
        idempotencyKey: idemKey.current,
        body: { customer_id: customer.id, reward_id: rewardId, location_id: locationId },
      });
      setIssued(res.data);
      idemKey.current = newIdempotencyKey();
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Redemption failed");
    } finally {
      setBusy(false);
    }
  }

  async function completeNow() {
    if (!issued || !locationId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api<Envelope<Redemption>>(`/redemptions/${issued.id}/complete`, { method: "POST", body: { location_id: locationId } });
      setIssued(res.data);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not complete");
    } finally {
      setBusy(false);
    }
  }

  if (issued) {
    return (
      <div className="stack">
        <div className="result-panel">
          <div className="muted small">Redemption code for {issued.reward.name}</div>
          <div className="code-display">{issued.code}</div>
          <div className="small muted">
            {issued.status === "redeemed" ? (
              <span className="text-success">
                <CheckCircle2 size={14} aria-hidden="true" style={{ verticalAlign: -2 }} /> Marked as used. Apply the reward manually at your register.
              </span>
            ) : (
              <>Valid until {formatDate(issued.expires_at, session?.user.timezone)}. {issued.points_cost} points deducted.</>
            )}
          </div>
        </div>
        {error && <Alert kind="error">{error}</Alert>}
        <div className="row">
          {issued.status === "issued" && can("redemptions.complete") && (
            <Button variant="primary" loading={busy} onClick={completeNow}>
              Mark as used now
            </Button>
          )}
          <Button onClick={() => setIssued(null)}>Redeem another</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="form">
      {error && <Alert kind="error">{error}</Alert>}
      <fieldset className="fieldset">
        <legend>Choose a reward · balance {formatNumber(customer.points_balance)} points</legend>
        {list.map((r) => {
          const affordable = customer.points_balance >= r.points_cost;
          const soldOut = r.stock_remaining !== null && r.stock_remaining <= 0;
          return (
            <label key={r.id} className="checkbox" style={{ opacity: affordable && !soldOut ? 1 : 0.6 }}>
              <input
                type="radio"
                name="reward"
                value={r.id}
                disabled={!affordable || soldOut}
                checked={rewardId === r.id}
                onChange={() => setRewardId(r.id)}
              />
              <span>
                <strong>{r.name}</strong> — {formatNumber(r.points_cost)} points
                <span className="hint" style={{ display: "block" }}>
                  {soldOut ? "Out of stock" : !affordable ? `Needs ${formatNumber(r.points_cost - customer.points_balance)} more points` : r.terms}
                </span>
              </span>
            </label>
          );
        })}
      </fieldset>
      <LocationPicker value={locationId} options={locations} onChange={select} />
      <p className="muted small">
        Points are deducted when the code is issued. This app does not connect to your payment terminal — apply the discount or item
        at your register.
      </p>
      <div className="form-actions">
        <Button variant="primary" disabled={!rewardId} loading={busy} onClick={issue}>
          Issue redemption code
        </Button>
      </div>
    </div>
  );
}
