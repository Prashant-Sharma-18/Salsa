import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Megaphone, Plus } from "lucide-react";
import { api } from "../api/client";
import { useLocations } from "../api/hooks";
import type { Envelope, Promotion } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Alert, applyServerErrors, Button, Card, Checkbox, EmptyState, Modal, PageHeader, QueryState, Select, Status, TextInput } from "../components/ui";
import { centsToInput, formatMoney, isoDate, promotionSchedule, promotionValue, WEEKDAYS } from "../lib/format";

export function PromotionsPage() {
  const { can } = useAuth();
  const locations = useLocations();
  const [editing, setEditing] = useState<Promotion | "new" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["promotions"],
    queryFn: async () => (await api<Envelope<Promotion[]>>("/promotions")).data,
  });
  const manage = can("promotions.manage");
  const locName = (ids: number[]) => ids.map((id) => locations.data?.find((l) => l.id === id)?.name ?? `#${id}`).join(", ");
  const today = isoDate(new Date());

  return (
    <>
      <PageHeader
        title="Promotions"
        description="Extra points for a limited time — like double points on quiet days. Only the best multiplier applies to a purchase; bonuses add up."
        actions={
          manage && (
            <Button variant="primary" onClick={() => setEditing("new")}>
              <Plus size={16} aria-hidden="true" /> New promotion
            </Button>
          )
        }
      />
      {notice && (
        <div style={{ marginBottom: 16 }}>
          <Alert kind="success">{notice}</Alert>
        </div>
      )}
      <Card bodyless>
        <QueryState isLoading={query.isLoading} error={query.error}>
          {query.data?.length === 0 ? (
            <EmptyState
              icon={<Megaphone size={28} aria-hidden="true" />}
              title="No promotions yet"
              description="Try double points on your slowest weekday, or a bonus for bigger orders."
              action={manage ? <Button variant="primary" onClick={() => setEditing("new")}>New promotion</Button> : undefined}
            />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Promotion</th>
                    <th>Offer</th>
                    <th>When</th>
                    <th>Where</th>
                    <th>Status</th>
                    {manage && <th><span className="visually-hidden">Actions</span></th>}
                  </tr>
                </thead>
                <tbody>
                  {query.data?.map((p) => {
                    const ended = p.ends_on !== null && p.ends_on < today;
                    return (
                      <tr key={p.id}>
                        <td>
                          <strong>{p.name}</strong>
                          {p.description && <div className="muted small">{p.description}</div>}
                        </td>
                        <td className="small">
                          {promotionValue(p)}
                          {p.min_spend_cents > 0 && <div className="muted">on {formatMoney(p.min_spend_cents)}+</div>}
                        </td>
                        <td className="small">{promotionSchedule(p)}</td>
                        <td className="small">{p.location_ids?.length ? locName(p.location_ids) : "All locations"}</td>
                        <td>
                          <Status value={ended ? "expired" : p.status} label={ended ? "Ended" : undefined} />
                        </td>
                        {manage && (
                          <td className="num">
                            <Button size="sm" onClick={() => setEditing(p)} aria-label={`Edit ${p.name}`}>
                              Edit
                            </Button>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </QueryState>
      </Card>
      <Modal open={editing !== null} title={editing === "new" ? "New promotion" : "Edit promotion"} onClose={() => setEditing(null)}>
        {editing !== null && (
          <PromotionForm
            promotion={editing === "new" ? null : editing}
            onDone={(msg) => {
              setEditing(null);
              setNotice(msg);
            }}
          />
        )}
      </Modal>
    </>
  );
}

const schema = z
  .object({
    name: z.string().trim().min(1, "Required").max(120),
    description: z.string().max(500),
    promo_type: z.enum(["multiplier", "bonus"]),
    multiplier: z.string(),
    bonus_points: z.string(),
    starts_on: z.string().min(1, "Required"),
    ends_on: z.string(),
    min_spend: z.union([z.literal(""), z.string().regex(/^\d{1,7}(\.\d{1,2})?$/, "Enter an amount like 10.00")]),
    status: z.enum(["active", "archived"]),
  })
  .refine((v) => v.promo_type !== "bonus" || (Number(v.bonus_points) >= 1 && Number.isInteger(Number(v.bonus_points))), {
    message: "Enter whole bonus points",
    path: ["bonus_points"],
  })
  .refine((v) => !v.ends_on || v.ends_on >= v.starts_on, { message: "End date must be on or after the start", path: ["ends_on"] });
type Values = z.infer<typeof schema>;

function PromotionForm({ promotion, onDone }: { promotion: Promotion | null; onDone: (msg: string) => void }) {
  const qc = useQueryClient();
  const locations = useLocations();
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState<number[]>(promotion?.days_of_week ?? []);
  const [locIds, setLocIds] = useState<number[]>(promotion?.location_ids ?? []);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: promotion?.name ?? "",
      description: promotion?.description ?? "",
      promo_type: promotion?.promo_type ?? "multiplier",
      multiplier: String(promotion?.multiplier_percent ?? 200),
      bonus_points: promotion?.bonus_points ? String(promotion.bonus_points) : "",
      starts_on: promotion?.starts_on ?? isoDate(new Date()),
      ends_on: promotion?.ends_on ?? "",
      min_spend: centsToInput(promotion?.min_spend_cents),
      status: promotion?.status ?? "active",
    },
  });
  const type = form.watch("promo_type");
  const errors = form.formState.errors;

  async function onSubmit(v: Values) {
    setError(null);
    const body = {
      name: v.name,
      description: v.description,
      promo_type: v.promo_type,
      multiplier_percent: v.promo_type === "multiplier" ? Number(v.multiplier) : null,
      bonus_points: v.promo_type === "bonus" ? Number(v.bonus_points) : null,
      starts_on: v.starts_on,
      ends_on: v.ends_on || null,
      days_of_week: days,
      location_ids: locIds,
      min_spend: v.min_spend || "0",
      status: v.status,
    };
    try {
      await api(promotion ? `/promotions/${promotion.id}` : "/promotions", { method: promotion ? "PATCH" : "POST", body });
      qc.invalidateQueries({ queryKey: ["promotions"] });
      qc.invalidateQueries({ queryKey: ["promotions-active"] });
      onDone(promotion ? "Promotion updated." : "Promotion created.");
    } catch (err) {
      setError(applyServerErrors(err, form.setError, { multiplier_percent: "multiplier" }));
    }
  }

  const toggle = (list: number[], set: (v: number[]) => void, value: number) =>
    set(list.includes(value) ? list.filter((x) => x !== value) : [...list, value].sort((a, b) => a - b));

  return (
    <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
      {error && <Alert kind="error">{error}</Alert>}
      <TextInput label="Name" placeholder="Double Points Tuesdays" {...form.register("name")} error={errors.name?.message} />
      <TextInput label="Description shown to customers (optional)" {...form.register("description")} />
      <div className="grid grid-2">
        <Select label="Type" {...form.register("promo_type")}>
          <option value="multiplier">Points multiplier</option>
          <option value="bonus">Flat bonus per purchase</option>
        </Select>
        {type === "multiplier" ? (
          <Select label="Multiplier" {...form.register("multiplier")} error={errors.multiplier?.message}>
            <option value="150">1.5x points</option>
            <option value="200">2x points</option>
            <option value="300">3x points</option>
            <option value="500">5x points</option>
          </Select>
        ) : (
          <TextInput label="Bonus points" type="number" inputMode="numeric" {...form.register("bonus_points")} error={errors.bonus_points?.message} />
        )}
      </div>
      <div className="grid grid-2">
        <TextInput label="Starts" type="date" {...form.register("starts_on")} error={errors.starts_on?.message} />
        <TextInput label="Ends (optional)" type="date" {...form.register("ends_on")} error={errors.ends_on?.message} />
      </div>
      <fieldset className="fieldset">
        <legend className="small">Days (none selected = every day)</legend>
        <div className="row">
          {WEEKDAYS.map((d, i) => (
            <label key={d} className="checkbox" style={{ marginRight: 8 }}>
              <input type="checkbox" checked={days.includes(i)} onChange={() => toggle(days, setDays, i)} />
              <span>{d}</span>
            </label>
          ))}
        </div>
      </fieldset>
      {(locations.data?.length ?? 0) > 1 && (
        <fieldset className="fieldset">
          <legend className="small">Locations (none selected = all)</legend>
          {locations.data?.map((l) => (
            <Checkbox key={l.id} label={l.name} checked={locIds.includes(l.id)} onChange={() => toggle(locIds, setLocIds, l.id)} />
          ))}
        </fieldset>
      )}
      <div className="grid grid-2">
        <TextInput label="Minimum spend ($, optional)" inputMode="decimal" {...form.register("min_spend")} error={errors.min_spend?.message} />
        <Select label="Status" {...form.register("status")}>
          <option value="active">Active</option>
          <option value="archived">Archived</option>
        </Select>
      </div>
      <p className="muted small">Promotions apply to purchases that earn points. Dates use your business time zone.</p>
      <div className="form-actions">
        <Button type="submit" variant="primary" loading={form.formState.isSubmitting}>
          {promotion ? "Save promotion" : "Create promotion"}
        </Button>
      </div>
    </form>
  );
}
