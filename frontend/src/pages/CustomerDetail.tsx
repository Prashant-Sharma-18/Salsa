import { useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Download, Gift, Mail, MinusCircle, ShoppingBag, Trash2, Undo2 } from "lucide-react";
import { api, ApiError, qs } from "../api/client";
import { useLocations, useRewards } from "../api/hooks";
import type { CustomerDetail, Envelope, LedgerEntry, Paged, Redemption } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { RedeemForm } from "./Checkout";
import {
  Alert,
  applyServerErrors,
  Avatar,
  Button,
  Card,
  Checkbox,
  ErrorMessage,
  Loading,
  Modal,
  PageHeader,
  Pagination,
  Status,
  TextInput,
} from "../components/ui";
import { ENTRY_LABELS, formatDate, formatDateTime, formatNumber, formatPoints, MONTHS, REFERRAL_LABELS } from "../lib/format";
import { BirthdayFields, birthdayPayload } from "../components/BirthdayFields";

export function CustomerDetailPage() {
  const { id } = useParams();
  const customerId = Number(id);
  const { can, session } = useAuth();
  const tz = session?.user.timezone;
  const qc = useQueryClient();
  const location = useLocation();
  const flash = location.state as { enrolled?: boolean; referral?: { status: string; rejection_reason: string | null } | null } | null;
  const [ledgerPage, setLedgerPage] = useState(1);
  const [modal, setModal] = useState<null | "adjust" | "reverse" | "redeem" | "edit" | "anonymize" | "cancel">(null);
  const [reverseEntry, setReverseEntry] = useState<LedgerEntry | null>(null);
  const [cancelTarget, setCancelTarget] = useState<Redemption | null>(null);
  const [notice, setNotice] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const locations = useLocations();
  const locationName = (lid: number | null) => locations.data?.find((l) => l.id === lid)?.name ?? "—";

  const detail = useQuery({
    queryKey: ["customer", customerId],
    queryFn: async () => (await api<Envelope<CustomerDetail>>(`/customers/${customerId}`)).data,
  });
  const ledger = useQuery({
    queryKey: ["customer-ledger", customerId, ledgerPage],
    queryFn: () => api<Paged<LedgerEntry>>(`/customers/${customerId}/ledger${qs({ page: ledgerPage, page_size: 15 })}`),
  });

  function invalidate() {
    qc.invalidateQueries({ queryKey: ["customer", customerId] });
    qc.invalidateQueries({ queryKey: ["customer-ledger", customerId] });
    qc.invalidateQueries({ queryKey: ["customers"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  }

  const portalLink = useMutation({
    mutationFn: () => api(`/customers/${customerId}/portal-link`, { method: "POST" }),
    onSuccess: () => setNotice({ kind: "success", text: "A secure sign-in link was emailed to the customer (valid 24 hours)." }),
    onError: (err: Error) => setNotice({ kind: "error", text: err.message }),
  });
  const consent = useMutation({
    mutationFn: (granted: boolean) => api(`/customers/${customerId}/consent`, { method: "POST", body: { marketing_opt_in: granted } }),
    onSuccess: invalidate,
    onError: (err: Error) => setNotice({ kind: "error", text: err.message }),
  });

  async function exportData() {
    try {
      const res = await api<Envelope<unknown>>(`/customers/${customerId}/privacy-export`);
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `customer-${customerId}-data.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setNotice({ kind: "error", text: (err as Error).message });
    }
  }

  if (detail.isLoading) return <Loading />;
  if (detail.error) return <ErrorMessage error={detail.error} />;
  const c = detail.data!;
  const anonymized = c.status === "anonymized";

  return (
    <>
      <PageHeader
        leading={<Avatar name={c.display_name} size="lg" />}
        title={c.display_name}
        description={
          <>
            <Status value={c.status} /> · Enrolled {formatDate(c.enrolled_at, tz)}
            {c.is_demo && <span className="tag" style={{ marginLeft: 8 }}>Demo data</span>}
          </>
        }
        actions={
          !anonymized && (
            <>
              {can("purchases.create") && c.status === "active" && (
                <Link className="btn btn-primary" to={`/checkout?customer=${c.id}`}>
                  <ShoppingBag size={16} aria-hidden="true" /> Record purchase
                </Link>
              )}
              {can("redemptions.issue") && c.status === "active" && (
                <Button onClick={() => setModal("redeem")}>
                  <Gift size={16} aria-hidden="true" /> Redeem reward
                </Button>
              )}
            </>
          )
        }
      />
      <div className="stack" style={{ marginBottom: 16 }}>
        {flash?.enrolled && <Alert kind="success">Customer enrolled.</Alert>}
        {flash?.referral?.status === "signed_up" && (
          <Alert kind="info">Referral recorded. The referrer is rewarded after this customer's first qualifying purchase.</Alert>
        )}
        {flash?.referral?.status === "rejected" && (
          <Alert kind="warning">Referral not accepted: {flash.referral.rejection_reason}</Alert>
        )}
        {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}
      </div>

      <div className="grid grid-sidebar">
        <div className="stack">
          <div className="grid grid-2">
            <div className="highlight-card">
              <div className="highlight-label">Points balance</div>
              <div className="highlight-value">{formatNumber(c.points_balance)}</div>
              <NextReward balance={c.points_balance} />
            </div>
            <div className="card stat" style={{ display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <div>
                <div className="stat-label">Referral code</div>
                <div className="stat-value mono" style={{ fontSize: 22, letterSpacing: "0.08em" }}>
                  {c.referral_code}
                </div>
              </div>
              <div className="stat-hint">Last activity {formatDate(c.last_activity_at, tz)}</div>
            </div>
          </div>

          <Card
            title="Points ledger"
            bodyless
            actions={
              can("ledger.adjust") &&
              !anonymized && (
                <Button size="sm" onClick={() => setModal("adjust")}>
                  <MinusCircle size={14} aria-hidden="true" /> Adjust points
                </Button>
              )
            }
          >
            {ledger.isLoading ? (
              <Loading />
            ) : ledger.data?.data.length === 0 ? (
              <p className="card-body muted">No ledger entries yet. Points appear here when a purchase is recorded.</p>
            ) : (
              <>
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Activity</th>
                        <th className="num">Points</th>
                        <th className="num">Balance</th>
                        {can("ledger.reverse") && <th><span className="visually-hidden">Actions</span></th>}
                      </tr>
                    </thead>
                    <tbody>
                      {ledger.data?.data.map((e) => (
                        <tr key={e.id}>
                          <td className="ledger-activity">
                            <div className="ledger-title">{ENTRY_LABELS[e.entry_type]}</div>
                            <div className="ledger-reason small">{e.reason}</div>
                            <div className="ledger-meta">
                              {formatDateTime(e.created_at, tz)} · {e.actor ? e.actor : "System"}
                              {e.location_id ? ` · ${locationName(e.location_id)}` : ""}
                              {e.reversed ? " · Reversed" : ""}
                            </div>
                          </td>
                          <td className={`num ${e.points > 0 ? "points-pos" : "points-neg"}`}>{formatPoints(e.points, true)}</td>
                          <td className="num">{formatNumber(e.balance_after)}</td>
                          {can("ledger.reverse") && (
                            <td className="num">
                              {!e.reversed && !anonymized && ["award", "adjustment", "referral_bonus", "expiration"].includes(e.entry_type) && (
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => {
                                    setReverseEntry(e);
                                    setModal("reverse");
                                  }}
                                  aria-label={`Reverse entry from ${formatDateTime(e.created_at, tz)}`}
                                >
                                  <Undo2 size={14} aria-hidden="true" /> Reverse
                                </Button>
                              )}
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {ledger.data && (
                  <Pagination page={ledger.data.meta.page} pages={ledger.data.meta.pages} total={ledger.data.meta.total} onPage={setLedgerPage} />
                )}
              </>
            )}
          </Card>

          {c.open_redemptions.length > 0 && (
            <Card title="Unused reward codes" bodyless>
              <ul className="list-plain">
                {c.open_redemptions.map((r) => (
                  <li key={r.id} className="row between">
                    <div>
                      <strong>{r.reward.name}</strong> · <span className="mono">{r.code}</span>
                      <div className="muted small">
                        {formatNumber(r.points_cost)} points · expires {formatDate(r.expires_at, tz)}
                      </div>
                    </div>
                    {can("redemptions.cancel") && (
                      <Button
                        size="sm"
                        onClick={() => {
                          setCancelTarget(r);
                          setModal("cancel");
                        }}
                      >
                        Cancel and refund
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>

        <div className="stack">
          <Card
            title="Profile"
            actions={can("customers.edit") && !anonymized && <Button size="sm" onClick={() => setModal("edit")}>Edit</Button>}
          >
            <dl className="dl">
              <dt>Email</dt>
              <dd>{c.email ?? "—"}</dd>
              <dt>Phone</dt>
              <dd>{c.phone ?? "—"}</dd>
              <dt>Birthday</dt>
              <dd>{c.birth_month && c.birth_day ? `${MONTHS[c.birth_month - 1]} ${c.birth_day}` : "—"}</dd>
              <dt>Location</dt>
              <dd>{locationName(c.enrolled_location_id)}</dd>
            </dl>
            {!anonymized && c.email && (
              <Button size="sm" style={{ marginTop: 16 }} loading={portalLink.isPending} onClick={() => portalLink.mutate()}>
                <Mail size={14} aria-hidden="true" /> Email loyalty page link
              </Button>
            )}
          </Card>

          <Card title="Marketing consent">
            <Checkbox
              label="Receives marketing emails"
              checked={c.marketing_opt_in}
              disabled={anonymized || consent.isPending || !can("customers.create")}
              onChange={(e) => consent.mutate(e.target.checked)}
              hint="Separate from essential program messages. Every change is recorded."
            />
            {c.consent_history.length > 0 && (
              <ul className="small muted" style={{ margin: "12px 0 0", paddingLeft: 18 }}>
                {c.consent_history.slice(0, 5).map((h) => (
                  <li key={h.id}>
                    {h.granted ? "Opted in" : "Opted out"} via {h.source.replace("_", " ")} · {formatDateTime(h.created_at, tz)}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Referrals">
            {c.referred_by && (
              <p className="small" style={{ marginBottom: 8 }}>
                Referred by <Link to={`/customers/${c.referred_by.referrer.id}`}>{c.referred_by.referrer.display_name}</Link> ·{" "}
                <Status value={c.referred_by.status} label={REFERRAL_LABELS[c.referred_by.status]} />
              </p>
            )}
            {c.referrals_made.length === 0 ? (
              <p className="muted small">Hasn't referred anyone yet. Share code {c.referral_code}.</p>
            ) : (
              <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
                {c.referrals_made.map((r) => (
                  <li key={r.id}>
                    {r.referred?.display_name ?? "Invited friend"} — {REFERRAL_LABELS[r.status]}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {can("customers.privacy") && (
            <Card title="Privacy">
              <p className="muted small" style={{ marginBottom: 12 }}>
                Export everything held about this customer, or permanently remove their personal details. The anonymous points
                ledger is kept for financial records.
              </p>
              <div className="row">
                <Button size="sm" onClick={exportData}>
                  <Download size={14} aria-hidden="true" /> Export data (JSON)
                </Button>
                {!anonymized && (
                  <Button size="sm" variant="danger" onClick={() => setModal("anonymize")}>
                    <Trash2 size={14} aria-hidden="true" /> Delete personal data
                  </Button>
                )}
              </div>
            </Card>
          )}
        </div>
      </div>

      <Modal open={modal === "adjust"} title="Adjust points" onClose={() => setModal(null)}>
        <AdjustForm
          customerId={c.id}
          onDone={() => {
            setModal(null);
            setNotice({ kind: "success", text: "Adjustment recorded in the ledger." });
            invalidate();
          }}
        />
      </Modal>
      <Modal open={modal === "reverse"} title="Reverse ledger entry" onClose={() => setModal(null)}>
        {reverseEntry && (
          <ReasonForm
            description={`This adds a new entry of ${formatPoints(-reverseEntry.points, true)} points. The original entry is kept.`}
            submitLabel="Reverse entry"
            path={`/ledger/${reverseEntry.id}/reverse`}
            onDone={() => {
              setModal(null);
              setNotice({ kind: "success", text: "Entry reversed." });
              invalidate();
            }}
          />
        )}
      </Modal>
      <Modal open={modal === "cancel"} title="Cancel redemption" onClose={() => setModal(null)}>
        {cancelTarget && (
          <ReasonForm
            description={`Code ${cancelTarget.code} will stop working and ${cancelTarget.points_cost} points will be returned.`}
            submitLabel="Cancel and refund"
            path={`/redemptions/${cancelTarget.id}/cancel`}
            onDone={() => {
              setModal(null);
              setNotice({ kind: "success", text: "Redemption cancelled and points refunded." });
              invalidate();
            }}
          />
        )}
      </Modal>
      <Modal open={modal === "redeem"} title="Redeem a reward" onClose={() => setModal(null)}>
        <RedeemForm
          customer={c}
          onDone={() => {
            invalidate();
          }}
        />
      </Modal>
      <Modal open={modal === "edit"} title="Edit customer" onClose={() => setModal(null)}>
        <EditCustomerForm
          customer={c}
          onDone={() => {
            setModal(null);
            invalidate();
          }}
        />
      </Modal>
      <Modal open={modal === "anonymize"} title="Delete personal data" onClose={() => setModal(null)}>
        <AnonymizeForm
          customerId={c.id}
          onDone={() => {
            setModal(null);
            setNotice({ kind: "success", text: "Personal data removed. The anonymous ledger has been retained." });
            invalidate();
          }}
        />
      </Modal>
    </>
  );
}

const adjustSchema = z.object({
  points: z.coerce.number().int("Whole numbers only").refine((n) => n !== 0, "Must not be zero"),
  reason: z.string().trim().min(3, "Explain the adjustment (at least 3 characters)").max(255),
});

function AdjustForm({ customerId, onDone }: { customerId: number; onDone: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.input<typeof adjustSchema>, unknown, z.output<typeof adjustSchema>>({ resolver: zodResolver(adjustSchema) });
  async function onSubmit(values: z.output<typeof adjustSchema>) {
    setError(null);
    try {
      await api(`/customers/${customerId}/adjustments`, { method: "POST", body: values });
      onDone();
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }
  return (
    <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
      {error && <Alert kind="error">{error}</Alert>}
      <TextInput
        label="Points"
        type="number"
        inputMode="numeric"
        hint="Use a negative number to remove points."
        {...form.register("points")}
        error={form.formState.errors.points?.message}
      />
      <TextInput label="Reason (required)" {...form.register("reason")} error={form.formState.errors.reason?.message} />
      <p className="muted small">Adjustments are permanent ledger entries and appear in the audit log.</p>
      <div className="form-actions">
        <Button type="submit" variant="primary" loading={form.formState.isSubmitting}>
          Record adjustment
        </Button>
      </div>
    </form>
  );
}

const reasonSchema = z.object({ reason: z.string().trim().min(3, "At least 3 characters").max(255) });

function ReasonForm({ description, submitLabel, path, onDone }: { description: string; submitLabel: string; path: string; onDone: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const form = useForm<{ reason: string }>({ resolver: zodResolver(reasonSchema) });
  async function onSubmit(values: { reason: string }) {
    setError(null);
    try {
      await api(path, { method: "POST", body: values });
      onDone();
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }
  return (
    <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
      <p>{description}</p>
      {error && <Alert kind="error">{error}</Alert>}
      <TextInput label="Reason (required)" autoFocus {...form.register("reason")} error={form.formState.errors.reason?.message} />
      <div className="form-actions">
        <Button type="submit" variant="primary" loading={form.formState.isSubmitting}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}

const editSchema = z.object({
  display_name: z.string().trim().min(1, "Required").max(120),
  email: z.union([z.literal(""), z.string().trim().email("Enter a valid email")]),
  phone: z.string().trim(),
  status: z.enum(["active", "inactive"]),
  birth_month: z.string(),
  birth_day: z.string(),
});

function EditCustomerForm({ customer, onDone }: { customer: CustomerDetail; onDone: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof editSchema>>({
    resolver: zodResolver(editSchema),
    defaultValues: {
      display_name: customer.display_name,
      email: customer.email ?? "",
      phone: customer.phone ?? "",
      status: customer.status === "inactive" ? "inactive" : "active",
      birth_month: customer.birth_month ? String(customer.birth_month) : "",
      birth_day: customer.birth_day ? String(customer.birth_day) : "",
    },
  });
  async function onSubmit(values: z.infer<typeof editSchema>) {
    setError(null);
    try {
      await api(`/customers/${customer.id}`, {
        method: "PATCH",
        body: {
          display_name: values.display_name,
          status: values.status,
          email: values.email || null,
          phone: values.phone || null,
          ...birthdayPayload(values.birth_month, values.birth_day),
        },
      });
      onDone();
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }
  const errors = form.formState.errors;
  return (
    <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
      {error && <Alert kind="error">{error}</Alert>}
      <TextInput label="Name" {...form.register("display_name")} error={errors.display_name?.message} />
      <TextInput label="Email" type="email" {...form.register("email")} error={errors.email?.message} />
      <TextInput label="Phone" type="tel" {...form.register("phone")} error={errors.phone?.message} />
      <BirthdayFields
        month={form.watch("birth_month")}
        day={form.watch("birth_day")}
        onChange={(m, d) => {
          form.setValue("birth_month", m);
          form.setValue("birth_day", d);
        }}
        error={errors.birth_day?.message}
      />
      <div className="field">
        <label htmlFor="edit-status">Status</label>
        <select id="edit-status" className="select" {...form.register("status")}>
          <option value="active">Active</option>
          <option value="inactive">Inactive (cannot earn or redeem)</option>
        </select>
      </div>
      <div className="form-actions">
        <Button type="submit" variant="primary" loading={form.formState.isSubmitting}>
          Save changes
        </Button>
      </div>
    </form>
  );
}

function AnonymizeForm({ customerId, onDone }: { customerId: number; onDone: () => void }) {
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api(`/customers/${customerId}/anonymize`, { method: "POST", body: { confirm } });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="form">
      <Alert kind="warning" title="This cannot be undone">
        Name, email and phone are erased, sign-in links are revoked and unused reward codes are cancelled. Points history stays as
        anonymous records.
      </Alert>
      {error && <Alert kind="error">{error}</Alert>}
      <TextInput label='Type "DELETE" to confirm' value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
      <div className="form-actions">
        <Button variant="danger" disabled={confirm !== "DELETE"} loading={busy} onClick={submit}>
          Delete personal data
        </Button>
      </div>
    </div>
  );
}

/** Progress toward the cheapest reward the customer can't afford yet. */
function NextReward({ balance }: { balance: number }) {
  const rewards = useRewards("active");
  const sorted = [...(rewards.data ?? [])].sort((a, b) => a.points_cost - b.points_cost);
  if (!sorted.length) return null;
  const next = sorted.find((r) => r.points_cost > balance);
  const affordable = sorted.filter((r) => r.points_cost <= balance).length;
  if (!next) return <div className="highlight-foot">Can redeem any reward in the catalog.</div>;
  const pct = Math.min(100, Math.round((balance / next.points_cost) * 100));
  return (
    <>
      <div className="progress" role="progressbar" aria-valuenow={balance} aria-valuemin={0} aria-valuemax={next.points_cost} aria-label={`Progress to ${next.name}`}>
        <span style={{ width: `${pct}%` }} />
      </div>
      <div className="highlight-foot">
        {formatNumber(next.points_cost - balance)} points to {next.name}
        {affordable > 0 && ` · ${affordable} reward${affordable === 1 ? "" : "s"} available now`}
      </div>
    </>
  );
}
