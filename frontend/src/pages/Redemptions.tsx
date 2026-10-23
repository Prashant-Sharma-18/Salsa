import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "../api/client";
import type { Envelope, Paged, Redemption } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Alert, Button, Card, EmptyState, PageHeader, Pagination, QueryState, Select, Status, TextInput } from "../components/ui";
import { formatDateTime, formatNumber } from "../lib/format";
import { useCheckoutLocation } from "./Checkout";

export function RedemptionsPage() {
  const { can, session } = useAuth();
  const tz = session?.user.timezone;
  const qc = useQueryClient();
  const { locations, locationId, select } = useCheckoutLocation();
  const [code, setCode] = useState("");
  const [found, setFound] = useState<Redemption | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const list = useQuery({
    queryKey: ["redemptions", status, page],
    queryFn: () => api<Paged<Redemption>>(`/redemptions${qs({ status, page, page_size: 15 })}`),
    enabled: can("redemptions.issue"),
  });

  async function lookup(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setFound(null);
    if (!code.trim()) {
      setError("Enter the code shown by the customer.");
      return;
    }
    setBusy(true);
    try {
      const res = await api<Envelope<Redemption>>(`/redemptions/lookup${qs({ code: code.trim() })}`);
      setFound(res.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lookup failed");
    } finally {
      setBusy(false);
    }
  }

  async function complete() {
    if (!found || !locationId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api<Envelope<Redemption>>(`/redemptions/${found.id}/complete`, { method: "POST", body: { location_id: locationId } });
      setFound(res.data);
      setMessage("Redemption completed. Apply the reward at your register.");
      qc.invalidateQueries({ queryKey: ["redemptions"] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not complete redemption");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Validate redemption" description="Check a customer's reward code, then mark it as used." />
      <div className="grid grid-2">
        <Card title="Enter code">
          <form className="form" onSubmit={lookup} noValidate>
            <TextInput
              label="Redemption code"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              className="input-lg mono"
              autoComplete="off"
              autoCapitalize="characters"
              maxLength={16}
              placeholder="e.g. 7KQ2M9XD"
            />
            <Select label="Your location" value={locationId ?? ""} onChange={(e) => select(Number(e.target.value))}>
              {locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </Select>
            <Button type="submit" variant="primary" loading={busy && !found}>
              Look up code
            </Button>
          </form>
        </Card>
        <Card title="Result">
          {error && <Alert kind="error">{error}</Alert>}
          {!found && !error && <p className="muted">Look up a code to see the reward and its status.</p>}
          {found && (
            <div className="stack">
              <div className="result-panel">
                <div className="code-display">{found.code}</div>
                <dl className="dl" style={{ marginTop: 12 }}>
                  <dt>Reward</dt>
                  <dd>{found.reward.name}</dd>
                  <dt>Customer</dt>
                  <dd>
                    {found.customer && <Link to={`/customers/${found.customer.id}`}>{found.customer.display_name}</Link>}
                  </dd>
                  <dt>Status</dt>
                  <dd>
                    <Status value={found.status} />
                  </dd>
                  <dt>Expires</dt>
                  <dd>{formatDateTime(found.expires_at, tz)}</dd>
                  {found.reward.terms && (
                    <>
                      <dt>Terms</dt>
                      <dd>{found.reward.terms}</dd>
                    </>
                  )}
                </dl>
              </div>
              {message && (
                <Alert kind="success">{message}</Alert>
              )}
              {found.status === "issued" ? (
                <Button variant="primary" loading={busy} onClick={complete}>
                  Mark as used
                </Button>
              ) : (
                !message && <Alert kind="warning">This code is {found.status} and cannot be used.</Alert>
              )}
            </div>
          )}
        </Card>
      </div>

      {can("redemptions.issue") && (
        <div style={{ marginTop: 16 }}>
          <Card bodyless title="Recent redemptions">
            <div className="toolbar">
              <div className="field">
                <label htmlFor="red-status">Status</label>
                <select id="red-status" className="select" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
                  <option value="">All</option>
                  <option value="issued">Issued</option>
                  <option value="redeemed">Redeemed</option>
                  <option value="cancelled">Cancelled</option>
                  <option value="expired">Expired</option>
                </select>
              </div>
            </div>
            <QueryState isLoading={list.isLoading} error={list.error}>
              {list.data?.data.length === 0 ? (
                <EmptyState title="No redemptions yet" description="Codes issued at checkout or by customers will appear here." />
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Code</th>
                        <th>Reward</th>
                        <th>Customer</th>
                        <th>Status</th>
                        <th>Issued</th>
                        <th className="num">Points</th>
                      </tr>
                    </thead>
                    <tbody>
                      {list.data?.data.map((r) => (
                        <tr key={r.id}>
                          <td className="mono">{r.code}</td>
                          <td>{r.reward.name}</td>
                          <td>{r.customer && <Link to={`/customers/${r.customer.id}`}>{r.customer.display_name}</Link>}</td>
                          <td>
                            <Status value={r.status} />
                          </td>
                          <td className="small muted">{formatDateTime(r.created_at, tz)}</td>
                          <td className="num">{formatNumber(r.points_cost)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {list.data && list.data.meta.total > 0 && (
                <Pagination page={list.data.meta.page} pages={list.data.meta.pages} total={list.data.meta.total} onPage={setPage} />
              )}
            </QueryState>
          </Card>
        </div>
      )}
    </>
  );
}
