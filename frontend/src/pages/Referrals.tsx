import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Share2 } from "lucide-react";
import { api, qs } from "../api/client";
import { useProgram } from "../api/hooks";
import type { Paged, Referral } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import {
  Alert,
  applyServerErrors,
  Button,
  Card,
  EmptyState,
  Modal,
  PageHeader,
  Pagination,
  QueryState,
  Status,
  TextInput,
} from "../components/ui";
import { formatDate, formatMoney, REFERRAL_LABELS } from "../lib/format";
import { useCustomerSearch } from "./Customers";

const STATUSES = ["created", "signed_up", "qualified", "rewarded", "rejected"];

export function ReferralsPage() {
  const { can, session } = useAuth();
  const tz = session?.user.timezone;
  const program = useProgram();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [modal, setModal] = useState<"invite" | Referral | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["referrals", status, page],
    queryFn: () => api<Paged<Referral>>(`/referrals${qs({ status, page })}`),
  });
  const counts = query.data?.meta.status_counts ?? {};
  const p = program.data;

  return (
    <>
      <PageHeader
        title="Referrals"
        description={
          p?.referrals_enabled
            ? `Referrers earn ${p.referrer_reward_points} points${p.referee_reward_points ? ` and friends earn ${p.referee_reward_points}` : ""} after the friend's first purchase${p.referral_min_spend_cents ? ` of ${formatMoney(p.referral_min_spend_cents)} or more` : ""}.`
            : "Referrals are turned off in program settings."
        }
        actions={
          can("referrals.manage") &&
          p?.referrals_enabled && (
            <Button variant="primary" onClick={() => setModal("invite")}>
              Record a referral
            </Button>
          )
        }
      />
      {notice && (
        <div style={{ marginBottom: 16 }}>
          <Alert kind="success">{notice}</Alert>
        </div>
      )}
      <div className="stats-grid">
        {STATUSES.map((s) => (
          <div className="card stat" key={s}>
            <div className="stat-label">{REFERRAL_LABELS[s]}</div>
            <div className="stat-value">{counts[s] ?? 0}</div>
          </div>
        ))}
      </div>
      <Card bodyless>
        <div className="toolbar">
          <div className="field">
            <label htmlFor="ref-status">Status</label>
            <select id="ref-status" className="select" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
              <option value="">All</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {REFERRAL_LABELS[s]}
                </option>
              ))}
            </select>
          </div>
        </div>
        <QueryState isLoading={query.isLoading} error={query.error}>
          {query.data?.data.length === 0 ? (
            <EmptyState
              icon={<Share2 size={28} aria-hidden="true" />}
              title="No referrals yet"
              description="Every customer has a referral code and link on their loyalty page. Referrals appear here when friends enroll."
            />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Referrer</th>
                    <th>Friend</th>
                    <th>Status</th>
                    <th>Source</th>
                    <th>Created</th>
                    {can("referrals.manage") && <th><span className="visually-hidden">Actions</span></th>}
                  </tr>
                </thead>
                <tbody>
                  {query.data?.data.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <Link to={`/customers/${r.referrer.id}`}>{r.referrer.display_name}</Link>
                      </td>
                      <td>{r.referred ? <Link to={`/customers/${r.referred.id}`}>{r.referred.display_name}</Link> : <span className="muted">Not enrolled yet</span>}</td>
                      <td>
                        <Status value={r.status} label={REFERRAL_LABELS[r.status]} />
                        {r.rejection_reason && <div className="muted small">{r.rejection_reason}</div>}
                      </td>
                      <td className="small">{r.source}</td>
                      <td className="small muted">{formatDate(r.created_at, tz)}</td>
                      {can("referrals.manage") && (
                        <td className="num">
                          {!["rewarded", "rejected"].includes(r.status) && (
                            <Button size="sm" variant="ghost" onClick={() => setModal(r)}>
                              Reject
                            </Button>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {query.data && query.data.meta.total > 0 && (
            <Pagination page={query.data.meta.page} pages={query.data.meta.pages} total={query.data.meta.total} onPage={setPage} />
          )}
        </QueryState>
      </Card>
      <Modal open={modal === "invite"} title="Record a referral" onClose={() => setModal(null)}>
        <InviteForm
          onDone={() => {
            setModal(null);
            setNotice("Referral recorded. It converts when the friend enrolls with this email.");
          }}
        />
      </Modal>
      <Modal open={modal !== null && modal !== "invite"} title="Reject referral" onClose={() => setModal(null)}>
        {modal && modal !== "invite" && (
          <RejectForm
            referral={modal}
            onDone={() => {
              setModal(null);
              setNotice("Referral rejected. No rewards will be issued for it.");
            }}
          />
        )}
      </Modal>
    </>
  );
}

function InviteForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [referrerId, setReferrerId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const search = useCustomerSearch(q, 1, "active", 5);
  const form = useForm<{ email: string }>({ resolver: zodResolver(z.object({ email: z.string().trim().email("Enter a valid email") })) });

  async function onSubmit(values: { email: string }) {
    if (!referrerId) {
      setError("Choose the customer who made the referral.");
      return;
    }
    setError(null);
    try {
      await api("/referrals", { method: "POST", body: { referrer_customer_id: referrerId, email: values.email } });
      qc.invalidateQueries({ queryKey: ["referrals"] });
      onDone();
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }

  return (
    <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
      {error && <Alert kind="error">{error}</Alert>}
      <TextInput label="Referring customer" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search customers" />
      {q && (
        <div className="card" role="list">
          {search.data?.data.map((c) => (
            <div role="listitem" key={c.id}>
              <button type="button" className="customer-pick" aria-pressed={referrerId === c.id} onClick={() => setReferrerId(c.id)}>
                <span>{c.display_name}</span>
                <span className="muted small">{c.referral_code}</span>
              </button>
            </div>
          ))}
        </div>
      )}
      <TextInput label="Friend's email" type="email" {...form.register("email")} error={form.formState.errors.email?.message} />
      <div className="form-actions">
        <Button type="submit" variant="primary" loading={form.formState.isSubmitting}>
          Record referral
        </Button>
      </div>
    </form>
  );
}

function RejectForm({ referral, onDone }: { referral: Referral; onDone: () => void }) {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<{ reason: string }>({ resolver: zodResolver(z.object({ reason: z.string().trim().min(3, "At least 3 characters") })) });
  async function onSubmit(values: { reason: string }) {
    try {
      await api(`/referrals/${referral.id}/reject`, { method: "POST", body: values });
      qc.invalidateQueries({ queryKey: ["referrals"] });
      onDone();
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }
  return (
    <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
      <p>
        Referral from <strong>{referral.referrer.display_name}</strong>. Rejected referrals never pay out.
      </p>
      {error && <Alert kind="error">{error}</Alert>}
      <TextInput label="Reason" {...form.register("reason")} error={form.formState.errors.reason?.message} />
      <div className="form-actions">
        <Button type="submit" variant="danger" loading={form.formState.isSubmitting}>
          Reject referral
        </Button>
      </div>
    </form>
  );
}
