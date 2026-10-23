import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ExternalLink } from "lucide-react";
import { api } from "../api/client";
import { useProgram } from "../api/hooks";
import type { Envelope, Program } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Alert, applyServerErrors, Button, Card, Checkbox, ErrorMessage, Loading, PageHeader, Select, Textarea, TextInput } from "../components/ui";
import { centsToInput } from "../lib/format";

const money = z.union([z.literal(""), z.string().trim().regex(/^\d{1,7}(\.\d{1,2})?$/, "Enter an amount like 5.00")]);
const int = (min: number, max: number) => z.coerce.number().int("Whole numbers only").min(min, `At least ${min}`).max(max, `At most ${max}`);

const schema = z.object({
  name: z.string().trim().min(1, "Required").max(120),
  description: z.string().max(2000),
  status: z.enum(["draft", "active", "paused"]),
  brand_color: z.string().regex(/^#[0-9a-fA-F]{6}$/, "Use a hex color like #1769aa"),
  logo_url: z.union([z.literal(""), z.string().url("Enter a full URL").startsWith("https://", "Must start with https://")]),
  contact_email: z.union([z.literal(""), z.string().email("Enter a valid email")]),
  contact_phone: z.string().max(32),
  earning_enabled: z.boolean(),
  points_per_dollar: int(0, 100),
  min_spend: money,
  redemption_enabled: z.boolean(),
  referrals_enabled: z.boolean(),
  referrer_reward_points: int(0, 100000),
  referee_reward_points: int(0, 100000),
  referral_min_spend: money,
  expiry_enabled: z.boolean(),
  points_expiry_days: z.coerce.number().int().min(30, "At least 30 days").max(3650, "At most 10 years"),
});
type Values = z.infer<typeof schema>;

function toValues(p: Program): Values {
  return {
    name: p.name,
    description: p.description,
    status: p.status,
    brand_color: p.brand_color,
    logo_url: p.logo_url,
    contact_email: p.contact_email,
    contact_phone: p.contact_phone,
    earning_enabled: p.earning_enabled,
    points_per_dollar: p.points_per_dollar,
    min_spend: centsToInput(p.min_spend_cents),
    redemption_enabled: p.redemption_enabled,
    referrals_enabled: p.referrals_enabled,
    referrer_reward_points: p.referrer_reward_points,
    referee_reward_points: p.referee_reward_points,
    referral_min_spend: centsToInput(p.referral_min_spend_cents),
    expiry_enabled: p.points_expiry_days !== null,
    points_expiry_days: p.points_expiry_days ?? 365,
  };
}

export function ProgramSettingsPage() {
  const program = useProgram();
  const { session, can } = useAuth();
  const qc = useQueryClient();
  const [notice, setNotice] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [running, setRunning] = useState(false);
  const form = useForm<Values>({ resolver: zodResolver(schema) });

  useEffect(() => {
    if (program.data) form.reset(toValues(program.data));
  }, [program.data, form]);

  if (program.isLoading) return <Loading />;
  if (program.error) return <ErrorMessage error={program.error} />;
  const errors = form.formState.errors;
  const w = form.watch();

  async function onSubmit(v: Values) {
    setNotice(null);
    const { expiry_enabled, ...rest } = v;
    try {
      const res = await api<Envelope<Program>>("/programs/current", {
        method: "PATCH",
        body: {
          ...rest,
          min_spend: v.min_spend || "0",
          referral_min_spend: v.referral_min_spend || "0",
          points_expiry_days: expiry_enabled ? v.points_expiry_days : null,
        },
      });
      qc.setQueryData(["program"], res.data);
      setNotice({ kind: "success", text: "Program settings saved." });
      window.scrollTo({ top: 0 });
    } catch (err) {
      setNotice({ kind: "error", text: applyServerErrors(err, form.setError) });
    }
  }

  async function runExpiry() {
    setRunning(true);
    try {
      const res = await api<Envelope<{ expired_balances: number; expired_codes: number }>>("/programs/current/run-expiry", { method: "POST" });
      setNotice({
        kind: "success",
        text: `Expiry processed: ${res.data.expired_balances} balances expired, ${res.data.expired_codes} unused codes expired and refunded.`,
      });
    } catch (err) {
      setNotice({ kind: "error", text: (err as Error).message });
    } finally {
      setRunning(false);
    }
  }

  const slug = session?.active_business?.slug;

  return (
    <>
      <PageHeader
        title="Program settings"
        description="Changes apply to future transactions. Past ledger entries are never rewritten."
        actions={
          slug && (
            <a className="btn" href={`/join/${slug}`} target="_blank" rel="noreferrer">
              <ExternalLink size={16} aria-hidden="true" /> Public join page
            </a>
          )
        }
      />
      {notice && (
        <div style={{ marginBottom: 16 }}>
          <Alert kind={notice.kind}>{notice.text}</Alert>
        </div>
      )}
      <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
        <div className="grid grid-sidebar">
          <div className="stack">
            <Card title="Branding and contact">
              <div className="form">
                <div className="grid grid-2">
                  <TextInput label="Program name" {...form.register("name")} error={errors.name?.message} />
                  <Select label="Status" {...form.register("status")} hint="Paused programs don't earn or redeem; draft programs hide the public page.">
                    <option value="active">Active</option>
                    <option value="paused">Paused</option>
                    <option value="draft">Draft</option>
                  </Select>
                </div>
                <Textarea label="Description" rows={2} {...form.register("description")} error={errors.description?.message} />
                <div className="grid grid-2">
                  <TextInput label="Brand color" {...form.register("brand_color")} error={errors.brand_color?.message} hint="Hex color for the customer page header." />
                  <TextInput label="Logo URL (https, optional)" {...form.register("logo_url")} error={errors.logo_url?.message} />
                </div>
                <div className="grid grid-2">
                  <TextInput label="Contact email" type="email" {...form.register("contact_email")} error={errors.contact_email?.message} />
                  <TextInput label="Contact phone" type="tel" {...form.register("contact_phone")} error={errors.contact_phone?.message} />
                </div>
              </div>
            </Card>

            <Card title="Earning">
              <div className="form">
                <Checkbox label="Customers earn points on purchases" {...form.register("earning_enabled")} />
                <div className="grid grid-2">
                  <TextInput label="Points per $1" type="number" inputMode="numeric" {...form.register("points_per_dollar")} error={errors.points_per_dollar?.message} disabled={!w.earning_enabled} />
                  <TextInput label="Minimum spend ($, optional)" inputMode="decimal" {...form.register("min_spend")} error={errors.min_spend?.message} disabled={!w.earning_enabled} />
                </div>
              </div>
            </Card>

            <Card title="Redemption">
              <Checkbox
                label="Customers can redeem points for rewards"
                hint="Configure what each reward costs in the Rewards catalog."
                {...form.register("redemption_enabled")}
              />
            </Card>

            <Card title="Referrals">
              <div className="form">
                <Checkbox label="Referral program enabled" {...form.register("referrals_enabled")} />
                <div className="grid grid-3">
                  <TextInput label="Referrer reward (points)" type="number" {...form.register("referrer_reward_points")} error={errors.referrer_reward_points?.message} disabled={!w.referrals_enabled} />
                  <TextInput label="Friend reward (points)" type="number" {...form.register("referee_reward_points")} error={errors.referee_reward_points?.message} disabled={!w.referrals_enabled} />
                  <TextInput label="Qualifying purchase ($)" inputMode="decimal" hint="Minimum first purchase." {...form.register("referral_min_spend")} error={errors.referral_min_spend?.message} disabled={!w.referrals_enabled} />
                </div>
              </div>
            </Card>

            <Card title="Points expiry">
              <div className="form">
                <Checkbox
                  label="Expire points after a period of inactivity"
                  hint="If a customer has no earning or redemption activity for this many days, their whole balance expires. Earning or redeeming resets the clock."
                  {...form.register("expiry_enabled")}
                />
                {w.expiry_enabled && (
                  <TextInput label="Days of inactivity" type="number" {...form.register("points_expiry_days")} error={errors.points_expiry_days?.message} />
                )}
                {can("expiry.run") && program.data?.points_expiry_days && (
                  <div>
                    <Button size="sm" loading={running} onClick={runExpiry}>
                      Run expiry now
                    </Button>
                    <p className="muted small" style={{ marginTop: 4 }}>
                      Also schedulable with <code>flask expire-points</code>.
                    </p>
                  </div>
                )}
              </div>
            </Card>
            <div className="form-actions">
              <Button type="submit" variant="primary" loading={form.formState.isSubmitting}>
                Save settings
              </Button>
            </div>
          </div>
          <div>
            <Card title="Rules customers see">
              <ul className="rules">
                {program.data?.rules.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
              <p className="muted small" style={{ marginTop: 12 }}>
                Updates after you save.
              </p>
            </Card>
          </div>
        </div>
      </form>
    </>
  );
}
