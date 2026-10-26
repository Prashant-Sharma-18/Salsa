import {
  forwardRef,
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import type { FieldValues, Path, UseFormSetError } from "react-hook-form";
import { ApiError } from "../api/client";

// ------------------------------------------------------------------ layout

export function PageHeader({
  title,
  description,
  actions,
  leading,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  leading?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div className="page-title-row">
        {leading}
        <div>
          <h1>{title}</h1>
          {description && <p className="page-description">{description}</p>}
        </div>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function Card({
  title,
  actions,
  children,
  footer,
  className = "",
  bodyless = false,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  className?: string;
  bodyless?: boolean;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-header">
          {typeof title === "string" ? <h2>{title}</h2> : title}
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {bodyless ? children : <div className="card-body">{children}</div>}
      {footer && <div className="card-footer">{footer}</div>}
    </section>
  );
}

export type Tone = "blue" | "green" | "amber" | "violet" | "rose";

export function StatCard({
  label,
  value,
  hint,
  icon,
  tone = "blue",
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  icon?: ReactNode;
  tone?: Tone;
}) {
  return (
    <div className="card stat">
      <div className="stat-head">
        <div className="stat-label">{label}</div>
        {icon && (
          <span className={`icon-tile ${tone}`} aria-hidden="true">
            {icon}
          </span>
        )}
      </div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function initials(name: string | null | undefined): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return ((parts[0][0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

/** Initials avatar with a stable colour per name. */
export function Avatar({ name, size }: { name: string | null | undefined; size?: "sm" | "lg" }) {
  const n = name ?? "";
  let hash = 0;
  for (let i = 0; i < n.length; i++) hash = (hash * 31 + n.charCodeAt(i)) >>> 0;
  const tone = hash % 5 === 0 ? "" : `c${hash % 5}`;
  return (
    <span className={`avatar ${size ?? ""} ${tone}`} aria-hidden="true">
      {initials(n)}
    </span>
  );
}

// ----------------------------------------------------------------- buttons

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md";
  loading?: boolean;
  block?: boolean;
};

export function Button({ variant = "secondary", size = "md", loading, block, className = "", children, disabled, ...rest }: ButtonProps) {
  const classes = [
    "btn",
    variant !== "secondary" ? `btn-${variant}` : "",
    size === "sm" ? "btn-sm" : "",
    block ? "btn-block" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button type="button" className={classes} disabled={disabled || loading} aria-busy={loading || undefined} {...rest}>
      {loading && <span className="spinner" aria-hidden="true" />}
      {children}
    </button>
  );
}

// ------------------------------------------------------------------- forms

export function Field({
  label,
  error,
  hint,
  children,
  htmlFor,
}: {
  label: string;
  error?: string;
  hint?: ReactNode;
  children: ReactNode;
  htmlFor: string;
}) {
  return (
    <div className="field">
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && !error && (
        <span className="hint" id={`${htmlFor}-hint`}>
          {hint}
        </span>
      )}
      {error && (
        <span className="error" id={`${htmlFor}-error`} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

type TextInputProps = InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string; hint?: ReactNode };

export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(function TextInput(
  { label, error, hint, id, className = "", ...rest },
  ref,
) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const describedBy = error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined;
  return (
    <Field label={label} error={error} hint={hint} htmlFor={inputId}>
      <input
        ref={ref}
        id={inputId}
        className={`input ${className}`}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        {...rest}
      />
    </Field>
  );
});

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & { label: string; error?: string; hint?: ReactNode };

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, error, hint, id, children, ...rest },
  ref,
) {
  const autoId = useId();
  const inputId = id ?? autoId;
  return (
    <Field label={label} error={error} hint={hint} htmlFor={inputId}>
      <select
        ref={ref}
        id={inputId}
        className="select"
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined}
        {...rest}
      >
        {children}
      </select>
    </Field>
  );
});

type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; error?: string; hint?: ReactNode };

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, error, hint, id, ...rest },
  ref,
) {
  const autoId = useId();
  const inputId = id ?? autoId;
  return (
    <Field label={label} error={error} hint={hint} htmlFor={inputId}>
      <textarea
        ref={ref}
        id={inputId}
        className="textarea"
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined}
        {...rest}
      />
    </Field>
  );
});

type CheckboxProps = InputHTMLAttributes<HTMLInputElement> & { label: ReactNode; hint?: ReactNode };

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox({ label, hint, id, ...rest }, ref) {
  const autoId = useId();
  const inputId = id ?? autoId;
  return (
    <div className="field">
      <label className="checkbox" htmlFor={inputId} style={{ fontWeight: 400 }}>
        <input ref={ref} id={inputId} type="checkbox" {...rest} />
        <span>
          {label}
          {hint && (
            <span className="hint" style={{ display: "block" }}>
              {hint}
            </span>
          )}
        </span>
      </label>
    </div>
  );
});

/** Copy server-side field errors onto react-hook-form fields; returns the general message. */
export function applyServerErrors<T extends FieldValues>(
  err: unknown,
  setError: UseFormSetError<T>,
  fieldMap: Record<string, string> = {},
): string {
  if (err instanceof ApiError) {
    for (const [field, message] of Object.entries(err.fields)) {
      setError((fieldMap[field] ?? field) as Path<T>, { type: "server", message });
    }
    return err.message;
  }
  return "Something went wrong. Please try again.";
}

// ------------------------------------------------------------------ alerts

export function Alert({
  kind = "info",
  title,
  children,
}: {
  kind?: "info" | "success" | "error" | "warning";
  title?: string;
  children?: ReactNode;
}) {
  const Icon = kind === "success" ? CheckCircle2 : kind === "info" ? Info : AlertCircle;
  return (
    <div className={`alert alert-${kind}`} role={kind === "error" ? "alert" : "status"}>
      <Icon size={18} aria-hidden="true" />
      <div>
        {title && <strong style={{ display: "block" }}>{title}</strong>}
        {children}
      </div>
    </div>
  );
}

export function ErrorMessage({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return <Alert kind="error">{message}</Alert>;
}

// ------------------------------------------------------------------ states

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      {icon}
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action}
    </div>
  );
}

/** Render loading / error states for a query, or the children when data is ready. */
export function QueryState({
  isLoading,
  error,
  children,
}: {
  isLoading: boolean;
  error: unknown;
  children: ReactNode;
}) {
  if (isLoading) return <Loading />;
  if (error)
    return (
      <div className="card-body">
        <ErrorMessage error={error} />
      </div>
    );
  return <>{children}</>;
}

const STATUS_KIND: Record<string, string> = {
  active: "s-success",
  redeemed: "s-success",
  rewarded: "s-success",
  accepted: "s-success",
  issued: "s-info",
  signed_up: "s-info",
  qualified: "s-info",
  pending: "s-info",
  created: "",
  paused: "s-warning",
  draft: "s-warning",
  inactive: "s-warning",
  expired: "s-warning",
  deactivated: "s-warning",
  archived: "",
  cancelled: "s-danger",
  rejected: "s-danger",
  revoked: "s-danger",
  anonymized: "",
};

export function Status({ value, label }: { value: string; label?: string }) {
  const text = label ?? value.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
  return <span className={`status ${STATUS_KIND[value] ?? ""}`}>{text}</span>;
}

export function Pagination({
  page,
  pages,
  total,
  onPage,
}: {
  page: number;
  pages: number;
  total: number;
  onPage: (p: number) => void;
}) {
  return (
    <nav className="pagination" aria-label="Pagination">
      <span className="muted">
        Page {page} of {pages} · {total} total
      </span>
      <div className="row">
        <Button size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </Button>
        <Button size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
        </Button>
      </div>
    </nav>
  );
}

// ------------------------------------------------------------------- modal

export function Modal({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }
    if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }
  }, [open]);
  return (
    <dialog ref={ref} className="modal" aria-labelledby={titleId} onClose={onClose} onCancel={onClose}>
      {open && (
        <>
          <div className="modal-header">
            <h2 id={titleId}>{title}</h2>
            <button type="button" className="icon-button" onClick={onClose} aria-label="Close dialog">
              <X size={18} />
            </button>
          </div>
          <div className="modal-body">{children}</div>
        </>
      )}
    </dialog>
  );
}
