import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { api } from "../api/client";
import type { Business, Envelope, User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Alert, applyServerErrors, Button, Card, Checkbox, PageHeader, Select, TextInput } from "../components/ui";
import { TwoFactorCard } from "./TwoFactor";

const TIMEZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu", "UTC"];

export function AccountPage() {
  const { session, can, refresh } = useAuth();
  const [notice, setNotice] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [resending, setResending] = useState(false);
  if (!session) return null;

  async function resend() {
    setResending(true);
    try {
      await api("/auth/verify-email/resend", { method: "POST" });
      setNotice({ kind: "success", text: "Verification email sent." });
    } catch (err) {
      setNotice({ kind: "error", text: (err as Error).message });
    } finally {
      setResending(false);
    }
  }

  return (
    <>
      <PageHeader title="Account & privacy" description="Your profile, security and how customer data is handled." />
      {notice && (
        <div style={{ marginBottom: 16 }}>
          <Alert kind={notice.kind}>{notice.text}</Alert>
        </div>
      )}
      <div className="grid grid-2">
        <div className="stack">
          <ProfileForm user={session.user} onSaved={() => { refresh(); setNotice({ kind: "success", text: "Profile saved." }); }} />
          <Card title="Email">
            <p>
              {session.user.email} · {session.user.email_verified ? <span className="text-success">Verified</span> : "Not verified"}
            </p>
            {!session.user.email_verified && (
              <Button size="sm" style={{ marginTop: 12 }} loading={resending} onClick={resend}>
                Resend verification email
              </Button>
            )}
          </Card>
          <TwoFactorCard />
          <PasswordForm onSaved={() => setNotice({ kind: "success", text: "Password changed. Other sessions were signed out." })} />
        </div>
        <div className="stack">
          {can("business.manage") && session.active_business && (
            <BusinessForm business={session.active_business} onSaved={() => { refresh(); setNotice({ kind: "success", text: "Business saved." }); }} />
          )}
          <Card title="Customer data and privacy">
            <ul className="rules small">
              <li>Customer contact details and balances are private to your business and never shared between businesses.</li>
              <li>Marketing consent is optional, recorded with a timestamp, and can be withdrawn by the customer on their loyalty page.</li>
              <li>Owners can export a customer's data or delete their personal details from the customer's page. The anonymous points ledger is kept for financial records.</li>
              <li>No payment card data is collected or stored.</li>
              <li>
                A privacy notice template is included in the repository (<code>docs/PRIVACY_NOTICE_TEMPLATE.md</code>). Have it reviewed by a qualified
                professional before publishing; this product does not by itself make you compliant with any privacy law.
              </li>
            </ul>
          </Card>
          <Card title="Plan">
            <p className="small">
              Current plan: <strong style={{ textTransform: "capitalize" }}>{session.active_business?.plan}</strong>. Billing is not yet connected; no
              charges are made.
            </p>
          </Card>
        </div>
      </div>
    </>
  );
}

function ProfileForm({ user, onSaved }: { user: User; onSaved: () => void }) {
  const form = useForm<{ display_name: string; timezone: string }>({
    resolver: zodResolver(z.object({ display_name: z.string().trim().min(1, "Required").max(120), timezone: z.string() })),
    defaultValues: { display_name: user.display_name, timezone: user.timezone },
  });
  const [error, setError] = useState<string | null>(null);
  async function onSubmit(values: { display_name: string; timezone: string }) {
    try {
      await api<Envelope<User>>("/auth/account", { method: "PATCH", body: values });
      onSaved();
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }
  return (
    <Card title="Profile">
      <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
        {error && <Alert kind="error">{error}</Alert>}
        <TextInput label="Name" {...form.register("display_name")} error={form.formState.errors.display_name?.message} />
        <Select label="Display times in" {...form.register("timezone")}>
          {TIMEZONES.map((tz) => (
            <option key={tz} value={tz}>
              {tz}
            </option>
          ))}
        </Select>
        <div className="form-actions">
          <Button type="submit" variant="primary" loading={form.formState.isSubmitting}>
            Save profile
          </Button>
        </div>
      </form>
    </Card>
  );
}

const passwordSchema = z
  .object({
    current_password: z.string().min(1, "Required"),
    new_password: z.string().min(10, "Use at least 10 characters").max(128),
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, { message: "Passwords do not match", path: ["confirm"] });

function PasswordForm({ onSaved }: { onSaved: () => void }) {
  const form = useForm<z.infer<typeof passwordSchema>>({ resolver: zodResolver(passwordSchema) });
  const [error, setError] = useState<string | null>(null);
  async function onSubmit(values: z.infer<typeof passwordSchema>) {
    setError(null);
    try {
      await api("/auth/change-password", { method: "POST", body: { current_password: values.current_password, new_password: values.new_password } });
      form.reset({ current_password: "", new_password: "", confirm: "" });
      onSaved();
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }
  const errors = form.formState.errors;
  return (
    <Card title="Change password">
      <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
        {error && <Alert kind="error">{error}</Alert>}
        <TextInput label="Current password" type="password" autoComplete="current-password" {...form.register("current_password")} error={errors.current_password?.message} />
        <TextInput label="New password" type="password" autoComplete="new-password" {...form.register("new_password")} error={errors.new_password?.message} />
        <TextInput label="Confirm new password" type="password" autoComplete="new-password" {...form.register("confirm")} error={errors.confirm?.message} />
        <div className="form-actions">
          <Button type="submit" variant="primary" loading={form.formState.isSubmitting}>
            Change password
          </Button>
        </div>
      </form>
    </Card>
  );
}

function BusinessForm({ business, onSaved }: { business: Business; onSaved: () => void }) {
  const form = useForm<{ name: string; timezone: string; require_mfa: boolean }>({
    resolver: zodResolver(
      z.object({ name: z.string().trim().min(2, "Required").max(120), timezone: z.string(), require_mfa: z.boolean() }),
    ),
    defaultValues: { name: business.name, timezone: business.timezone, require_mfa: business.require_mfa },
  });
  const [error, setError] = useState<string | null>(null);
  async function onSubmit(values: { name: string; timezone: string; require_mfa: boolean }) {
    try {
      await api("/businesses/current", { method: "PATCH", body: values });
      onSaved();
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }
  return (
    <Card title="Business">
      <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
        {error && <Alert kind="error">{error}</Alert>}
        <TextInput label="Business name" {...form.register("name")} error={form.formState.errors.name?.message} />
        <Select label="Reporting time zone" {...form.register("timezone")}>
          {TIMEZONES.map((tz) => (
            <option key={tz} value={tz}>
              {tz}
            </option>
          ))}
        </Select>
        <Checkbox
          label="Require two-factor authentication for owners and managers"
          hint="They'll be asked to set it up before they can use this business. Turn it on for your own account first."
          {...form.register("require_mfa")}
        />
        <div className="form-actions">
          <Button type="submit" variant="primary" loading={form.formState.isSubmitting}>
            Save business
          </Button>
        </div>
      </form>
    </Card>
  );
}
