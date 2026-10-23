import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { UserPlus } from "lucide-react";
import { api } from "../api/client";
import { useLocations } from "../api/hooks";
import type { Envelope, Invitation, Member } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Alert, applyServerErrors, Button, Card, Checkbox, Modal, PageHeader, QueryState, Select, Status, TextInput } from "../components/ui";
import { formatDate } from "../lib/format";

const ROLE_HELP: Record<string, string> = {
  owner: "Full control including billing boundary, program settings, staff and data deletion.",
  manager: "Day-to-day operations: rewards, adjustments, reversals, cancellations, analytics and exports.",
  staff: "Checkout tasks: enroll customers, record purchases, issue and validate redemptions.",
};

export function TeamPage() {
  const { can, session } = useAuth();
  const tz = session?.user.timezone;
  const qc = useQueryClient();
  const locations = useLocations();
  const [modal, setModal] = useState<"invite" | Member | null>(null);
  const [notice, setNotice] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const manage = can("members.manage");
  const query = useQuery({
    queryKey: ["members"],
    queryFn: async () => (await api<Envelope<{ members: Member[]; invitations: Invitation[] }>>("/members")).data,
  });
  const locName = (ids: number[]) => ids.map((id) => locations.data?.find((l) => l.id === id)?.name ?? `#${id}`).join(", ");

  async function revoke(inv: Invitation) {
    try {
      await api(`/members/invitations/${inv.id}`, { method: "DELETE" });
      qc.invalidateQueries({ queryKey: ["members"] });
      setNotice({ kind: "success", text: "Invitation revoked." });
    } catch (err) {
      setNotice({ kind: "error", text: (err as Error).message });
    }
  }

  return (
    <>
      <PageHeader
        title="Staff & permissions"
        description="Permissions are enforced by the server for every request."
        actions={
          manage && (
            <Button variant="primary" onClick={() => setModal("invite")} disabled={!session?.user.email_verified}>
              <UserPlus size={16} aria-hidden="true" /> Invite team member
            </Button>
          )
        }
      />
      <div className="stack" style={{ marginBottom: 16 }}>
        {manage && !session?.user.email_verified && <Alert kind="warning">Verify your email address before inviting team members.</Alert>}
        {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}
      </div>
      <QueryState isLoading={query.isLoading} error={query.error}>
        <div className="stack">
          <Card title="Team" bodyless>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Role</th>
                    <th>Locations</th>
                    <th>Status</th>
                    {manage && <th><span className="visually-hidden">Actions</span></th>}
                  </tr>
                </thead>
                <tbody>
                  {query.data?.members.map((m) => (
                    <tr key={m.id}>
                      <td>
                        <strong>{m.user.display_name}</strong>
                        <div className="muted small">{m.user.email}</div>
                      </td>
                      <td style={{ textTransform: "capitalize" }}>{m.role}</td>
                      <td className="small">{m.all_locations ? "All locations" : locName(m.location_ids)}</td>
                      <td>
                        <Status value={m.status} />
                      </td>
                      {manage && (
                        <td className="num">
                          {m.role !== "owner" && m.user.id !== session?.user.id && (
                            <Button size="sm" onClick={() => setModal(m)}>
                              Manage
                            </Button>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          {manage && (
            <Card title="Invitations" bodyless>
              {query.data?.invitations.length === 0 ? (
                <p className="card-body muted">No pending invitations.</p>
              ) : (
                <ul className="list-plain">
                  {query.data?.invitations.map((inv) => (
                    <li key={inv.id} className="row between">
                      <div>
                        <strong>{inv.email}</strong> · <span style={{ textTransform: "capitalize" }}>{inv.role}</span>
                        <div className="muted small">
                          <Status value={inv.status} /> · expires {formatDate(inv.expires_at, tz)}
                        </div>
                      </div>
                      {inv.status === "pending" && (
                        <Button size="sm" variant="ghost" onClick={() => revoke(inv)}>
                          Revoke
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}
          <Card title="What each role can do">
            <dl className="dl">
              {Object.entries(ROLE_HELP).map(([role, help]) => (
                <div key={role} style={{ display: "contents" }}>
                  <dt style={{ textTransform: "capitalize" }}>{role}</dt>
                  <dd>{help}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </div>
      </QueryState>
      <Modal open={modal === "invite"} title="Invite team member" onClose={() => setModal(null)}>
        <InviteForm
          onDone={(email) => {
            setModal(null);
            setNotice({ kind: "success", text: `Invitation sent to ${email}. The link expires in 7 days and works once.` });
          }}
        />
      </Modal>
      <Modal open={modal !== null && modal !== "invite"} title="Manage team member" onClose={() => setModal(null)}>
        {modal && modal !== "invite" && (
          <MemberForm
            member={modal}
            onDone={() => {
              setModal(null);
              setNotice({ kind: "success", text: "Team member updated." });
            }}
          />
        )}
      </Modal>
    </>
  );
}

function LocationChecklist({ selected, onChange }: { selected: number[]; onChange: (ids: number[]) => void }) {
  const locations = useLocations();
  return (
    <fieldset className="fieldset">
      <legend className="small">Locations</legend>
      {locations.data
        ?.filter((l) => l.status === "active")
        .map((l) => (
          <Checkbox
            key={l.id}
            label={l.name}
            checked={selected.includes(l.id)}
            onChange={(e) => onChange(e.target.checked ? [...selected, l.id] : selected.filter((id) => id !== l.id))}
          />
        ))}
    </fieldset>
  );
}

const inviteSchema = z.object({ email: z.string().trim().email("Enter a valid email"), role: z.enum(["manager", "staff"]) });

function InviteForm({ onDone }: { onDone: (email: string) => void }) {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [allLocations, setAllLocations] = useState(true);
  const [locationIds, setLocationIds] = useState<number[]>([]);
  const form = useForm<z.infer<typeof inviteSchema>>({ resolver: zodResolver(inviteSchema), defaultValues: { role: "staff" } });
  const role = form.watch("role");

  async function onSubmit(values: z.infer<typeof inviteSchema>) {
    setError(null);
    if (!allLocations && locationIds.length === 0) {
      setError("Choose at least one location.");
      return;
    }
    try {
      await api("/members/invitations", { method: "POST", body: { ...values, all_locations: allLocations, location_ids: locationIds } });
      qc.invalidateQueries({ queryKey: ["members"] });
      onDone(values.email);
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }

  return (
    <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
      {error && <Alert kind="error">{error}</Alert>}
      <TextInput label="Email" type="email" {...form.register("email")} error={form.formState.errors.email?.message} />
      <Select label="Role" hint={ROLE_HELP[role]} {...form.register("role")}>
        <option value="staff">Staff</option>
        <option value="manager">Manager</option>
      </Select>
      <Checkbox label="Access to all locations" checked={allLocations} onChange={(e) => setAllLocations(e.target.checked)} />
      {!allLocations && <LocationChecklist selected={locationIds} onChange={setLocationIds} />}
      <div className="form-actions">
        <Button type="submit" variant="primary" loading={form.formState.isSubmitting}>
          Send invitation
        </Button>
      </div>
    </form>
  );
}

function MemberForm({ member, onDone }: { member: Member; onDone: () => void }) {
  const qc = useQueryClient();
  const [role, setRole] = useState(member.role);
  const [status, setStatus] = useState(member.status);
  const [allLocations, setAllLocations] = useState(member.all_locations);
  const [locationIds, setLocationIds] = useState(member.location_ids);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api(`/members/${member.id}`, {
        method: "PATCH",
        body: { role, status, all_locations: allLocations, location_ids: allLocations ? [] : locationIds },
      });
      qc.invalidateQueries({ queryKey: ["members"] });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <p>
        <strong>{member.user.display_name}</strong> · {member.user.email}
      </p>
      {error && <Alert kind="error">{error}</Alert>}
      <Select label="Role" value={role} onChange={(e) => setRole(e.target.value as Member["role"])} hint={ROLE_HELP[role]}>
        <option value="staff">Staff</option>
        <option value="manager">Manager</option>
      </Select>
      <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value as Member["status"])}>
        <option value="active">Active</option>
        <option value="deactivated">Deactivated (no access)</option>
      </Select>
      <Checkbox label="Access to all locations" checked={allLocations} onChange={(e) => setAllLocations(e.target.checked)} />
      {!allLocations && <LocationChecklist selected={locationIds} onChange={setLocationIds} />}
      <div className="form-actions">
        <Button variant="primary" loading={busy} onClick={save}>
          Save changes
        </Button>
      </div>
    </div>
  );
}
