import { useEffect, useMemo, useState } from 'react';
import type { FmUser } from '../sections/familymap/phone/types';
import { homeApi, type DagbogConfig, type DagbogEntry, type DagbogFamily, type DagbogField } from './api';
import { addDays, dayTitle, face, mean, routeHash, shortDay, todayLocal, weekStart } from './logic';

/** Dagbog (FamilyLog 0.2.0): rate the day in a minute. The family sees the
    ratings and activities; the highlight text and photo are yours alone -
    the page says so where you write them. */

type Draft = {
  mood: number | null; mental: number | null; alcohol: number | null;
  foods: string[]; tags: string[]; highlight: string;
};
const EMPTY: Draft = { mood: null, mental: null, alcohol: null, foods: [], tags: [], highlight: '' };

function toDraft(e: DagbogEntry | null): Draft {
  if (!e) return { ...EMPTY, foods: [], tags: [] };
  return { mood: e.mood, mental: e.mental, alcohol: e.alcohol, foods: [...(e.foods ?? [])],
           tags: [...e.tags], highlight: e.highlight ?? '' };
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

function Tabs({ on }: { on: 'mine' | 'family' }) {
  return (
    <nav className="hm-tabs" aria-label="Dagbog">
      <a className={on === 'mine' ? 'on' : ''} href={routeHash({ name: 'dagbog', day: null })}>Min dag</a>
      <a className={on === 'family' ? 'on' : ''} href={routeHash({ name: 'family', week: null })}>Familien</a>
    </nav>
  );
}

export function DagbogPage({ day }: { day: string }) {
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
      <Tabs on="mine" />
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
            setSaved(null); setDraft({ ...EMPTY, foods: [], tags: [] }); setNote('Dagen er slettet.');
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

function FieldBox({ f, draft, set, lists, day, hasPhoto, photoV, busy, onPhoto, onRemovePhoto }: {
  f: DagbogField; draft: Draft; set: <K extends keyof Draft>(k: K, v: Draft[K]) => void;
  lists: { tags: string[]; foods: string[] }; day: string; hasPhoto: boolean; photoV: string; busy: boolean;
  onPhoto: (f: File | undefined) => void; onRemovePhoto: () => void;
}) {
  const key = f.key as keyof Draft;
  if (f.kind === 'scale') {
    const value = draft[key] as number | null;
    return (
      <section className="fm-sheet hm-field" aria-label={f.label}>
        <h3 className="hm-field-label">{f.label}</h3>
        <div className={`hm-scale${f.faces ? ' hm-faces' : ''}`} role="radiogroup" aria-label={f.label}>
          {[1, 2, 3, 4, 5].map((n) => (
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
      <p className="hm-private">🔒 Kun du kan se teksten og billedet.</p>
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

// ---- the family's week -----------------------------------------------------------------

const SCALE_KEYS: [keyof DagbogEntry, string][] = [['mental', 'Mentalt overskud']];

export function FamilyWeek({ me, week }: { me: FmUser; week: string | null }) {
  const today = todayLocal();
  const start = week ?? weekStart(today);
  const end = addDays(start, 6);
  const [data, setData] = useState<DagbogFamily | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pick, setPick] = useState<{ userId: number; day: string } | null>(null);

  useEffect(() => {
    setData(null); setPick(null);
    homeApi.family(start, end).then(setData).catch((e) => setError(e.message));
  }, [start, end]);

  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(start, i)), [start]);
  const byKey = useMemo(() => new Map((data?.entries ?? []).map((e) => [`${e.userId}|${e.day}`, e])), [data]);
  const picked = pick ? byKey.get(`${pick.userId}|${pick.day}`) ?? null : null;
  const pickedName = data?.members.find((m) => m.id === pick?.userId)?.username;

  return (
    <div className="fm-page hm-page">
      <Bar title="Dagbog" />
      <Tabs on="family" />
      <div className="hm-daynav">
        <a className="hm-step" aria-label="Ugen før" href={routeHash({ name: 'family', week: addDays(start, -7) })}>‹</a>
        <span className="hm-dayname">Uge {weekNumber(start)}</span>
        {addDays(start, 7) <= today
          ? <a className="hm-step" aria-label="Ugen efter" href={routeHash({ name: 'family', week: addDays(start, 7) })}>›</a>
          : <span className="hm-step hm-step-off" aria-hidden>›</span>}
      </div>
      <main className="hm-form">
        {error && <p className="fm-error">{error}</p>}
        {!data && !error && <p className="fm-note">Henter…</p>}
        {data && (
          <div className="fm-sheet hm-week">
            <table>
              <thead>
                <tr><th />{days.map((d) => <th key={d} className={d === today ? 'hm-today' : ''}>{shortDay(d)}</th>)}<th>Ø</th></tr>
              </thead>
              <tbody>
                {data.members.map((m) => {
                  const avg = mean(days.map((d) => byKey.get(`${m.id}|${d}`)?.mood));
                  return (
                    <tr key={m.id}>
                      <th scope="row">{m.id === me.id ? 'Mig' : m.username}</th>
                      {days.map((d) => {
                        const e = byKey.get(`${m.id}|${d}`);
                        const on = pick?.userId === m.id && pick.day === d;
                        return (
                          <td key={d}>
                            <button className={`hm-cell${on ? ' on' : ''}${e ? '' : ' hm-empty'}`}
                                    disabled={!e} aria-label={`${m.username} ${shortDay(d)}`}
                                    onClick={() => setPick(on ? null : { userId: m.id, day: d })}>
                              {e ? face(e.mood) : '·'}
                            </button>
                          </td>
                        );
                      })}
                      <td className="hm-avg">{avg == null ? '' : face(avg)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {picked && (
          <section className="fm-sheet hm-detail" aria-label="Dagen">
            <h3 className="hm-field-label">{pick?.userId === me.id ? 'Mig' : pickedName} · {dayTitle(picked.day, today)}</h3>
            <p className="hm-detail-mood">{face(picked.mood)} {picked.mood ? `Humør ${picked.mood}/5` : 'Humør ikke angivet'}</p>
            <dl className="fm-fieldlist">
              {SCALE_KEYS.filter(([k]) => picked[k] != null).map(([k, label]) => (
                <div key={k}><dt>{label}</dt><dd><Dots n={picked[k] as number} /></dd></div>
              ))}
              {picked.alcohol != null && <div><dt>Alkohol</dt><dd>{picked.alcohol} genstande</dd></div>}
            </dl>
            {(picked.foods ?? []).length > 0 && (
              <><p className="hm-detail-label">Mad</p>
                <div className="hm-tags hm-tags-ro">{picked.foods.map((t) => <span key={t}>{t}</span>)}</div></>
            )}
            {picked.tags.length > 0 && (
              <><p className="hm-detail-label">Aktiviteter</p>
                <div className="hm-tags hm-tags-ro">{picked.tags.map((t) => <span key={t}>{t}</span>)}</div></>
            )}
            {pick?.userId === me.id
              ? <a className="fm-link" href={routeHash({ name: 'dagbog', day: picked.day })}>Åbn din dag</a>
              : <p className="fm-dim">Teksten og billedet er kun for {pickedName}.</p>}
          </section>
        )}
      </main>
    </div>
  );
}

function Dots({ n }: { n: number }) {
  return (
    <span className="hm-dots" aria-label={`${n} af 5`}>
      {[1, 2, 3, 4, 5].map((i) => <span key={i} className={i <= n ? 'on' : ''} />)}
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
