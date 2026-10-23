import { useId } from "react";
import { MONTHS } from "../lib/format";

/** Optional birthday (month + day, no year). Values are strings so they work with form libraries. */
export function BirthdayFields({
  month,
  day,
  onChange,
  error,
  hint = "Optional. Used only for a birthday bonus; we don't ask for the year.",
}: {
  month: string;
  day: string;
  onChange: (month: string, day: string) => void;
  error?: string;
  hint?: string;
}) {
  const id = useId();
  const daysInMonth = month ? new Date(2024, Number(month), 0).getDate() : 31;
  return (
    <fieldset className="fieldset" aria-describedby={`${id}-hint`}>
      <legend className="small" style={{ fontWeight: 500, marginBottom: 4 }}>
        Birthday
      </legend>
      <div className="row">
        <label className="visually-hidden" htmlFor={`${id}-m`}>
          Birth month
        </label>
        <select id={`${id}-m`} className="select" style={{ width: "auto" }} value={month} onChange={(e) => onChange(e.target.value, e.target.value ? day : "")}>
          <option value="">Month</option>
          {MONTHS.map((m, i) => (
            <option key={m} value={i + 1}>
              {m}
            </option>
          ))}
        </select>
        <label className="visually-hidden" htmlFor={`${id}-d`}>
          Birth day
        </label>
        <select id={`${id}-d`} className="select" style={{ width: "auto" }} value={day} disabled={!month} onChange={(e) => onChange(month, e.target.value)}>
          <option value="">Day</option>
          {Array.from({ length: daysInMonth }, (_, i) => i + 1).map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      </div>
      {error ? (
        <span className="error" role="alert">
          {error}
        </span>
      ) : (
        <span className="hint" id={`${id}-hint`}>
          {hint}
        </span>
      )}
    </fieldset>
  );
}

export function birthdayPayload(month: string, day: string) {
  return month && day ? { birth_month: Number(month), birth_day: Number(day) } : { birth_month: null, birth_day: null };
}
