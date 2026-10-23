import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { UserPlus, Users } from "lucide-react";
import { api, qs } from "../api/client";
import { rememberedLocation, useAccessibleLocations, useProgram } from "../api/hooks";
import type { Customer, CustomerDetail, Envelope, Paged } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import {
  Alert,
  applyServerErrors,
  Button,
  Card,
  Checkbox,
  EmptyState,
  PageHeader,
  Pagination,
  QueryState,
  Select,
  Status,
  TextInput,
} from "../components/ui";
import { formatDate, formatNumber } from "../lib/format";

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function useCustomerSearch(q: string, page = 1, status = "", pageSize = 25) {
  const debounced = useDebounced(q.trim());
  return useQuery({
    queryKey: ["customers", debounced, page, status, pageSize],
    queryFn: () => api<Paged<Customer>>(`/customers${qs({ q: debounced, page, status, page_size: pageSize })}`),
    placeholderData: keepPreviousData,
  });
}

export function CustomersPage() {
  const { can, session } = useAuth();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const query = useCustomerSearch(q, page, status);
  const result = query.data;

  useEffect(() => setPage(1), [q, status]);

  return (
    <>
      <PageHeader
        title="Customers"
        description="Search by name, email, phone (last 4+ digits) or referral code."
        actions={
          can("customers.create") && (
            <Link className="btn btn-primary" to="/customers/new">
              <UserPlus size={16} aria-hidden="true" /> Enroll customer
            </Link>
          )
        }
      />
      <Card bodyless>
        <div className="toolbar">
          <div className="field grow">
            <label htmlFor="customer-search">Search</label>
            <input
              id="customer-search"
              className="input"
              type="search"
              value={q}
              placeholder="Name, email, phone or code"
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="customer-status">Status</label>
            <select id="customer-status" className="select" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="anonymized">Anonymized</option>
            </select>
          </div>
        </div>
        <QueryState isLoading={query.isLoading} error={query.error}>
          {result && result.data.length === 0 ? (
            <EmptyState
              icon={<Users size={28} aria-hidden="true" />}
              title={q || status ? "No customers match" : "No customers yet"}
              description={q || status ? "Try a different search or filter." : "Enroll your first customer at checkout or share your join page."}
              action={
                !q && can("customers.create") ? (
                  <Link className="btn btn-primary" to="/customers/new">
                    Enroll customer
                  </Link>
                ) : undefined
              }
            />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Contact</th>
                    <th>Enrolled</th>
                    <th>Status</th>
                    <th className="num">Points</th>
                  </tr>
                </thead>
                <tbody>
                  {result?.data.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <Link to={`/customers/${c.id}`}>{c.display_name}</Link>
                        {c.is_demo && <span className="tag" style={{ marginLeft: 8 }}>Demo</span>}
                      </td>
                      <td className="small">
                        {c.email ?? "—"}
                        {c.phone && <div className="muted">{c.phone}</div>}
                      </td>
                      <td className="small">{formatDate(c.enrolled_at, session?.user.timezone)}</td>
                      <td>
                        <Status value={c.status} />
                      </td>
                      <td className="num">{formatNumber(c.points_balance)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {result && result.meta.total > 0 && (
            <Pagination page={result.meta.page} pages={result.meta.pages} total={result.meta.total} onPage={setPage} />
          )}
        </QueryState>
      </Card>
    </>
  );
}

// ------------------------------------------------------------------- enroll

const enrollSchema = z
  .object({
    display_name: z.string().trim().min(1, "Required").max(120),
    email: z.union([z.literal(""), z.string().trim().email("Enter a valid email address")]),
    phone: z
      .string()
      .trim()
      .refine((v) => v === "" || v.replace(/\D/g, "").replace(/^1(?=\d{10}$)/, "").length === 10, "Enter a 10-digit US phone number"),
    location_id: z.string(),
    referral_code: z.string().trim().max(16),
    marketing_opt_in: z.boolean(),
  })
  .refine((v) => v.email || v.phone, { message: "Provide an email or phone number", path: ["email"] });
type EnrollValues = z.infer<typeof enrollSchema>;

export function EnrollCustomerPage() {
  const navigate = useNavigate();
  const locations = useAccessibleLocations();
  const program = useProgram();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<EnrollValues>({
    resolver: zodResolver(enrollSchema),
    defaultValues: {
      display_name: "",
      email: "",
      phone: "",
      referral_code: "",
      marketing_opt_in: false,
      location_id: String(rememberedLocation() ?? ""),
    },
  });
  const errors = form.formState.errors;

  useEffect(() => {
    const current = form.getValues("location_id");
    if (locations.data.length && !locations.data.some((l) => String(l.id) === current)) {
      form.setValue("location_id", String(locations.data[0].id));
    }
  }, [locations.data, form]);

  async function onSubmit(values: EnrollValues) {
    setError(null);
    try {
      const res = await api<Envelope<CustomerDetail & { referral: { status: string; rejection_reason: string | null } | null }>>(
        "/customers",
        {
          method: "POST",
          body: {
            display_name: values.display_name,
            email: values.email || undefined,
            phone: values.phone || undefined,
            location_id: values.location_id ? Number(values.location_id) : undefined,
            referral_code: values.referral_code || undefined,
            marketing_opt_in: values.marketing_opt_in,
          },
        },
      );
      navigate(`/customers/${res.data.id}`, { state: { enrolled: true, referral: res.data.referral } });
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }

  return (
    <>
      <PageHeader title="Enroll customer" description="Joining the loyalty program does not require marketing consent." />
      <div className="grid grid-sidebar">
        <Card>
          <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
            {error && <Alert kind="error">{error}</Alert>}
            <TextInput label="Name" autoFocus {...form.register("display_name")} error={errors.display_name?.message} />
            <div className="grid grid-2">
              <TextInput label="Email" type="email" autoComplete="off" {...form.register("email")} error={errors.email?.message} />
              <TextInput label="Phone (optional)" type="tel" autoComplete="off" {...form.register("phone")} error={errors.phone?.message} />
            </div>
            <div className="grid grid-2">
              <Select label="Enrolling location" {...form.register("location_id")}>
                {locations.data.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </Select>
              {program.data?.referrals_enabled && (
                <TextInput
                  label="Referral code (optional)"
                  hint="If a friend referred them."
                  style={{ textTransform: "uppercase" }}
                  {...form.register("referral_code")}
                  error={errors.referral_code?.message}
                />
              )}
            </div>
            <Checkbox
              label="Customer agrees to receive marketing emails"
              hint="Optional. Recorded with a timestamp. Essential program messages are sent regardless."
              {...form.register("marketing_opt_in")}
            />
            <div className="form-actions">
              <Button onClick={() => navigate(-1)}>Cancel</Button>
              <Button type="submit" variant="primary" loading={form.formState.isSubmitting}>
                Enroll customer
              </Button>
            </div>
          </form>
        </Card>
        {program.data && (
          <Card title="What to tell the customer">
            <ul className="rules">
              {program.data.rules.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </>
  );
}
