import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Gift, Plus } from "lucide-react";
import { api } from "../api/client";
import { useRewards } from "../api/hooks";
import type { Reward } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import {
  Alert,
  applyServerErrors,
  Button,
  Card,
  EmptyState,
  Modal,
  PageHeader,
  QueryState,
  Select,
  Status,
  Textarea,
  TextInput,
} from "../components/ui";
import { centsToInput, formatMoney, formatNumber, REWARD_TYPE_LABELS } from "../lib/format";

const schema = z
  .object({
    name: z.string().trim().min(1, "Required").max(120),
    description: z.string().max(2000),
    reward_type: z.enum(["fixed_discount", "free_item", "custom"]),
    value: z.union([z.literal(""), z.string().trim().regex(/^\d{1,7}(\.\d{1,2})?$/, "Enter an amount like 5.00")]),
    points_cost: z.coerce.number().int("Whole numbers only").min(1, "At least 1").max(1_000_000),
    stock_limit: z.union([z.literal(""), z.coerce.number().int("Whole numbers only").min(0, "Cannot be negative")]),
    status: z.enum(["active", "archived"]),
    terms: z.string().max(2000),
  })
  .refine((v) => v.reward_type !== "fixed_discount" || v.value !== "", { message: "Required for fixed discounts", path: ["value"] });
type Values = z.infer<typeof schema>;

export function RewardsPage() {
  const { can } = useAuth();
  const rewards = useRewards();
  const [editing, setEditing] = useState<Reward | "new" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const manage = can("rewards.manage");

  return (
    <>
      <PageHeader
        title="Rewards catalog"
        description="What customers can spend points on. Archived rewards stay in history but can't be redeemed."
        actions={
          manage && (
            <Button variant="primary" onClick={() => setEditing("new")}>
              <Plus size={16} aria-hidden="true" /> Add reward
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
        <QueryState isLoading={rewards.isLoading} error={rewards.error}>
          {rewards.data?.length === 0 ? (
            <EmptyState
              icon={<Gift size={28} aria-hidden="true" />}
              title="No rewards yet"
              description="Add at least one reward so customers have something to work toward."
              action={manage ? <Button variant="primary" onClick={() => setEditing("new")}>Add reward</Button> : undefined}
            />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Reward</th>
                    <th>Type</th>
                    <th className="num">Cost</th>
                    <th className="num">Stock left</th>
                    <th>Status</th>
                    {manage && <th><span className="visually-hidden">Actions</span></th>}
                  </tr>
                </thead>
                <tbody>
                  {rewards.data?.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <strong>{r.name}</strong>
                        {r.terms && <div className="muted small">{r.terms}</div>}
                      </td>
                      <td className="small">
                        {REWARD_TYPE_LABELS[r.reward_type]}
                        {r.value_cents ? ` · ${formatMoney(r.value_cents)}` : ""}
                      </td>
                      <td className="num">{formatNumber(r.points_cost)} pts</td>
                      <td className="num">{r.stock_remaining === null ? "Unlimited" : formatNumber(r.stock_remaining)}</td>
                      <td>
                        <Status value={r.status} />
                      </td>
                      {manage && (
                        <td className="num">
                          <Button size="sm" onClick={() => setEditing(r)} aria-label={`Edit ${r.name}`}>
                            Edit
                          </Button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </QueryState>
      </Card>
      <Modal open={editing !== null} title={editing === "new" ? "Add reward" : "Edit reward"} onClose={() => setEditing(null)}>
        {editing !== null && (
          <RewardForm
            reward={editing === "new" ? null : editing}
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

function RewardForm({ reward, onDone }: { reward: Reward | null; onDone: (message: string) => void }) {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: reward
      ? {
          name: reward.name,
          description: reward.description,
          reward_type: reward.reward_type,
          value: centsToInput(reward.value_cents),
          points_cost: reward.points_cost,
          stock_limit: reward.stock_limit ?? "",
          status: reward.status,
          terms: reward.terms,
        }
      : { name: "", description: "", reward_type: "free_item", value: "", points_cost: 100, stock_limit: "", status: "active", terms: "" },
  });
  const type = form.watch("reward_type");

  async function onSubmit(values: Values) {
    setError(null);
    const body = {
      ...values,
      value: values.value || null,
      stock_limit: values.stock_limit === "" ? null : values.stock_limit,
    };
    try {
      await api(reward ? `/rewards/${reward.id}` : "/rewards", { method: reward ? "PATCH" : "POST", body });
      qc.invalidateQueries({ queryKey: ["rewards"] });
      onDone(reward ? "Reward updated." : "Reward added.");
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }

  async function remove() {
    if (!reward) return;
    setDeleting(true);
    setError(null);
    try {
      await api(`/rewards/${reward.id}`, { method: "DELETE" });
      qc.invalidateQueries({ queryKey: ["rewards"] });
      onDone("Reward deleted.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeleting(false);
    }
  }

  const errors = form.formState.errors;
  return (
    <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
      {error && <Alert kind="error">{error}</Alert>}
      <TextInput label="Name" {...form.register("name")} error={errors.name?.message} />
      <div className="grid grid-2">
        <Select label="Type" {...form.register("reward_type")}>
          {Object.entries(REWARD_TYPE_LABELS).map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </Select>
        <TextInput
          label={type === "fixed_discount" ? "Discount value ($)" : "Retail value ($, optional)"}
          inputMode="decimal"
          {...form.register("value")}
          error={errors.value?.message}
        />
      </div>
      <div className="grid grid-2">
        <TextInput label="Points cost" type="number" inputMode="numeric" {...form.register("points_cost")} error={errors.points_cost?.message} />
        <TextInput
          label="Stock limit (optional)"
          type="number"
          inputMode="numeric"
          hint="Leave blank for unlimited."
          {...form.register("stock_limit")}
          error={errors.stock_limit?.message}
        />
      </div>
      <Textarea label="Description (optional)" rows={2} {...form.register("description")} />
      <Textarea label="Terms shown to customers (optional)" rows={2} {...form.register("terms")} />
      <Select label="Status" {...form.register("status")}>
        <option value="active">Active</option>
        <option value="archived">Archived</option>
      </Select>
      <div className="form-actions" style={{ justifyContent: reward ? "space-between" : "flex-end" }}>
        {reward && (
          <Button variant="ghost" loading={deleting} onClick={remove}>
            Delete
          </Button>
        )}
        <Button type="submit" variant="primary" loading={form.formState.isSubmitting}>
          {reward ? "Save reward" : "Add reward"}
        </Button>
      </div>
    </form>
  );
}
