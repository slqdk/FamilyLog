import type { FmField, FmFieldValue } from './types';

/** The one loud element on the page: a 1-100 score as a big number with a
    bar underneath showing where it sits. `size` sm for list rows. */
export function Score({ value, size = 'lg', label }: {
  value: number | null; size?: 'sm' | 'lg'; label?: string;
}) {
  return (
    <span className={`fm-score fm-score-${size}${value == null ? ' fm-score-none' : ''}`}
          aria-label={value == null ? 'Ingen karakter endnu'
            : `${label ?? 'Karakter'} ${value} af 100`}>
      <span className="fm-score-num">{value ?? '–'}</span>
      <span className="fm-score-bar"><span style={{ width: `${value ?? 0}%` }} /></span>
    </span>
  );
}

/** 1-100 with a slider for the rough value and − / + for the exact one; a
    phone's slider moves three pixels per point, which nobody can hit. */
export function ScoreInput({ label, value, onChange, required }: {
  label: string; value: number | null; onChange: (v: number | null) => void;
  required?: boolean;
}) {
  const v = value ?? 50;
  const step = (d: number) => onChange(Math.min(100, Math.max(1, v + d)));
  return (
    <div className={`fm-scorein${value == null ? ' unset' : ''}`}>
      <div className="fm-scorein-head">
        <span className="fm-label">{label}{required && <span className="fm-req"> *</span>}</span>
        {value != null && !required && (
          <button type="button" className="fm-clear" aria-label={`Fjern ${label}`}
                  title="Fjern" onClick={() => onChange(null)}>✕</button>
        )}
      </div>
      <div className="fm-scorein-row">
        <button type="button" className="fm-step" aria-label={`${label} minus 1`}
                onClick={() => step(-1)}>−</button>
        <input type="range" min={1} max={100} value={v} aria-label={label}
               onChange={(e) => onChange(Number(e.target.value))}
               onClick={() => { if (value == null) onChange(v); }} />
        <button type="button" className="fm-step" aria-label={`${label} plus 1`}
                onClick={() => step(1)}>+</button>
        {/* Unscored says so in words: a pale "–" next to a slider resting at
            50 read as a score of 50. (2.50.2) */}
        {value == null
          ? <span className="fm-scorein-num fm-scorein-none">Ikke vurderet</span>
          : <span className="fm-scorein-num">{value}</span>}
      </div>
    </div>
  );
}

/** A tap-again-to-clear choice between a few words (Ja/Nej, Billig/Middel/Dyr). */
function Segments<T extends string | boolean>({ options, value, onChange }: {
  options: { value: T; label: string }[]; value: T | null; onChange: (v: T | null) => void;
}) {
  return (
    <div className="fm-seg" role="group">
      {options.map((o) => (
        <button key={String(o.value)} type="button"
                className={value === o.value ? 'on' : ''} aria-pressed={value === o.value}
                onClick={() => onChange(value === o.value ? null : o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function YesNo({ value, onChange }: {
  value: boolean | null; onChange: (v: boolean | null) => void;
}) {
  return <Segments options={[{ value: true, label: 'Ja' }, { value: false, label: 'Nej' }]}
                   value={value} onChange={onChange} />;
}

export function FieldInput({ field, value, onChange }: {
  field: FmField; value: FmFieldValue | null | undefined;
  onChange: (v: FmFieldValue | null) => void;
}) {
  const v = value ?? null;
  if (field.kind === 'rating') {
    return <ScoreInput label={field.label} value={typeof v === 'number' ? v : null}
                       onChange={onChange} />;
  }
  return (
    <div className="fm-field">
      <span className="fm-label">{field.label}</span>
      {field.kind === 'bool' ? (
        <YesNo value={typeof v === 'boolean' ? v : null} onChange={onChange} />
      ) : field.kind === 'choice' ? (
        <Segments options={(field.options ?? []).map((o) => ({ value: o, label: o }))}
                  value={typeof v === 'string' ? v : null} onChange={onChange} />
      ) : (
        <input value={typeof v === 'string' ? v : ''} maxLength={200} placeholder={field.placeholder}
               onChange={(e) => onChange(e.target.value)} />
      )}
    </div>
  );
}

/** A review field's value as words, for reading a review back. */
export function fieldText(field: FmField, v: FmFieldValue): string {
  if (field.kind === 'bool') return v ? 'Ja' : 'Nej';
  return String(v);
}
