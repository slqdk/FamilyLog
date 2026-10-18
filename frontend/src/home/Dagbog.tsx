import { useEffect, useState } from 'react';
import { homeApi, type DagbogConfig, type DagbogEntry, type DagbogField } from './api';
import { addDays, dayTitle, routeHash, todayLocal } from './logic';

/** Dagbog (FamilyLog 0.2.0): rate the day in a minute. The family sees your
    days - since 0.3.9 the text and photo too, unless you keep a day to
    yourself; the page says which where you write them. A user account's
    days are its own. */

type Draft = {
  mood: number | null; mental: number | null; alcohol: number | null; exercise: number | null; soda: number | null;
  foods: string[]; tags: string[]; sick: string[]; sickNote: string; highlight: string; shared: boolean;
};
const EMPTY: Draft = { mood: null, mental: null, alcohol: null, exercise: null, soda: null, foods: [], tags: [],
  sick: [], sickNote: '', highlight: '', shared: true };

function toDraft(e: DagbogEntry | null): Draft {
  if (!e) return { ...EMPTY, foods: [], tags: [], sick: [] };
  return { mood: e.mood, mental: e.mental, alcohol: e.alcohol, exercise: e.exercise ?? null, soda: e.soda ?? null,
           foods: [...(e.foods ?? [])], tags: [...e.tags], sick: [...(e.sick ?? [])], sickNote: e.sickNote ?? '',
           highlight: e.highlight ?? '', shared: e.shared ?? true };
}

/** 90 -> "1½ t" (motion is kept in minutes, set in half hours). */
export function hoursText(min: number): string {
  const h = Math.floor(min / 60);
  const half = min % 60 >= 30;
  return `${h === 0 && half ? '' : h}${half ? '½' : ''} t`;
}

export function Bar({ title, back = '#/' }: { title: string; back?: string }) {
  return (
    <header className="fm-bar">
      <a className="fm-back" aria-label="Tilbage" href={back}>
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden>
          <path d="M15 5 L8 12 L15 19" fill="none" stroke="currentColor" strokeWidth="2.6"
                strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </a>
      <span className="fm-bar-title">{title}</span>
    </header>
  );
}

/** "Familien" is for the family - family accounts and the administrator
    (0.3.7); a user account sees only its own days. */
export function isFamily(role: string | undefined) { return role === 'admin' || role === 'family'; }

export function Tabs({ on, role }: { on: 'mine' | 'family'; role?: string }) {
  if (on === 'mine' && role && !isFamily(role)) return null;
  return (
    <nav className="hm-tabs" aria-label="Dagbog">
      <a className={on === 'mine' ? 'on' : ''} href={routeHash({ name: 'dagbog', day: null })}>Min dag</a>
      <a className={on === 'family' ? 'on' : ''} href={routeHash({ name: 'family', person: null })}>Familien</a>
    </nav>
  );
}

export function DagbogPage({ day, role }: { day: string; role?: string }) {
  const today = todayLocal();
  const [cfg, setCfg] = useState<DagbogConfig | null>(null);
  const [saved, setSaved] = useState<DagbogEntry | null | undefined>(undefined);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [photoV, setPhotoV] = useState('');

  useEffect(() => { homeApi.dagbogConfig().then(setCfg).catch((e) => setError(e.message)); }, []);
  useEffect(() => {
    setSaved(undefined); setNote(null); setError(null);
    homeApi.entry(day).then(({ entry }) => {
      setSaved(entry); setDraft(toDraft(entry)); setPhotoV(entry?.updatedAt ?? '');
    }).catch((e) => setError(e.message));
  }, [day]);

  const dirty = saved !== undefined && JSON.stringify(draft) !== JSON.stringify(toDraft(saved));
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => { setNote(null); setDraft((d) => ({ ...d, [k]: v })); };

  async function save() {
    setBusy(true); setError(null);
    try {
      const { entry } = await homeApi.saveEntry({ day, ...draft });
      setSaved(entry); setDraft(toDraft(entry)); setNote('Gemt ✓');
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function photo(file: File | undefined) {
    if (!file) return;
    setBusy(true); setError(null);
    try {
      if (dirty) await save();
      const { entry } = await homeApi.uploadPhoto(day, file);
      setSaved(entry); setDraft(toDraft(entry)); setPhotoV(entry.updatedAt);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  const prev = addDays(day, -1);
  const next = addDays(day, 1);
  const fields = cfg?.fields ?? [];
  return (
    <div className="fm-page hm-page">
      <Bar title="Dagbog" />
      <Tabs on="mine" role={role} />
      <div className="hm-daynav">
        <a className="hm-step" aria-label="Dagen før" href={routeHash({ name: 'dagbog', day: prev })}>‹</a>
        <span className="hm-dayname">{dayTitle(day, today)}</span>
        {next <= today
          ? <a className="hm-step" aria-label="Dagen efter" href={routeHash({ name: 'dagbog', day: next })}>›</a>
          : <span className="hm-step hm-step-off" aria-hidden>›</span>}
      </div>
      <main className="hm-form">
        {(!cfg || saved === undefined) && !error && <p className="fm-note">Henter…</p>}
        {error && <p className="fm-error">{error}</p>}
        {cfg && saved !== undefined && fields.map((f) => (
          <FieldBox key={f.key} f={f} draft={draft} set={set} lists={{ tags: cfg.tags, foods: cfg.foods }} day={day}
                    family={!role || isFamily(role)}
                    hasPhoto={!!saved?.hasPhoto} photoV={photoV} busy={busy}
                    onPhoto={photo}
                    onRemovePhoto={async () => {
                      const { entry } = await homeApi.deletePhoto(day);
                      setSaved(entry); setDraft(toDraft(entry));
                    }} />
        ))}
        {cfg && saved && (
          <button className="fm-link fm-danger hm-delete" disabled={busy} onClick={async () => {
            if (!confirm('Slet hele dagen?')) return;
            await homeApi.deleteEntry(day);
            setSaved(null); setDraft({ ...EMPTY, foods: [], tags: [], sick: [] }); setNote('Dagen er slettet.');
          }}>Slet dagen</button>
        )}
      </main>
      <footer className="fm-bottom">
        <button className="fm-primary hm-save" disabled={busy || !dirty} onClick={() => void save()}>
          {busy ? 'Gemmer…' : dirty ? 'Gem dagen' : note ?? (saved ? 'Gemt ✓' : 'Gem dagen')}
        </button>
      </footer>
    </div>
  );
}

/** A scale or an amount as a slider (0.3.7 Mentalt overskud; 0.3.8 motion in
    half hours, sodavand, alkohol). Untouched it says so and sits faded; the
    first touch - a tap or a drag - sets it. */
function SliderField({ f, value, min, top, step, onChange }: {
  f: DagbogField; value: number | null; min: number; top: number; step: number; onChange: (v: number | null) => void;
}) {
  const hours = f.format === 'hours';
  const unit = (v: number) => (v === 1 && f.unit === 'genstande' ? 'genstand' : f.unit ?? '');
  const fmt = (v: number) => hours ? hoursText(v) : min === 1 ? `${v}/${top}` : `${v} ${unit(v)}`.trim();
  const shown = value ?? (min === 1 ? Math.ceil(top / 2) : min);
  const pct = ((Math.min(shown, top) - min) / (top - min)) * 100;
  const count = (top - min) / step;
  const every = hours ? 120 / step : count > 12 ? 5 : 1;            // a label every 2 hours, 5 units, or each
  const ticks = Array.from({ length: Math.floor(count / every) + 1 }, (_, i) => min + i * every * step);
  return (
    <section className="fm-sheet hm-field" aria-label={f.label}>
      <div className="hm-slider-head">
        <h3 className="hm-field-label">{f.label}</h3>
        <span className={`hm-slider-value${value == null ? ' hm-unset' : ''}`} aria-hidden>
          {value == null ? 'Træk for at vælge' : fmt(value)}
        </span>
      </div>
      {f.hint && <p className="hm-hint">{f.hint}</p>}
      <div className={`hm-slider${value == null ? ' hm-unset' : ''}`} style={{ '--pct': `${pct}%` } as React.CSSProperties}>
        <input type="range" min={min} max={top} step={step} value={Math.min(shown, top)} aria-label={f.label}
               aria-valuetext={value == null ? 'Ikke valgt' : min === 1 ? `${value} af ${top}` : fmt(value)}
               onChange={(e) => onChange(Number(e.target.value))}
               onPointerUp={(e) => { if (value == null) onChange(Number((e.target as HTMLInputElement).value)); }}
               onKeyUp={(e) => { if (value == null) onChange(Number((e.target as HTMLInputElement).value)); }} />
        <div className="hm-slider-ticks" aria-hidden>
          {ticks.map((t) => <span key={t} className={value === t ? 'on' : ''}>{hours ? t / 60 : t}{t === top && !hours && min === 0 ? '+' : ''}</span>)}
        </div>
      </div>
      <div className="hm-scale-ends"><span>{f.low ?? (hours ? 'timer' : '')}</span>
        {value != null && <button className="fm-link hm-slider-clear" onClick={() => onChange(null)}>Nulstil</button>}
        <span>{f.high}</span></div>
    </section>
  );
}

function FieldBox({ f, draft, set, lists, day, family, hasPhoto, photoV, busy, onPhoto, onRemovePhoto }: {
  f: DagbogField; draft: Draft; set: <K extends keyof Draft>(k: K, v: Draft[K]) => void; family: boolean;
  lists: { tags: string[]; foods: string[] }; day: string; hasPhoto: boolean; photoV: string; busy: boolean;
  onPhoto: (f: File | undefined) => void; onRemovePhoto: () => void;
}) {
  const key = f.key as keyof Draft;
  if (f.kind === 'scale') {
    const value = draft[key] as number | null;
    const top = f.max ?? 5;                       // mood 1-5, mentalt overskud 1-10 (0.2.2)
    if (top > 5) return <SliderField f={f} value={value} min={1} top={top} step={1} onChange={(v) => set(key, v as never)} />;
    return (
      <section className="fm-sheet hm-field" aria-label={f.label}>
        <h3 className="hm-field-label">{f.label}</h3>
        <div className={`hm-scale${f.faces ? ' hm-faces' : ''}${top > 5 ? ' hm-scale-long' : ''}`}
             role="radiogroup" aria-label={f.label}>
          {Array.from({ length: top }, (_, i) => i + 1).map((n) => (
            <button key={n} role="radio" aria-checked={value === n} className={value === n ? 'on' : ''}
                    aria-label={`${f.label} ${n}`}
                    onClick={() => set(key, (value === n ? null : n) as never)}>
              {f.faces ? f.faces[n - 1] : n}
            </button>
          ))}
        </div>
        <div className="hm-scale-ends"><span>{f.low}</span><span>{f.high}</span></div>
      </section>
    );
  }
  if (f.kind === 'slider') {
    const k = key as 'exercise' | 'soda' | 'alcohol';
    return <SliderField f={f} value={draft[k]} min={f.min ?? 0} top={f.max ?? 10} step={f.step ?? 1}
                        onChange={(v) => set(k, v)} />;
  }
  if (f.kind === 'sick') {
    return (
      <section className="fm-sheet hm-field" aria-label={f.label}>
        <h3 className="hm-field-label">{f.label}</h3>
        {f.hint && <p className="hm-hint">{f.hint}</p>}
        <div className="hm-tags">
          {(f.options ?? []).map((t) => {
            const on = draft.sick.includes(t);
            return <button key={t} className={on ? 'on' : ''} aria-pressed={on}
                           onClick={() => set('sick', on ? draft.sick.filter((x) => x !== t) : [...draft.sick, t])}>{t}</button>;
          })}
        </div>
        {draft.sick.length > 0 && (
          <input className="hm-text hm-sick-note" maxLength={200} placeholder="Hvad skete der? (familien kan se det)"
                 aria-label="Om sygdommen" value={draft.sickNote} onChange={(e) => set('sickNote', e.target.value)} />
        )}
      </section>
    );
  }
  if (f.kind === 'count') {
    const v = draft.alcohol;
    return (
      <section className="fm-sheet hm-field" aria-label={f.label}>
        <h3 className="hm-field-label">{f.label}</h3>
        <div className="hm-count">
          <button aria-label="Færre" onClick={() => set('alcohol', v == null ? 0 : Math.max(0, v - 1))}>−</button>
          <span className="hm-count-value">{v == null ? '–' : v}<small> {f.unit}</small></span>
          <button aria-label="Flere" onClick={() => set('alcohol', v == null ? 1 : Math.min(f.max ?? 30, v + 1))}>+</button>
          {v != null && <button className="fm-clear" aria-label="Ryd" onClick={() => set('alcohol', null)}>✕</button>}
        </div>
      </section>
    );
  }
  if (f.kind === 'tags' || f.kind === 'foods') {
    // Activities and food: tap what fits the day - the lists are the admin's.
    const name = f.kind;
    const picked = draft[name];
    return (
      <section className="fm-sheet hm-field" aria-label={f.label}>
        <h3 className="hm-field-label">{f.label}</h3>
        {f.hint && <p className="hm-hint">{f.hint}</p>}
        <div className="hm-tags">
          {lists[name].map((t) => {
            const on = picked.includes(t);
            return (
              <button key={t} className={on ? 'on' : ''} aria-pressed={on}
                      onClick={() => set(name, on ? picked.filter((x) => x !== t) : [...picked, t])}>{t}</button>
            );
          })}
        </div>
      </section>
    );
  }
  return (
    <section className="fm-sheet hm-field" aria-label={f.label}>
      <h3 className="hm-field-label">{f.label}</h3>
      {family ? (
        // 0.3.9: the family sees the text and the photo - unless this day is kept to yourself.
        <label className="hm-share">
          <input type="checkbox" checked={draft.shared} onChange={(e) => set('shared', e.target.checked)} />
          <span>{draft.shared ? '👪 Familien kan se teksten og billedet' : '🔒 Kun du kan se teksten og billedet'}</span>
        </label>
      ) : <p className="hm-private">🔒 Kun du kan se teksten og billedet.</p>}
      <textarea className="hm-text" rows={3} maxLength={2000} value={draft.highlight}
                placeholder="Hvad var det bedste ved dagen?"
                onChange={(e) => set('highlight', e.target.value)} />
      {hasPhoto && (
        <div className="hm-photo">
          <img src={homeApi.photoUrl(day, photoV)} alt="Dagens billede" />
          <button className="fm-link fm-danger" disabled={busy} onClick={onRemovePhoto}>Fjern billedet</button>
        </div>
      )}
      <label className="fm-secondary hm-photo-pick">
        {hasPhoto ? 'Skift billedet' : 'Tilføj et billede'}
        <input type="file" accept="image/*" hidden disabled={busy}
               onChange={(e) => { onPhoto(e.target.files?.[0]); e.target.value = ''; }} />
      </label>
    </section>
  );
}

// ---- shared with Dagbog → Familien (DagbogFamily.tsx) ----------------------------------

export function Dots({ n, max }: { n: number; max: number }) {
  return (
    <span className="hm-dots" aria-label={`${n} af ${max}`}>
      {Array.from({ length: max }, (_, i) => i + 1).map((i) => <span key={i} className={i <= n ? 'on' : ''} />)}
      <b>{n}/{max}</b>
    </span>
  );
}

/** ISO week number. */
export function weekNumber(day: string): number {
  const [y, m, d] = day.split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d));
  const wd = (t.getUTCDay() + 6) % 7;
  t.setUTCDate(t.getUTCDate() - wd + 3);
  const first = new Date(Date.UTC(t.getUTCFullYear(), 0, 4));
  return 1 + Math.round(((t.getTime() - first.getTime()) / 86400000 - 3 + ((first.getUTCDay() + 6) % 7)) / 7);
}
