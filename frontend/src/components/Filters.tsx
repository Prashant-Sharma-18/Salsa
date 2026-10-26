import { useId } from "react";
import { useLocations } from "../api/hooks";
import { daysAgo, isoDate } from "../lib/format";

export interface RangeValue {
  start: string;
  end: string;
  location_id: string;
}

export function defaultRange(days = 30): RangeValue {
  return { start: daysAgo(days - 1), end: isoDate(new Date()), location_id: "" };
}

const PRESETS = [
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
];

/** Compact one-line filter bar: preset ranges, custom dates and location. */
export function RangeFilter({ value, onChange }: { value: RangeValue; onChange: (v: RangeValue) => void }) {
  const id = useId();
  const locations = useLocations();
  const accessible = (locations.data ?? []).filter((l) => l.accessible !== false);
  const today = isoDate(new Date());
  const activePreset = PRESETS.find((p) => value.end === today && value.start === daysAgo(p.days - 1))?.days;

  return (
    <div className="filter-bar" role="group" aria-label="Filters">
      <div className="segmented" role="group" aria-label="Date range presets">
        {PRESETS.map((p) => (
          <button
            key={p.days}
            type="button"
            aria-pressed={activePreset === p.days}
            onClick={() => onChange({ ...defaultRange(p.days), location_id: value.location_id })}
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="date-range">
        <label className="visually-hidden" htmlFor={`${id}-start`}>
          From
        </label>
        <input
          id={`${id}-start`}
          type="date"
          className="input"
          value={value.start}
          max={value.end}
          onChange={(e) => e.target.value && onChange({ ...value, start: e.target.value })}
        />
        <span aria-hidden="true">to</span>
        <label className="visually-hidden" htmlFor={`${id}-end`}>
          To
        </label>
        <input
          id={`${id}-end`}
          type="date"
          className="input"
          value={value.end}
          min={value.start}
          onChange={(e) => e.target.value && onChange({ ...value, end: e.target.value })}
        />
      </div>
      {accessible.length > 1 && (
        <>
          <label className="visually-hidden" htmlFor={`${id}-loc`}>
            Location
          </label>
          <select
            id={`${id}-loc`}
            className="select"
            value={value.location_id}
            onChange={(e) => onChange({ ...value, location_id: e.target.value })}
          >
            <option value="">All my locations</option>
            {accessible.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </>
      )}
    </div>
  );
}
