import { useCallback, useEffect, useState } from 'react';
import {
  homeApi, type CyDay, type CyOptions, type CyOwn, type CyShared, type CyState, type DayKind, type Phase,
} from './api';
import {
  addDays, addMonths, dayOfMonth, dayTitle, monthGrid, monthTitle, routeHash, shortDate,
  todayLocal, weekStart, weekdayLetter,
} from './logic';

/** Cyklus (FamilyLog 0.3.0): her period log and forecast, in its own soft
    pink look. Only accounts set to female log; she chooses who sees her
    status (Deling). Everyone sees the cycles shared with them here. */

function days(n: number) { return n === 1 ? '1 dag' : `${n} dage`; }

function CyBar({ title, back = '#/', right }: { title: string; back?: string; right?: React.ReactNode }) {
  return (
    <header className="cy-bar">
      <a className="cy-round" aria-label="Tilbage" href={back}>
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden>
          <path d="M15 5 L8 12 L15 19" fill="none" stroke="currentColor" strokeWidth="2.6"
                strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </a>
      <span className="cy-bar-title">{title}</span>
      {right ?? <span className="cy-round cy-ghost" aria-hidden />}
    </header>
  );
}

const CalIcon = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden>
    <rect x="3.5" y="5" width="17" height="15" rx="3" fill="none" stroke="currentColor" strokeWidth="2" />
    <path d="M3.5 10h17M8 3v4M16 3v4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    <circle cx="8.5" cy="14" r="1.1" fill="currentColor" /><circle cx="12" cy="14" r="1.1" fill="currentColor" />
    <circle cx="15.5" cy="14" r="1.1" fill="currentColor" /><circle cx="8.5" cy="17" r="1.1" fill="currentColor" />
  </svg>
);

function useCy() {
  const [st, setSt] = useState<CyState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => homeApi.cyState().then(setSt).catch((e) => setError(e.message)), []);
  useEffect(() => { void load(); }, [load]);
  const setOwn = (own: CyOwn) => setSt((s) => (s ? { ...s, own } : s));
  return { st, error, setError, setOwn, load };
}

// ---- the strip of days ------------------------------------------------------------------------

function Strip({ list, today, link }: { list: { day: string; kind: DayKind }[]; today: string; link?: boolean }) {
  return (
    <div className="cy-strip">
      {list.map(({ day, kind }) => {
        const cls = `cy-dot cy-${kind || 'none'}${day === today ? ' cy-today' : ''}`;
        const inner = <><span className="cy-wd">{weekdayLetter(day)}</span><span className={cls}>{dayOfMonth(day)}</span></>;
        return link && day <= today
          ? <a key={day} className="cy-strip-day" href={routeHash({ name: 'cyklusDay', day })}
               aria-label={`${dayTitle(day, today)}${kind ? `: ${KIND_LABEL[kind]}` : ''}`}>{inner}</a>
          : <span key={day} className="cy-strip-day" aria-label={`${dayTitle(day, today)}${kind ? `: ${KIND_LABEL[kind]}` : ''}`}>{inner}</span>;
      })}
    </div>
  );
}

const KIND_LABEL: Record<DayKind, string> = {
  '': '', period: 'menstruation', predicted: 'forventet menstruation', fertile: 'frugtbar',
  ovulation: 'ægløsning', pms: 'PMS',
};

function Legend({ fertile = true }: { fertile?: boolean }) {
  return (
    <p className="cy-legend">
      <span><i className="cy-dot cy-period" />Menstruation</span>
      <span><i className="cy-dot cy-predicted" />Forventet</span>
      {fertile && <span><i className="cy-dot cy-fertile" />Frugtbar</span>}
      <span><i className="cy-dot cy-pms" />PMS</span>
    </p>
  );
}

// ---- the main page ----------------------------------------------------------------------------

export function CyklusPage() {
  const { st, error, setError, setOwn, load } = useCy();
  const [busy, setBusy] = useState(false);
  const today = todayLocal();

  async function act(fn: () => Promise<CyOwn>) {
    setBusy(true); setError(null);
    try { setOwn(await fn()); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div className="cy-page">
      <CyBar title="Cyklus" right={st?.enabled
        ? <a className="cy-round" aria-label="Kalender" href={routeHash({ name: 'cyklusCal', month: null })}><CalIcon /></a>
        : undefined} />
      {!st && !error && <p className="cy-note">Henter…</p>}
      {error && <p className="cy-error" role="alert">{error}</p>}
      {st?.enabled && st.own && <Own own={st.own} options={st.options} today={today} busy={busy} act={act} reload={load} />}
      {st && st.shared.length > 0 && (
        <section aria-label="Delt med dig">
          <h2 className="cy-h2">Delt med dig</h2>
          {st.shared.map((c) => <SharedCard key={c.id} c={c} />)}
        </section>
      )}
      {st && !st.enabled && st.shared.length === 0 && (
        <section className="cy-card"><p>Ingen deler deres cyklus med dig.</p>
          <p className="cy-dim">Cyklus er for konti, der er sat til kvinde. Hun vælger selv, hvem der kan se hendes status.</p></section>
      )}
      {st && <p className="cy-disclaimer">{st.options.disclaimer}</p>}
    </div>
  );
}

function Own({ own, options, today, busy, act, reload }: {
  own: CyOwn; options: CyOptions; today: string; busy: boolean;
  act: (fn: () => Promise<CyOwn>) => Promise<void>; reload: () => void;
}) {
  const s = own.status;
  const [week, setWeek] = useState<{ day: string; kind: DayKind }[]>([]);
  const [otherDay, setOtherDay] = useState(false);
  const [pick, setPick] = useState(today);
  const mon = weekStart(today);
  useEffect(() => {
    homeApi.cyCalendar(mon, addDays(mon, 6)).then((r) => setWeek(r.days)).catch(() => setWeek([]));
  }, [mon, s.lastStart, s.inPeriod, s.lastOpen, own.periods.length]);

  let big: string; let small = '';
  if (s.empty) { big = 'Velkommen'; small = 'Log starten på din seneste menstruation, så regner Cyklus resten ud.'; }
  else if (s.stale) { big = 'Log din seneste menstruation'; small = `Den sidste, der er logget, startede ${shortDate(s.lastStart!)} ${s.lastStart!.slice(0, 4)}.`; }
  else if (s.inPeriod) { big = `Menstruationsdag ${s.periodDay}`; small = `Cyklusdag ${s.cycleDay}`; }
  else if (s.late) { big = `${days(s.late)} forsinket`; small = `Menstruationen ventedes ${shortDate(addDays(today, -s.late))} · cyklusdag ${s.cycleDay}`; }
  else if (s.daysUntilNext === 0) { big = 'Menstruation i dag'; small = `Forventet · cyklusdag ${s.cycleDay}`; }
  else { big = `Menstruation om ${days(s.daysUntilNext ?? 0)}`; small = `Cyklusdag ${s.cycleDay} · ${s.phaseLabel}`; }
  const phase = s.phase;
  const pattern = phase ? own.patterns[phase === 'ovulation' ? 'fertile' : phase] : undefined;

  return (
    <>
      <Strip list={week} today={today} link />
      <section className="cy-hero" aria-label="I dag">
        <h1 className="cy-big">{big}</h1>
        <p className="cy-small">{small}</p>
        {s.phaseText && <p className="cy-phase-text">{s.phaseText}</p>}
        {s.askEnded && (
          <div className="cy-ask-ended">
            <span>Er din menstruation slut?</span>
            <button className="cy-pill cy-pill-soft" disabled={busy}
                    onClick={() => act(() => homeApi.cyEnd(addDays(s.lastStart!, own.status.averages.period - 1) < today
                      ? addDays(s.lastStart!, own.status.averages.period - 1) : today))}>Ja</button>
          </div>
        )}
        <div className="cy-hero-actions">
          {s.inPeriod
            ? <button className="cy-pill" disabled={busy} onClick={() => act(() => homeApi.cyEnd(today))}>Menstruationen sluttede i dag</button>
            : <button className="cy-pill" disabled={busy} onClick={() => act(() => homeApi.cyStart(today))}>Menstruationen startede i dag</button>}
          {!otherDay
            ? <button className="cy-link" onClick={() => setOtherDay(true)}>En anden dag…</button>
            : (
              <span className="cy-otherday">
                <input type="date" value={pick} max={today} aria-label="Dato" onChange={(e) => setPick(e.target.value)} />
                <button className="cy-pill cy-pill-soft" disabled={busy || !pick}
                        onClick={() => act(() => s.inPeriod ? homeApi.cyEnd(pick) : homeApi.cyStart(pick)).then(() => setOtherDay(false))}>
                  {s.inPeriod ? 'Sluttede' : 'Startede'}</button>
              </span>
            )}
        </div>
      </section>

      <nav className="cy-actions" aria-label="Genveje">
        <a href={routeHash({ name: 'cyklusDay', day: today })}>
          <span className="cy-act cy-act-main" aria-hidden>
            <svg viewBox="0 0 24 24" width="26" height="26"><path d="M4 20h4L19 9l-4-4L4 16z M13.5 6.5l4 4" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round" /></svg>
          </span>Log i dag</a>
        <a href={routeHash({ name: 'cyklusCal', month: null })}><span className="cy-act" aria-hidden><CalIcon /></span>Kalender</a>
        <a href={routeHash({ name: 'cyklusShare' })}>
          <span className="cy-act" aria-hidden>
            <svg viewBox="0 0 24 24" width="26" height="26"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round" /></svg>
          </span>Deling</a>
      </nav>

      {!s.empty && !s.stale && (
        <section aria-label="Mine indsigter">
          <h2 className="cy-h2">Mine indsigter · {shortDate(today)}</h2>
          <div className="cy-cards">
            <div className={`cy-insight cy-ph-${phase}`}>
              <span className="cy-insight-title">{s.phaseLabel}</span>
              <span className="cy-insight-big">{s.cycleDay}</span>
              <span className="cy-insight-sub">cyklusdag</span>
            </div>
            <div className="cy-insight cy-ph-next">
              <span className="cy-insight-title">Næste menstruation</span>
              <span className="cy-insight-big cy-insight-mid">{shortDate(s.nextStart!)}</span>
              <span className="cy-insight-sub">{s.inPeriod ? `om ${days(s.daysUntilNext ?? 0)}` : s.late ? 'snart' : s.daysUntilNext === 0 ? 'i dag' : `om ${days(s.daysUntilNext ?? 0)}`}</span>
            </div>
            <div className="cy-insight cy-ph-fertile">
              <span className="cy-insight-title">Frugtbare dage</span>
              <span className="cy-insight-big cy-insight-mid">{s.fertileToday ? 'I dag' : `${shortDate(s.fertileFrom!)}`}</span>
              <span className="cy-insight-sub">{s.fertileToday ? `til ${shortDate(s.fertileTo!)}` : `til ${shortDate(s.fertileTo!)} · anslået`}</span>
            </div>
            {pattern && pattern.top.length > 0 && (
              <div className="cy-insight cy-ph-pattern">
                <span className="cy-insight-title">Det plejer du at mærke nu</span>
                <ul>{pattern.top.map((t) => <li key={t.name}>{t.name}</li>)}</ul>
              </div>
            )}
            {pattern && pattern.mood != null && (
              <div className="cy-insight cy-ph-mood">
                <span className="cy-insight-title">Dit humør i Dagbogen</span>
                <span className="cy-insight-big">{pattern.mood.toLocaleString('da-DK')}</span>
                <span className="cy-insight-sub">i snit i {pattern.label.toLowerCase()} (1-5)</span>
              </div>
            )}
          </div>
        </section>
      )}

      {own.today && (own.today.flow || own.today.symptoms.length > 0 || own.today.moods.length > 0) && (
        <section className="cy-card" aria-label="Logget i dag">
          <h3 className="cy-h3">Logget i dag</h3>
          <div className="cy-chips cy-chips-ro">
            {own.today.flow && <span>{options.flows.find((f) => f.key === own.today.flow)?.label}</span>}
            {[...own.today.symptoms, ...own.today.moods].map((x) => <span key={x}>{x}</span>)}
          </div>
        </section>
      )}

      <Patterns own={own} />
      <History own={own} today={today} busy={busy} act={act} reload={reload} />
    </>
  );
}

function Patterns({ own }: { own: CyOwn }) {
  const order: Phase[] = ['menstruation', 'follicular', 'fertile', 'luteal', 'pms'];
  const rows = order.map((p) => [p, own.patterns[p]] as const).filter(([, v]) => v && (v.top.length || v.mood != null));
  if (!rows.length) return null;
  return (
    <section className="cy-card" aria-label="Dine mønstre">
      <h3 className="cy-h3">Dine mønstre</h3>
      <p className="cy-dim">Det, du har logget mindst to gange og på mindst hver tredje dag i fasen.</p>
      <dl className="cy-patterns">
        {rows.map(([p, v]) => (
          <div key={p}>
            <dt><i className={`cy-swatch cy-ph-${p}`} />{v!.label}</dt>
            <dd>{v!.top.map((t) => t.name).join(', ') || '—'}
              {v!.mood != null && <small> · humør {v!.mood.toLocaleString('da-DK')}</small>}
              {v!.mental != null && <small> · overskud {v!.mental.toLocaleString('da-DK')}</small>}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function History({ own, today, busy, act, reload }: {
  own: CyOwn; today: string; busy: boolean; act: (fn: () => Promise<CyOwn>) => Promise<void>; reload: () => void;
}) {
  const a = own.status.averages;
  const [edit, setEdit] = useState<number | null>(null);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  if (!own.periods.length) return null;
  return (
    <section className="cy-card" aria-label="Dine cyklusser">
      <h3 className="cy-h3">Dine cyklusser</h3>
      <div className="cy-avgs">
        <div><b>{a.cycle}</b><span>dage i en cyklus</span></div>
        <div><b>{a.period}</b><span>dage med menstruation</span></div>
        <div><b>{a.regular == null ? '–' : a.regular ? 'Ja' : 'Nej'}</b><span>regelmæssig</span></div>
      </div>
      <p className="cy-dim">{a.cycleSource === 'målt' ? (a.cyclesMeasured === 1 ? 'Ud fra din sidste cyklus.' : `Ud fra dine sidste ${a.cyclesMeasured} cyklusser.`)
        : a.cycleSource === 'indstilling' ? 'Ud fra din indstilling, indtil du har logget to cyklusser.'
          : 'Standard 28 dage, indtil du har logget en hel cyklus.'}</p>
      <ul className="cy-periods">
        {own.periods.slice(0, 12).map((p) => (
          <li key={p.id}>
            {edit === p.id ? (
              <span className="cy-edit">
                <input type="date" value={start} max={today} aria-label="Start" onChange={(e) => setStart(e.target.value)} />
                <input type="date" value={end} max={today} aria-label="Slut" onChange={(e) => setEnd(e.target.value)} />
                <button className="cy-pill cy-pill-soft" disabled={busy || !start}
                        onClick={() => act(() => homeApi.cyEditPeriod(p.id, start, end || null)).then(() => { setEdit(null); reload(); })}>Gem</button>
                <button className="cy-link" onClick={() => setEdit(null)}>Fortryd</button>
              </span>
            ) : (
              <>
                <span><b>{shortDate(p.start)}</b>{p.start.slice(0, 4) !== today.slice(0, 4) && ` ${p.start.slice(0, 4)}`}
                  <small>{p.periodDays ? ` · ${days(p.periodDays)}` : p.end ? '' : ' · i gang'}{p.cycleLength ? ` · cyklus ${p.cycleLength} dage` : ''}</small></span>
                <span>
                  <button className="cy-link" onClick={() => { setEdit(p.id); setStart(p.start); setEnd(p.end ?? ''); }}>Ret</button>
                  <button className="cy-link cy-danger" disabled={busy}
                          onClick={() => { if (confirm(`Slet menstruationen fra ${shortDate(p.start)}?`)) void act(() => homeApi.cyDeletePeriod(p.id)); }}>Slet</button>
                </span>
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function SharedCard({ c }: { c: CyShared }) {
  if (c.empty || !c.phase) {
    return <section className="cy-card cy-shared" aria-label={c.name}><h3 className="cy-h3">{c.name}</h3>
      <p className="cy-dim">{c.stale ? 'Har ikke logget en menstruation i et stykke tid.' : 'Har ikke logget en menstruation endnu.'}</p></section>;
  }
  const line = c.inPeriod ? `Menstruationsdag ${c.periodDay}`
    : c.late ? `Menstruationen er ${days(c.late)} forsinket`
      : c.daysUntilNext === 0 ? 'Menstruation forventes i dag'
        : `Menstruation om ${days(c.daysUntilNext ?? 0)}`;
  return (
    <section className={`cy-card cy-shared cy-ph-${c.phase}-soft`} aria-label={c.name}>
      <div className="cy-shared-head">
        <h3 className="cy-h3">{c.name}</h3>
        <span className={`cy-badge cy-ph-${c.phase}`}>{c.phaseLabel}</span>
      </div>
      <p className="cy-shared-line">{line}</p>
      <p className="cy-dim">Cyklusdag {c.cycleDay}</p>
      <p className="cy-phase-text">{c.phaseText}</p>
      {c.week && <Strip list={c.week} today={c.today} />}
      {c.fertileFrom && <p className="cy-dim">Frugtbare dage (anslået): {shortDate(c.fertileFrom)} - {shortDate(c.fertileTo!)}</p>}
      {c.todayLog && (c.todayLog.symptoms.length + c.todayLog.moods.length > 0) && (
        <><p className="cy-label">I dag har {c.name} logget</p>
          <div className="cy-chips cy-chips-ro">{[...c.todayLog.symptoms, ...c.todayLog.moods].map((x) => <span key={x}>{x}</span>)}</div></>
      )}
      {c.pattern && c.pattern.top.length > 0 && (
        <p className="cy-dim">Plejer i denne fase: {c.pattern.top.map((t) => t.name.toLowerCase()).join(', ')}</p>
      )}
    </section>
  );
}

// ---- one day ------------------------------------------------------------------------------------

export function CyklusDayPage({ day }: { day: string }) {
  const today = todayLocal();
  const [opts, setOpts] = useState<CyOptions | null>(null);
  const [saved, setSaved] = useState<CyDay | null>(null);
  const [d, setD] = useState<CyDay | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { homeApi.cyState().then((s) => setOpts(s.options)).catch((e) => setError(e.message)); }, []);
  useEffect(() => {
    setSaved(null); setD(null); setNote(null); setError(null);
    homeApi.cyDay(day).then((r) => { setSaved(r.day); setD(r.day); }).catch((e) => setError(e.message));
  }, [day]);
  const dirty = !!d && JSON.stringify(d) !== JSON.stringify(saved);
  const toggle = (k: 'symptoms' | 'moods', v: string) => setD((x) => x && ({
    ...x, [k]: x[k].includes(v) ? x[k].filter((y) => y !== v) : [...x[k], v] }));

  async function save() {
    if (!d) return;
    setBusy(true); setError(null);
    try {
      const own = await homeApi.cySaveDay(d);
      const fresh = own.today.day === day ? own.today : (await homeApi.cyDay(day)).day;
      setSaved(fresh); setD(fresh); setNote('Gemt ✓');
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function period(kind: 'start' | 'end') {
    setBusy(true); setError(null);
    try { await (kind === 'start' ? homeApi.cyStart(day) : homeApi.cyEnd(day)); setNote(kind === 'start' ? 'Start gemt ✓' : 'Slut gemt ✓'); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const next = addDays(day, 1);
  return (
    <div className="cy-page cy-page-form">
      <CyBar title="Log dagen" back={routeHash({ name: 'cyklus' })} />
      <div className="cy-daynav">
        <a className="cy-round" aria-label="Dagen før" href={routeHash({ name: 'cyklusDay', day: addDays(day, -1) })}>‹</a>
        <span className="cy-dayname">{dayTitle(day, today)}</span>
        {next <= today ? <a className="cy-round" aria-label="Dagen efter" href={routeHash({ name: 'cyklusDay', day: next })}>›</a>
          : <span className="cy-round cy-ghost" aria-hidden />}
      </div>
      {error && <p className="cy-error" role="alert">{error}</p>}
      {(!d || !opts) && !error && <p className="cy-note">Henter…</p>}
      {d && opts && (
        <>
          <section className="cy-card" aria-label="Menstruation">
            <h3 className="cy-h3">Menstruation</h3>
            <div className="cy-period-btns">
              <button className="cy-pill cy-pill-soft" disabled={busy} onClick={() => void period('start')}>Startede denne dag</button>
              <button className="cy-pill cy-pill-soft" disabled={busy} onClick={() => void period('end')}>Sluttede denne dag</button>
            </div>
            <p className="cy-label">Blødning</p>
            <div className="cy-chips" role="radiogroup" aria-label="Blødning">
              {opts.flows.map((f) => (
                <button key={f.key} role="radio" aria-checked={d.flow === f.key} className={d.flow === f.key ? 'on' : ''}
                        onClick={() => setD({ ...d, flow: d.flow === f.key ? '' : f.key })}>
                  <Drops flow={f.key} />{f.label}</button>
              ))}
            </div>
          </section>
          <section className="cy-card" aria-label="Symptomer">
            <h3 className="cy-h3">Symptomer</h3>
            <div className="cy-chips">
              {opts.symptoms.map((x) => <button key={x} className={d.symptoms.includes(x) ? 'on' : ''} aria-pressed={d.symptoms.includes(x)}
                                                onClick={() => toggle('symptoms', x)}>{x}</button>)}
            </div>
          </section>
          <section className="cy-card" aria-label="Humør">
            <h3 className="cy-h3">Humør</h3>
            <div className="cy-chips">
              {opts.moods.map((x) => <button key={x} className={d.moods.includes(x) ? 'on' : ''} aria-pressed={d.moods.includes(x)}
                                             onClick={() => toggle('moods', x)}>{x}</button>)}
            </div>
          </section>
          <section className="cy-card" aria-label="Note">
            <h3 className="cy-h3">Note</h3>
            <p className="cy-dim">🔒 Kun du kan se noten - den deles aldrig.</p>
            <textarea className="cy-text" rows={3} maxLength={1000} value={d.note}
                      onChange={(e) => setD({ ...d, note: e.target.value })} placeholder="Noget at huske?" />
          </section>
        </>
      )}
      <footer className="cy-bottom">
        <button className="cy-pill cy-save" disabled={busy || !dirty} onClick={() => void save()}>
          {busy ? 'Gemmer…' : dirty ? 'Gem dagen' : note ?? 'Gem dagen'}
        </button>
      </footer>
    </div>
  );
}

function Drops({ flow }: { flow: string }) {
  const n = { plet: 0, let: 1, middel: 2, kraftig: 3 }[flow] ?? 0;
  const drop = (x: number) => <path key={x} d={`M${x} 3 C${x} 3 ${x - 4.5} 8.5 ${x - 4.5} 11.5 A4.5 4.5 0 0 0 ${x + 4.5} 11.5 C${x + 4.5} 8.5 ${x} 3 ${x} 3Z`} />;
  return (
    <svg className="cy-drops" viewBox={`0 0 ${n ? n * 10 + 2 : 10} 18`} height="16" aria-hidden fill="currentColor">
      {n ? Array.from({ length: n }, (_, i) => drop(6 + i * 10)) : <circle cx="5" cy="12" r="2.6" />}
    </svg>
  );
}

// ---- the calendar -------------------------------------------------------------------------------

export function CyklusCalendar({ month }: { month: string | null }) {
  const today = todayLocal();
  const m = month ?? today.slice(0, 7);
  const [list, setList] = useState<Map<string, { kind: DayKind; logged: boolean }> | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setList(null);
    const grid = monthGrid(m).filter((x): x is string => !!x);
    homeApi.cyCalendar(grid[0], grid[grid.length - 1])
      .then((r) => setList(new Map(r.days.map((x) => [x.day, { kind: x.kind, logged: x.logged }]))))
      .catch((e) => setError(e.message));
  }, [m]);
  const lastAllowed = addMonths(today.slice(0, 7), 6);
  return (
    <div className="cy-page">
      <CyBar title="Kalender" back={routeHash({ name: 'cyklus' })} />
      <div className="cy-daynav">
        <a className="cy-round" aria-label="Måneden før" href={routeHash({ name: 'cyklusCal', month: addMonths(m, -1) })}>‹</a>
        <span className="cy-dayname">{monthTitle(m)}</span>
        {m < lastAllowed ? <a className="cy-round" aria-label="Måneden efter" href={routeHash({ name: 'cyklusCal', month: addMonths(m, 1) })}>›</a>
          : <span className="cy-round cy-ghost" aria-hidden />}
      </div>
      {error && <p className="cy-error" role="alert">{error}</p>}
      <section className="cy-card cy-cal" aria-label={monthTitle(m)}>
        <div className="cy-cal-grid">
          {['M', 'T', 'O', 'T', 'F', 'L', 'S'].map((x, i) => <span key={i} className="cy-wd">{x}</span>)}
          {monthGrid(m).map((day, i) => {
            if (!day) return <span key={`e${i}`} />;
            const v = list?.get(day);
            const cls = `cy-dot cy-${v?.kind || 'none'}${day === today ? ' cy-today' : ''}`;
            const inner = <span className={cls}>{dayOfMonth(day)}{v?.logged && <i className="cy-logged" />}</span>;
            return day <= today
              ? <a key={day} href={routeHash({ name: 'cyklusDay', day })} aria-label={`${day}${v?.kind ? ` ${KIND_LABEL[v.kind]}` : ''}`}>{inner}</a>
              : <span key={day} aria-label={`${day}${v?.kind ? ` ${KIND_LABEL[v.kind]}` : ''}`}>{inner}</span>;
          })}
        </div>
        <Legend />
        <p className="cy-dim">Tryk på en dag for at logge den. En prik under datoen: noget er logget.</p>
      </section>
    </div>
  );
}

// ---- sharing ----------------------------------------------------------------------------------------

export function CyklusShare() {
  const [s, setS] = useState<Awaited<ReturnType<typeof homeApi.cySettings>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => { homeApi.cySettings().then(setS).catch((e) => setError(e.message)); }, []);
  async function save(patch: Parameters<typeof homeApi.cySaveSettings>[0]) {
    setError(null); setNote(null);
    const before = s;
    setS((x) => (x ? { ...x, settings: { ...x.settings, ...patch } } : x));      // the box ticks at once
    try { setS(await homeApi.cySaveSettings(patch)); setNote('Gemt ✓'); }
    catch (e) { setS(before); setError((e as Error).message); }
  }
  const viewers = s?.settings.viewers ?? [];
  return (
    <div className="cy-page">
      <CyBar title="Deling" back={routeHash({ name: 'cyklus' })} />
      {error && <p className="cy-error" role="alert">{error}</p>}
      {!s && !error && <p className="cy-note">Henter…</p>}
      {s && (
        <>
          <section className="cy-card" aria-label="Hvem kan se din cyklus">
            <h3 className="cy-h3">Hvem kan se din cyklus?</h3>
            <p className="cy-dim">Kun dem, du vælger her - heller ikke administratoren ser noget ellers.
              De ser din fase, cyklusdag og hvornår næste menstruation ventes. (Ud fra den dato kan man selv
              regne de frugtbare dage nogenlunde ud.)</p>
            <ul className="cy-checks">
              {s.candidates.map((c) => (
                <li key={c.id}><label>
                  <input type="checkbox" checked={viewers.includes(c.id)}
                         onChange={(e) => void save({ viewers: e.target.checked ? [...viewers, c.id] : viewers.filter((v) => v !== c.id) })} />
                  <span>{c.username}</span>{c.gender === 'male' && <small>mand</small>}{c.gender === 'female' && <small>kvinde</small>}
                </label></li>
              ))}
            </ul>
          </section>
          <section className="cy-card" aria-label="Hvad deles">
            <h3 className="cy-h3">Del også</h3>
            <label className="cy-toggle"><input type="checkbox" checked={s.settings.shareFertile}
                                                onChange={(e) => void save({ shareFertile: e.target.checked })} />
              <span>Frugtbare dage<small>Ellers vises de bare som "midt i cyklussen".</small></span></label>
            <label className="cy-toggle"><input type="checkbox" checked={s.settings.shareDetails}
                                                onChange={(e) => void save({ shareDetails: e.target.checked })} />
              <span>Dagens symptomer og humør, og dine mønstre<small>Din note deles aldrig.</small></span></label>
          </section>
          <section className="cy-card" aria-label="Din cyklus">
            <h3 className="cy-h3">Din cyklus</h3>
            <p className="cy-dim">Bruges indtil du har logget nok til, at Cyklus kan regne det ud selv. Tomt = standard.</p>
            <NumberSetting label="Dage i en cyklus" value={s.settings.cycleLength} min={20} max={60}
                           onSave={(v) => save({ cycleLength: v })} />
            <NumberSetting label="Dage med menstruation" value={s.settings.periodLength} min={1} max={10}
                           onSave={(v) => save({ periodLength: v })} />
          </section>
          {note && <p className="cy-ok">{note}</p>}
        </>
      )}
    </div>
  );
}

function NumberSetting({ label, value, min, max, onSave }: {
  label: string; value: number | null; min: number; max: number; onSave: (v: number | null) => void;
}) {
  const [v, setV] = useState(value == null ? '' : String(value));
  useEffect(() => { setV(value == null ? '' : String(value)); }, [value]);
  const n = v === '' ? null : Number(v);
  const ok = n === null || (Number.isInteger(n) && n >= min && n <= max);
  return (
    <label className="cy-num"><span>{label}</span>
      <input type="number" inputMode="numeric" min={min} max={max} value={v} onChange={(e) => setV(e.target.value)}
             onBlur={() => { if (ok && n !== value) onSave(n); }} aria-invalid={!ok} />
    </label>
  );
}

/** The front page tile's line: her own day, or the first shared status. */
export function cyklusTileLine(st: CyState): string {
  const s = st.own?.status;
  if (st.enabled && s) {
    if (s.empty || s.stale) return 'Log din menstruation';
    if (s.inPeriod) return `Menstruationsdag ${s.periodDay}`;
    if (s.late) return `${days(s.late)} forsinket`;
    return `Cyklusdag ${s.cycleDay}`;
  }
  const c = st.shared[0];
  if (!c || c.empty) return c ? `${c.name}` : '';
  return c.inPeriod ? `${c.name}: menstruation` : `${c.name}: ${(c.phaseLabel ?? '').toLowerCase()}`;
}

