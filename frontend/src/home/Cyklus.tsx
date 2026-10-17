import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  homeApi, type CyCalDay, type CyDay, type CyDayInfo, type CyForecast, type CyOptions, type CyOwn, type CyShared,
  type CySharedDay, type CyState, type DayKind, type Phase,
} from './api';
import {
  addDays, addMonths, dayOfMonth, daysBetween, dayTitle, longDate, monthGrid, monthTitle, routeHash, shortDate,
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

// ---- the strip of days: swipe week by week, tap a day -----------------------------------------

const KIND_LABEL: Record<DayKind, string> = {
  '': '', period: 'menstruation', predicted: 'forventet menstruation', possible: 'mulig menstruation',
  fertile: 'frugtbar', ovulation: 'ægløsning', pms: 'PMS',
};

const WEEKS_BACK = 6;
const WEEKS_AHEAD = 8;

function dotClass(kind: DayKind | undefined, day: string, today: string, selected?: string) {
  return `cy-dot cy-${kind || 'none'}${day === today ? ' cy-today' : ''}${selected === day ? ' cy-sel' : ''}`;
}

/** Weeks side by side; the page opens on this week and swipes either way. */
function ScrollStrip({ marks, today, selected, onPick, back = WEEKS_BACK, ahead = WEEKS_AHEAD }: {
  marks: Map<string, DayKind>; today: string; selected: string; onPick: (day: string) => void;
  back?: number; ahead?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const first = addDays(weekStart(today), -7 * back);
  const weeks = Array.from({ length: back + ahead + 1 }, (_, w) => addDays(first, 7 * w));
  // Show the week of the chosen day - on opening, and when "back to today"
  // (or a tap elsewhere) picks a day in another week.
  const week = Math.max(0, Math.min(weeks.length - 1, Math.floor(daysBetween(first, selected) / 7)));
  const shown = useRef(week);
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollLeft = el.clientWidth * week;      // instant: a smooth scroll can be cut short
    shown.current = week;
  }, [week]);
  // Keep the week in view when the width changes (turning the phone).
  useEffect(() => {
    const on = () => { const el = ref.current; if (el) el.scrollLeft = el.clientWidth * shown.current; };
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  return (
    <div className="cy-strip-scroll" ref={ref} aria-label="Uger - stryg til siden"
         onScroll={(e) => { const el = e.currentTarget; if (el.clientWidth) shown.current = Math.round(el.scrollLeft / el.clientWidth); }}>
      {weeks.map((w) => (
        <div key={w} className="cy-strip">
          {Array.from({ length: 7 }, (_, i) => addDays(w, i)).map((day) => {
            const kind = marks.get(day) ?? '';
            return (
              <button key={day} className="cy-strip-day" onClick={() => onPick(day)} aria-pressed={selected === day}
                      aria-label={`${dayTitle(day, today)}${kind ? `: ${KIND_LABEL[kind]}` : ''}`}>
                <span className={`cy-wd${day === today ? ' cy-wd-today' : ''}`}>{day === today ? 'I DAG' : weekdayLetter(day)}</span>
                <span className={dotClass(kind, day, today, selected)}>{dayOfMonth(day)}</span>
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function Legend() {
  return (
    <p className="cy-legend">
      <span><i className="cy-dot cy-period" />Menstruation</span>
      <span><i className="cy-dot cy-predicted" />Forventet</span>
      <span><i className="cy-dot cy-possible" />Mulig</span>
      <span><i className="cy-dot cy-fertile" />Frugtbar</span>
      <span><i className="cy-dot cy-ovulation" />Ægløsning</span>
      <span><i className="cy-dot cy-pms" />PMS</span>
    </p>
  );
}

// ---- the main page ----------------------------------------------------------------------------

export function CyklusPage() {
  const { st, error, setError, setOwn, load } = useCy();
  const [busy, setBusy] = useState(false);
  const today = todayLocal();
  const [selected, setSelected] = useState(today);

  async function act(fn: () => Promise<CyOwn>) {
    setBusy(true); setError(null);
    try { setOwn(await fn()); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div className="cy-page">
      <CyBar title={st?.enabled ? (selected === today ? 'I dag' : longDate(selected)) : 'Cyklus'} right={st?.enabled
        ? <a className="cy-round" aria-label="Kalender" href={routeHash({ name: 'cyklusCal', month: null })}><CalIcon /></a>
        : undefined} />
      {!st && !error && <p className="cy-note">Henter…</p>}
      {error && <p className="cy-error" role="alert">{error}</p>}
      {st?.enabled && st.own && <Own own={st.own} options={st.options} today={today} busy={busy} act={act}
                                     reload={load} selected={selected} setSelected={setSelected} />}
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

function Own({ own, options, today, busy, act, reload, selected, setSelected }: {
  own: CyOwn; options: CyOptions; today: string; busy: boolean;
  act: (fn: () => Promise<CyOwn>) => Promise<void>; reload: () => void;
  selected: string; setSelected: (d: string) => void;
}) {
  const s = own.status;
  const [marks, setMarks] = useState<Map<string, DayKind>>(new Map());
  const [info, setInfo] = useState<CyDayInfo | null>(null);
  const first = addDays(weekStart(today), -7 * WEEKS_BACK);
  const last = addDays(weekStart(today), 7 * WEEKS_AHEAD + 6);
  const version = `${s.lastStart}|${s.inPeriod}|${s.lastOpen}|${own.periods.map((p) => `${p.start}-${p.end}`).join(',')}`;
  useEffect(() => {
    homeApi.cyCalendar(first, last).then((r) => setMarks(new Map(r.days.map((d) => [d.day, d.kind])))).catch(() => setMarks(new Map()));
  }, [first, last, version]);
  useEffect(() => {
    setInfo(null);
    homeApi.cyDayInfo(selected).then(setInfo).catch(() => setInfo(null));
  }, [selected, version, own.today]);

  const isToday = selected === today;
  let kicker = ''; let big: string; let small = '';
  if (isToday) {
    if (s.empty) { big = 'Velkommen'; small = 'Tryk på dagen, din seneste menstruation startede, og så "Menstruationen startede".'; }
    else if (s.stale) { big = 'Log din seneste menstruation'; small = `Den sidste, der er logget, startede ${shortDate(s.lastStart!)} ${s.lastStart!.slice(0, 4)}.`; }
    else if (s.inPeriod) { big = `Menstruationsdag ${s.periodDay}`; small = `Cyklusdag ${s.cycleDay}`; }
    else if (s.late) { big = `${days(s.late)} forsinket`; small = `Menstruationen ventedes ${shortDate(addDays(today, -s.late))} · cyklusdag ${s.cycleDay}`; }
    else if (s.daysUntilNext === 0) { kicker = 'Forudsigelse'; big = 'Menstruation i dag'; small = `Cyklusdag ${s.cycleDay}`; }
    else if (s.fertileToday) { kicker = 'Forudsigelse'; big = 'Frugtbar dag'; small = `Menstruation om ${days(s.daysUntilNext ?? 0)} · cyklusdag ${s.cycleDay}`; }
    else if ((s.daysUntilFertile ?? 0) > 0 && s.fertileFrom! < s.nextStart!) {
      kicker = 'Forudsigelse'; big = `Frugtbare dage om ${days(s.daysUntilFertile!)}`;
      small = `Menstruation om ${days(s.daysUntilNext ?? 0)} · cyklusdag ${s.cycleDay}`;
    } else { kicker = 'Forudsigelse'; big = `Menstruation om ${days(s.daysUntilNext ?? 0)}`; small = `Cyklusdag ${s.cycleDay} · ${s.phaseLabel}`; }
  } else {
    kicker = selected > today ? `Forudsigelse · ${dayTitle(selected, today)}` : dayTitle(selected, today);
    big = info?.title ?? '…';
    small = info?.sub ?? '';
  }
  const selKind = marks.get(selected) ?? '';
  const canLog = selected <= today;
  const word = isToday ? 'i dag' : 'denne dag';
  const lastPeriod = own.periods[0];
  const endsOpen = !!lastPeriod && !lastPeriod.end && selected >= lastPeriod.start && selKind === 'period';
  const ins = info && info.phase ? info : null;

  return (
    <>
      <ScrollStrip marks={marks} today={today} selected={selected} onPick={setSelected} />
      <section className="cy-hero" aria-label="Dagen">
        {kicker && <p className="cy-kicker">{kicker}</p>}
        <h1 className="cy-big">{big}</h1>
        {small && <p className="cy-small">{small}</p>}
        {isToday && s.phaseText && <p className="cy-phase-text">{s.phaseText}</p>}
        {isToday && s.askEnded && (
          <div className="cy-ask-ended">
            <span>Er din menstruation slut?</span>
            <button className="cy-pill cy-pill-soft" disabled={busy}
                    onClick={() => act(() => homeApi.cyEnd(addDays(s.lastStart!, s.averages.period - 1) < today
                      ? addDays(s.lastStart!, s.averages.period - 1) : today))}>Ja</button>
          </div>
        )}
        <div className="cy-hero-actions">
          {canLog && (endsOpen
            ? <button className="cy-pill" disabled={busy} onClick={() => act(() => homeApi.cyEnd(selected))}>Menstruationen sluttede {word}</button>
            : selKind !== 'period' && <button className="cy-pill" disabled={busy} onClick={() => act(() => homeApi.cyStart(selected))}>Menstruationen startede {word}</button>)}
          {!isToday && <button className="cy-link" onClick={() => setSelected(today)}>Tilbage til i dag</button>}
        </div>
      </section>

      <nav className="cy-actions" aria-label="Genveje">
        <a href={routeHash({ name: 'cyklusDay', day: canLog ? selected : today })}>
          <span className="cy-act cy-act-main" aria-hidden>
            <svg viewBox="0 0 24 24" width="26" height="26"><path d="M4 20h4L19 9l-4-4L4 16z M13.5 6.5l4 4" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round" /></svg>
          </span>{canLog && !isToday ? 'Log dagen' : 'Log i dag'}</a>
        <a href={routeHash({ name: 'cyklusCal', month: null })}><span className="cy-act" aria-hidden><CalIcon /></span>Kalender</a>
        <a href={routeHash({ name: 'cyklusShare' })}>
          <span className="cy-act" aria-hidden>
            <svg viewBox="0 0 24 24" width="26" height="26"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round" /></svg>
          </span>Deling</a>
      </nav>

      {ins && (
        <section aria-label="Mine indsigter">
          <h2 className="cy-h2">Mine indsigter · {isToday ? 'i dag' : shortDate(selected)}</h2>
          <div className="cy-cards">
            <div className={`cy-insight cy-ph-${ins.phase}`}>
              <span className="cy-insight-title">{ins.phaseLabel}</span>
              <span className="cy-insight-big">{ins.cycleDay}</span>
              <span className="cy-insight-sub">cyklusdag</span>
            </div>
            <div className={`cy-insight cy-chance-${ins.chance}`}>
              <span className="cy-insight-title">Chance for graviditet</span>
              <span className="cy-insight-big cy-insight-mid">{ins.chanceLabel}</span>
              <span className="cy-insight-sub">anslået ud fra kalenderen</span>
            </div>
            {ins.forecast && (
              <div className="cy-insight cy-ph-expect">
                <span className="cy-insight-title">Symptomer at forvente</span>
                {ins.forecast.expect.length
                  ? <ul>{ins.forecast.expect.slice(0, 4).map((x) => <li key={x}>{x}</li>)}</ul>
                  : <span className="cy-insight-sub">Ingen særlige</span>}
                <span className="cy-insight-sub">{ins.forecast.expectSource === 'dig' ? 'ud fra dine logs' : 'typisk for fasen'}</span>
              </div>
            )}
            {ins.nextPeriodIn != null && (
              <div className="cy-insight cy-ph-next">
                <span className="cy-insight-title">Næste menstruation</span>
                <span className="cy-insight-big cy-insight-mid">{ins.nextPeriodIn === 0 ? 'Samme dag' : `om ${days(ins.nextPeriodIn)}`}</span>
                <span className="cy-insight-sub">{shortDate(addDays(selected, ins.nextPeriodIn))}</span>
              </div>
            )}
          </div>
        </section>
      )}

      {ins?.forecast && <ForecastCard f={ins.forecast} text={ins.text} title={isToday ? 'Humør og adfærd i dag' : `Humør og adfærd · ${shortDate(selected)}`} />}
      {info && !info.phase && !s.empty && <section className="cy-card"><p className="cy-dim">{info.text}</p></section>}

      {info?.log && (info.log.flow || info.log.symptoms.length > 0 || info.log.moods.length > 0) && (
        <section className="cy-card" aria-label="Logget">
          <h3 className="cy-h3">Logget {isToday ? 'i dag' : shortDate(selected)}</h3>
          <div className="cy-chips cy-chips-ro">
            {info.log.flow && <span>{options.flows.find((f) => f.key === info.log!.flow)?.label}</span>}
            {[...info.log.symptoms, ...info.log.moods].map((x) => <span key={x}>{x}</span>)}
          </div>
        </section>
      )}

      <Patterns own={own} />
      <History own={own} today={today} busy={busy} act={act} reload={reload} />
    </>
  );
}

const SOURCE: Record<string, string> = { typisk: 'typisk', dig: 'dine logs', dagbog: 'Dagbogen' };

/** The mood and behaviour to expect - bars of five, each saying where it comes from. */
function ForecastCard({ f, text, title, shared, embedded }: {
  f: CyForecast; text?: string; title: string; shared?: boolean; embedded?: boolean;
}) {
  return (
    <section className={`${embedded ? 'cy-embedded' : 'cy-card'} cy-forecast`} aria-label={title}>
      <h3 className="cy-h3">{title}</h3>
      {text && <p className="cy-day-text">{text}</p>}
      <ul className="cy-bars">
        {f.items.map((x) => (
          <li key={x.key}>
            <span className="cy-bar-label">{x.label}</span>
            <span className="cy-bar" role="img" aria-label={`${x.label} ${x.value} af 5`}>
              {[1, 2, 3, 4, 5].map((i) => <i key={i} className={i <= x.value ? 'on' : ''} />)}
            </span>
            <small className={`cy-src cy-src-${x.source}`}>{SOURCE[x.source]}</small>
          </li>
        ))}
      </ul>
      <p className="cy-behaviour"><b>{shared ? 'Typisk nu: ' : 'Forvent: '}</b>{f.behaviour}</p>
      {shared && f.expect.length > 0 && <p className="cy-dim">Kan mærke: {f.expect.map((x) => x.toLowerCase()).join(', ')}</p>}
    </section>
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
    <>
      <section className={`cy-card cy-shared cy-ph-${c.phase}-soft`} aria-label={c.name}>
        <div className="cy-shared-head">
          <h3 className="cy-h3">{c.name}</h3>
          <span className={`cy-badge cy-ph-${c.phase}`}>{c.phaseLabel}</span>
        </div>
        <p className="cy-shared-line">{line}</p>
        <p className="cy-dim">Cyklusdag {c.cycleDay}</p>
        <p className="cy-phase-text">{c.phaseText}</p>
        <SharedDays c={c} />
        {c.fertileFrom && <p className="cy-dim">Frugtbare dage (anslået): {shortDate(c.fertileFrom)} - {shortDate(c.fertileTo!)}</p>}
        {c.todayLog && (c.todayLog.symptoms.length + c.todayLog.moods.length > 0) && (
          <><p className="cy-label">I dag har {c.name} logget</p>
            <div className="cy-chips cy-chips-ro">{[...c.todayLog.symptoms, ...c.todayLog.moods].map((x) => <span key={x}>{x}</span>)}</div></>
        )}
      </section>
    </>
  );
}

/** The days ahead as she shares them (0.3.1): swipe, tap a day, see what
    it is and the mood and behaviour to expect. */
function SharedDays({ c }: { c: CyShared }) {
  const [sel, setSel] = useState(c.today);
  const [marks, setMarks] = useState<Map<string, DayKind>>(
    new Map((c.week ?? []).map((w) => [w.day, w.kind])));
  const [day, setDay] = useState<CySharedDay | null>(null);
  const first = addDays(weekStart(c.today), -14);
  const last = addDays(weekStart(c.today), 7 * 8 + 6);
  useEffect(() => {
    homeApi.cySharedCalendar(c.id, first, last).then((r) => setMarks(new Map(r.days.map((d) => [d.day, d.kind])))).catch(() => {});
  }, [c.id, first, last]);
  useEffect(() => {
    setDay(null);
    if (sel !== c.today) homeApi.cySharedDay(c.id, sel).then(setDay).catch(() => setDay(null));
  }, [c.id, c.today, sel]);
  const isToday = sel === c.today;
  return (
    <>
      <ScrollStrip marks={marks} today={c.today} selected={sel} onPick={setSel} back={2} ahead={8} />
      {!isToday && (
        <div className="cy-shared-day" aria-label="Den valgte dag">
          <p className="cy-kicker">{sel > c.today ? `Forudsigelse · ${dayTitle(sel, c.today)}` : dayTitle(sel, c.today)}</p>
          {!day && <p className="cy-dim">Henter…</p>}
          {day && <><p className="cy-shared-line">{day.title}</p>
            {day.sub && <p className="cy-dim">{day.sub}{day.chanceLabel ? ` · chance for graviditet: ${day.chanceLabel.toLowerCase()}` : ''}</p>}
            {day.nextPeriodIn != null && day.nextPeriodIn > 0 && <p className="cy-dim">Menstruation om {days(day.nextPeriodIn)}</p>}</>}
          <button className="cy-link" onClick={() => setSel(c.today)}>Tilbage til i dag</button>
        </div>
      )}
      {isToday && c.forecast && <ForecastCard f={c.forecast} title={`${c.name} i dag: humør og adfærd`} shared embedded />}
      {!isToday && day?.forecast && <ForecastCard f={day.forecast} text={day.text}
        title={`${c.name} · ${shortDate(sel)}: humør og adfærd`} shared embedded />}
    </>
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

// ---- the calendar: months and a year, like a period app's ---------------------------------------

const MONTHS_BACK = 6;
const MONTHS_AHEAD = 6;

export function CyklusCalendar({ month }: { month: string | null }) {
  const today = todayLocal();
  const thisMonth = today.slice(0, 7);
  const [mode, setMode] = useState<'month' | 'year'>('month');
  const [year, setYear] = useState(Number(today.slice(0, 4)));
  const [target, setTarget] = useState(month ?? thisMonth);
  const [marks, setMarks] = useState<Map<string, CyCalDay> | null>(null);
  const [yearMarks, setYearMarks] = useState<Map<string, CyCalDay> | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [info, setInfo] = useState<CyDayInfo | null>(null);
  const [edit, setEdit] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const months = useMemo(() => Array.from({ length: MONTHS_BACK + MONTHS_AHEAD + 1 },
    (_, i) => addMonths(thisMonth, i - MONTHS_BACK)), [thisMonth]);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const from = `${months[0]}-01`;
    const lastGrid = monthGrid(months[months.length - 1]).filter((x): x is string => !!x);
    homeApi.cyCalendar(from, lastGrid[lastGrid.length - 1])
      .then((r) => setMarks(new Map(r.days.map((x) => [x.day, x])))).catch((e) => setError(e.message));
  }, [months, version]);
  useEffect(() => {
    if (mode !== 'year') return;
    setYearMarks(null);
    homeApi.cyCalendar(`${year}-01-01`, `${year}-12-31`)
      .then((r) => setYearMarks(new Map(r.days.map((x) => [x.day, x])))).catch((e) => setError(e.message));
  }, [mode, year, version]);
  useEffect(() => {
    if (mode !== 'month' || !marks) return;
    const el = listRef.current?.querySelector(`[data-month="${target}"]`);
    (el as HTMLElement | null)?.scrollIntoView?.({ block: 'start' });
  }, [mode, marks, target]);
  useEffect(() => {
    setInfo(null);
    if (picked && !edit) homeApi.cyDayInfo(picked).then(setInfo).catch((e) => setError(e.message));
  }, [picked, edit, version]);

  async function toggle(day: string) {
    if (day > today || busy) return;
    setBusy(true); setError(null);
    try { await homeApi.cyToggle(day); setVersion((v) => v + 1); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  function tap(day: string) {
    if (edit) void toggle(day);
    else setPicked(picked === day ? null : day);
  }

  return (
    <div className={`cy-page cy-cal-page${picked && !edit ? ' cy-has-sheet' : ''}`}>
      <header className="cy-cal-head">
        <a className="cy-round" aria-label="Luk kalenderen" href={routeHash({ name: 'cyklus' })}>✕</a>
        <div className="cy-seg" role="tablist">
          <button role="tab" aria-selected={mode === 'month'} className={mode === 'month' ? 'on' : ''}
                  onClick={() => setMode('month')}>Måned</button>
          <button role="tab" aria-selected={mode === 'year'} className={mode === 'year' ? 'on' : ''}
                  onClick={() => { setMode('year'); setEdit(false); setPicked(null); }}>År</button>
        </div>
        <button className="cy-link cy-today-link" onClick={() => {
          setYear(Number(today.slice(0, 4))); setMode('month'); setTarget(thisMonth);
          const el = listRef.current?.querySelector(`[data-month="${thisMonth}"]`);
          (el as HTMLElement | null)?.scrollIntoView?.({ block: 'start', behavior: 'smooth' });
          setPicked(edit ? null : today);
        }}>I dag</button>
      </header>
      {error && <p className="cy-error" role="alert">{error}</p>}

      {mode === 'month' && (
        <>
          <div className="cy-wd-row" aria-hidden>{['M', 'T', 'O', 'T', 'F', 'L', 'S'].map((x, i) => <span key={i}>{x}</span>)}</div>
          {!marks && <p className="cy-note">Henter…</p>}
          <div className="cy-months" ref={listRef}>
            {marks && months.map((m) => (
              <section key={m} className="cy-month" data-month={m} aria-label={monthTitle(m)}>
                <h3 className="cy-month-title">{monthTitle(m).replace(` ${today.slice(0, 4)}`, '')}</h3>
                <div className="cy-cal-grid">
                  {monthGrid(m).map((day, i) => {
                    if (!day) return <span key={`e${i}`} />;
                    const v = marks.get(day);
                    const future = day > today;
                    const on = v?.kind === 'period';
                    return (
                      <button key={day} className={`cy-cal-day${edit && !future ? ' cy-editable' : ''}`}
                              disabled={edit && future} onClick={() => tap(day)}
                              aria-label={`${longDate(day)}${v?.kind ? `: ${KIND_LABEL[v.kind]}` : ''}`}
                              aria-pressed={edit ? on : picked === day}>
                        <span className={dotClass(v?.kind, day, today, edit ? undefined : picked ?? undefined)}>
                          {dayOfMonth(day)}{v?.logged && <i className="cy-logged" />}
                        </span>
                        {edit && !future && <span className={`cy-check${on ? ' on' : ''}`} aria-hidden>{on ? '✓' : ''}</span>}
                      </button>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
          <Legend />
          {!picked && (
            <div className="cy-cal-bottom">
              {edit
                ? <button className="cy-pill" onClick={() => setEdit(false)}>Færdig</button>
                : <button className="cy-pill" onClick={() => { setEdit(true); setPicked(null); }}>Rediger menstruationsdatoer</button>}
              {edit && <p className="cy-dim">Tryk på de dage, du havde menstruation. {busy ? 'Gemmer…' : ''}</p>}
            </div>
          )}
          {picked && !edit && <DaySheet day={picked} info={info} today={today} onClose={() => setPicked(null)} />}
        </>
      )}

      {mode === 'year' && (
        <section className="cy-year" aria-label={`År ${year}`}>
          <div className="cy-daynav">
            <button className="cy-round" aria-label="Året før" onClick={() => setYear(year - 1)}
                    disabled={year <= Number(today.slice(0, 4)) - 2}>‹</button>
            <span className="cy-dayname">{year}</span>
            <button className="cy-round" aria-label="Året efter" onClick={() => setYear(year + 1)}
                    disabled={year >= Number(today.slice(0, 4)) + 1}>›</button>
          </div>
          {!yearMarks && <p className="cy-note">Henter…</p>}
          {yearMarks && (
            <div className="cy-year-grid">
              {Array.from({ length: 12 }, (_, i) => `${year}-${String(i + 1).padStart(2, '0')}`).map((m) => (
                <button key={m} className="cy-mini" aria-label={monthTitle(m)}
                        onClick={() => { if (months.includes(m)) { setTarget(m); setMode('month'); } }}>
                  <span className={`cy-mini-title${m === thisMonth ? ' on' : ''}`}>{monthTitle(m).split(' ')[0]}</span>
                  <span className="cy-mini-grid">
                    {monthGrid(m).map((day, j) => day
                      ? <i key={day} className={`cy-mini-day cy-${yearMarks.get(day)?.kind || 'none'}${day === today ? ' cy-today' : ''}`}>{dayOfMonth(day)}</i>
                      : <i key={`e${j}`} />)}
                  </span>
                </button>
              ))}
            </div>
          )}
          <Legend />
        </section>
      )}
    </div>
  );
}

function DaySheet({ day, info, today, onClose }: { day: string; info: CyDayInfo | null; today: string; onClose: () => void }) {
  return (
    <section className="cy-sheet" aria-label="Dagen">
      <div className="cy-sheet-head">
        <h3>{shortDate(day)}{info?.cycleDay ? ` · Cyklusdag ${info.cycleDay}` : ''}</h3>
        <button className="cy-x" aria-label="Luk" onClick={onClose}>✕</button>
      </div>
      {!info && <p className="cy-dim">Henter…</p>}
      {info && (
        <>
          <p className="cy-sheet-title">{info.title}</p>
          {info.chanceLabel && <p className="cy-dim">{info.phaseLabel} · chance for graviditet: {info.chanceLabel.toLowerCase()}</p>}
          <p className="cy-day-text">{info.text}</p>
          {info.forecast && <p className="cy-behaviour"><b>Forvent: </b>{info.forecast.behaviour}</p>}
          {info.log && (info.log.flow || info.log.symptoms.length + info.log.moods.length > 0) && (
            <div className="cy-chips cy-chips-ro">{[...info.log.symptoms, ...info.log.moods].map((x) => <span key={x}>{x}</span>)}</div>
          )}
          {day <= today && <a className="cy-pill cy-sheet-btn" href={routeHash({ name: 'cyklusDay', day })}>Log dagen</a>}
        </>
      )}
    </section>
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

