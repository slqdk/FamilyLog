import { useEffect, useMemo, useState } from 'react';
import type { FmUser } from '../sections/familymap/phone/types';
import { homeApi, type DagbogCount, type DagbogEntry, type DagbogFamily, type DagbogPerson, type DagbogStats } from './api';
import { Bar, Dots, Tabs, hoursText } from './Dagbog';
import {
  addDays, addMonths, dayOfMonth, dayTitle, face, mean, monthGrid, monthShort, monthTitle, routeHash, todayLocal,
  weekdayLetter,
} from './logic';

/** Dagbog → Familien (0.3.9, Søren: "make it person based… go back a long
    way… statistics for the individual… text and pictures visible"). The
    family's week at a glance, one card per person; a person's page has their
    days - every one, back to the first, with a month calendar to jump - and
    their statistics. The family is the family accounts and the administrator. */

const one = (x: number) => x.toFixed(1).replace('.', ',');
const name = (me: FmUser, p: { id: number; username: string }) => (p.id === me.id ? 'Mig' : p.username);

export function FamilyPage({ me, person, stats }: { me: FmUser; person: number | null; stats?: boolean }) {
  const today = todayLocal();
  const [week, setWeek] = useState<DagbogFamily | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    homeApi.family(addDays(today, -6), today).then(setWeek).catch((e) => setError(e.message));
  }, [today]);

  return (
    <div className="fm-page hm-page">
      <Bar title="Dagbog" back={person == null ? '#/' : routeHash({ name: 'family', person: null })} />
      <Tabs on="family" />
      {week && person != null && <PersonChips me={me} members={week.members} on={person} stats={!!stats} />}
      <main className="hm-form">
        {error && <p className="fm-error">{error}</p>}
        {!week && !error && <p className="fm-note">Henter…</p>}
        {week && person == null && <FamilyCards me={me} week={week} today={today} />}
        {week && person != null && (
          <>
            <nav className="hm-subtabs" aria-label="Visning">
              <a className={stats ? '' : 'on'} href={routeHash({ name: 'family', person })}>Dage</a>
              <a className={stats ? 'on' : ''} href={routeHash({ name: 'family', person, stats: true })}>Statistik</a>
            </nav>
            {stats ? <PersonStats key={person} uid={person} today={today} />
                   : <PersonDays key={person} uid={person} today={today} />}
          </>
        )}
      </main>
    </div>
  );
}

function PersonChips({ me, members, on, stats }: {
  me: FmUser; members: DagbogFamily['members']; on: number; stats: boolean;
}) {
  return (
    <nav className="hm-people" aria-label="Personer">
      {members.map((m) => (
        <a key={m.id} className={m.id === on ? 'on' : ''} aria-current={m.id === on ? 'page' : undefined}
           href={routeHash({ name: 'family', person: m.id, stats })}>
          <span className="hm-avatar" aria-hidden>{m.username[0]?.toUpperCase()}</span>{name(me, m)}
        </a>
      ))}
    </nav>
  );
}

/** The week at a glance: a card per person with the last seven days. */
function FamilyCards({ me, week, today }: { me: FmUser; week: DagbogFamily; today: string }) {
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(today, i - 6)), [today]);
  const byKey = useMemo(() => new Map(week.entries.map((e) => [`${e.userId}|${e.day}`, e])), [week]);
  return (
    <>
      <p className="hm-lead">De sidste 7 dage. Tryk på en person for alle dagene og statistik.</p>
      {week.members.map((m) => {
        const mine = days.map((d) => byKey.get(`${m.id}|${d}`));
        const avg = mean(mine.map((e) => e?.mood));
        const last = [...mine].reverse().find((e) => e?.highlight);
        return (
          <a key={m.id} className="fm-sheet hm-person" href={routeHash({ name: 'family', person: m.id })}
             aria-label={`${name(me, m)}: åbn`}>
            <div className="hm-person-head">
              <span className="hm-avatar" aria-hidden>{m.username[0]?.toUpperCase()}</span>
              <b>{name(me, m)}</b>
              <span className="hm-person-avg">{avg == null ? 'Intet i ugen' : <>{face(avg)} {one(avg)}</>}</span>
            </div>
            <div className="hm-person-week">
              {days.map((d, i) => (
                <span key={d} className={`hm-mini${mine[i] ? ` hm-has hm-m${Math.round(mine[i]!.mood ?? 0)}` : ''}`}>
                  <small>{weekdayLetter(d)}</small>{mine[i] ? face(mine[i]!.mood) : '·'}
                </span>
              ))}
            </div>
            {last && <p className="hm-person-quote">“{last.highlight}” <small>{dayTitle(last.day, today)}</small></p>}
          </a>
        );
      })}
    </>
  );
}

// ---- one person's days ------------------------------------------------------------------

function PersonDays({ uid, today }: { uid: number; today: string }) {
  const [page, setPage] = useState<DagbogPerson | null>(null);
  const [entries, setEntries] = useState<DagbogEntry[]>([]);
  const [from, setFrom] = useState<string | null>(null);     // jumped to a day in the calendar
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setBusy(true); setError(null);
    homeApi.person(uid, from ? addDays(from, 1) : null)
      .then((p) => { setPage(p); setEntries(p.entries); })
      .catch((e) => setError(e.message)).finally(() => setBusy(false));
  }, [uid, from]);

  async function older() {
    if (!entries.length) return;
    setBusy(true);
    try {
      const p = await homeApi.person(uid, entries[entries.length - 1].day);
      setPage(p); setEntries((xs) => [...xs, ...p.entries]);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  if (error) return <p className="fm-error">{error}</p>;
  if (!page) return <p className="fm-note">Henter…</p>;
  if (page.total === 0) {
    return <p className="fm-sheet hm-empty-note">{page.own ? 'Du har ikke skrevet nogen dage endnu.'
      : `${page.person.username} har ikke skrevet nogen dage endnu.`}</p>;
  }
  return (
    <>
      <MoodMonth uid={uid} today={today} first={page.firstDay} picked={from} onPick={setFrom} />
      {from && (
        <p className="hm-jump">Fra {dayTitle(from, today).toLowerCase()} og tilbage ·{' '}
          <button className="fm-link" onClick={() => setFrom(null)}>Til i dag</button></p>
      )}
      {entries.length === 0 && <p className="fm-note">Ingen dage her.</p>}
      {entries.map((e) => <DayCard key={e.day} e={e} own={page.own} uid={uid} today={today} />)}
      {page.more
        ? <button className="fm-secondary hm-older" disabled={busy} onClick={() => void older()}>
            {busy ? 'Henter…' : 'Hent ældre dage'}</button>
        : <p className="fm-dim hm-end">{page.total === 1 ? 'Den eneste dag' : `Det var alle ${page.total} dage`}
            {page.firstDay ? ` - siden ${dayTitle(page.firstDay, today).toLowerCase()}` : ''}.</p>}
    </>
  );
}

/** A month of moods; a filled-in day jumps the list to it. */
function MoodMonth({ uid, today, first, picked, onPick }: {
  uid: number; today: string; first: string | null; picked: string | null; onPick: (d: string) => void;
}) {
  const [month, setMonth] = useState(today.slice(0, 7));
  const [days, setDays] = useState<Record<string, number | null> | null>(null);
  useEffect(() => {
    setDays(null);
    homeApi.personMonth(uid, month).then((m) => setDays(m.days)).catch(() => setDays({}));
  }, [uid, month]);
  const canBack = !!first && month > first.slice(0, 7);
  const canNext = month < today.slice(0, 7);
  return (
    <section className="fm-sheet hm-moodcal" aria-label="Måned">
      <div className="hm-moodcal-head">
        <button className="hm-step-s" aria-label="Måneden før" disabled={!canBack}
                onClick={() => setMonth(addMonths(month, -1))}>‹</button>
        <b>{monthTitle(month)}</b>
        <button className="hm-step-s" aria-label="Måneden efter" disabled={!canNext}
                onClick={() => setMonth(addMonths(month, 1))}>›</button>
      </div>
      <div className="hm-moodcal-grid">
        {['M', 'T', 'O', 'T', 'F', 'L', 'S'].map((l, i) => <span key={i} className="hm-wd">{l}</span>)}
        {monthGrid(month).map((d, i) => {
          if (!d) return <span key={i} />;
          const has = days != null && d in days;
          const mood = days?.[d] ?? null;
          return (
            <button key={d} disabled={!has} aria-label={`${dayTitle(d, today)}${has ? `, ${mood ? `humør ${mood}` : 'udfyldt'}` : ''}`}
                    className={`hm-cal-day${has ? ` hm-has hm-m${mood ?? 0}` : ''}${d === picked ? ' on' : ''}${d === today ? ' hm-today' : ''}`}
                    onClick={() => onPick(d)}>{dayOfMonth(d)}</button>
          );
        })}
      </div>
    </section>
  );
}

function DayCard({ e, own, uid, today }: { e: DagbogEntry; own: boolean; uid: number; today: string }) {
  const facts: string[] = [];
  if (e.exercise) facts.push(`🏃 ${hoursText(e.exercise)} motion`);
  if (e.soda) facts.push(`🥤 ${e.soda} glas sodavand`);
  if (e.alcohol) facts.push(`🍷 ${e.alcohol} ${e.alcohol === 1 ? 'genstand' : 'genstande'}`);
  return (
    <article className="fm-sheet hm-daycard" aria-label={dayTitle(e.day, today)}>
      <header className="hm-daycard-head">
        <span className="hm-daycard-face" aria-hidden>{face(e.mood)}</span>
        <div><b>{dayTitle(e.day, today)}</b>
          <small>{e.mood ? `Humør ${e.mood}/5` : 'Humør ikke angivet'}</small></div>
        {own && <a className="fm-link hm-daycard-edit" href={routeHash({ name: 'dagbog', day: e.day })}>Ret</a>}
      </header>
      {e.mental != null && <div className="hm-daycard-row"><span>Mentalt overskud</span><Dots n={e.mental} max={10} /></div>}
      {facts.length > 0 && <p className="hm-facts">{facts.map((f) => <span key={f}>{f}</span>)}</p>}
      {(e.sick ?? []).length > 0 && (
        <div className="hm-daycard-sick"><span>🤒 {e.sick!.join(', ')}</span>{e.sickNote && <small>{e.sickNote}</small>}</div>
      )}
      {e.tags.length > 0 && <div className="hm-tags hm-tags-ro">{e.tags.map((t) => <span key={t}>{t}</span>)}</div>}
      {(e.foods ?? []).length > 0 && (
        <div className="hm-tags hm-tags-ro hm-tags-food">{e.foods.map((t) => <span key={t}>{t}</span>)}</div>
      )}
      {e.highlight && <blockquote className="hm-quote">{e.highlight}</blockquote>}
      {e.hasPhoto && (
        <img className="hm-daycard-photo" loading="lazy" alt={`Billede fra ${dayTitle(e.day, today).toLowerCase()}`}
             src={homeApi.photoUrl(e.day, e.updatedAt, own ? undefined : uid)} />
      )}
      {own && e.shared === false && (e.highlight || e.hasPhoto) && (
        <p className="hm-private">🔒 Kun du kan se teksten og billedet fra denne dag.</p>
      )}
    </article>
  );
}

// ---- one person's statistics ------------------------------------------------------------

const RANGES: [string, number | null][] = [['30 dage', 30], ['3 mdr', 91], ['12 mdr', 365], ['Alt', null]];
const WEEKDAYS = ['man', 'tir', 'ons', 'tor', 'fre', 'lør', 'søn'];

function PersonStats({ uid, today }: { uid: number; today: string }) {
  const [range, setRange] = useState<number | null>(30);
  const [s, setS] = useState<DagbogStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setS(null); setError(null);
    homeApi.dagbogStats(uid, range == null ? '' : addDays(today, 1 - range)).then(setS).catch((e) => setError(e.message));
  }, [uid, range, today]);
  const has = (k: string) => !s || s.fields.includes(k);

  return (
    <>
      <div className="hm-range" role="group" aria-label="Periode">
        {RANGES.map(([label, n]) => (
          <button key={label} className={range === n ? 'on' : ''} aria-pressed={range === n}
                  onClick={() => setRange(n)}>{label}</button>
        ))}
      </div>
      {error && <p className="fm-error">{error}</p>}
      {!s && !error && <p className="fm-note">Regner…</p>}
      {s && s.days === 0 && <p className="fm-sheet hm-empty-note">Ingen dage i perioden.</p>}
      {s && s.days > 0 && (
        <>
          <section className="hm-kpis" aria-label="Tal">
            <Kpi label="Dage skrevet" value={String(s.days)} sub={`${s.coverage}% af dagene`} />
            <Kpi label="Længste stribe" value={String(s.bestStreak)} sub="dage i træk" />
            {has('mood') && s.mood != null && <Kpi label="Humør" value={`${face(s.mood)} ${one(s.mood)}`} sub="af 5 i snit" />}
            {has('mental') && s.mental != null && <Kpi label="Mentalt overskud" value={one(s.mental)} sub="af 10 i snit" />}
            {has('exercise') && <Kpi label="Motion" value={`${one(s.exerciseHoursPerWeek ?? 0)} t`} sub="om ugen i snit" />}
            {has('alcohol') && <Kpi label="Alkohol" value={one(s.alcoholPerWeek ?? 0)} sub="genstande om ugen i snit" />}
            {has('soda') && <Kpi label="Sodavand" value={one(s.sodaPerWeek ?? 0)} sub="glas om ugen i snit" />}
            {has('sick') && <Kpi label="Syg eller skadet" value={String(s.sickDays ?? 0)} sub={s.sickDays === 1 ? 'dag' : 'dage'} />}
          </section>
          {s.days < 14 && <p className="hm-lead">Ugetallene er regnet ud fra {s.days === 1 ? 'én dag' : `${s.days} dage`} - de bliver mere sikre, jo flere dage der er skrevet.</p>}
          {has('mood') && (s.months ?? []).length > 1 && <MonthBars months={s.months!} />}
          {has('mood') && (s.weekdays ?? []).some((x) => x != null) && (
            <section className="fm-sheet hm-stat" aria-label="Humør pr. ugedag">
              <h3 className="hm-field-label">Humør pr. ugedag</h3>
              {s.weekdays!.map((v, i) => (
                <div key={i} className="hm-hbar"><span>{WEEKDAYS[i]}</span>
                  <i><b className={`hm-m${v == null ? 0 : Math.round(v)}`} style={{ width: `${v == null ? 0 : (v / 5) * 100}%` }} /></i>
                  <em>{v == null ? '–' : `${face(v)} ${one(v)}`}</em></div>
              ))}
            </section>
          )}
          {(s.links ?? []).length > 0 && (
            <section className="fm-sheet hm-stat" aria-label="Det følger med humøret">
              <h3 className="hm-field-label">Det følger med humøret</h3>
              <ul className="hm-links">
                {s.links!.map((l) => (
                  <li key={l.kind + l.label}>
                    <span className={`hm-arrow ${l.diff > 0 ? 'up' : 'down'}`} aria-hidden>{l.diff > 0 ? '▲' : '▼'}</span>
                    <div><b>{l.label}</b> <small>{l.kind.toLowerCase()} · {l.days} dage</small>
                      <p>Humør {one(l.with)} med, {one(l.without)} uden</p></div>
                  </li>
                ))}
              </ul>
              <p className="fm-dim hm-small">Det viser hvad der går sammen med et godt eller dårligt humør - ikke hvad der er årsagen.</p>
            </section>
          )}
          {has('tags') && <TopList title="Mest lavet" items={s.topTags ?? []} days={s.days} />}
          {has('foods') && <TopList title="Mest spist" items={s.topFoods ?? []} days={s.days} />}
          {has('sick') && <TopList title="Sygdom og skader" items={s.topSick ?? []} days={s.days} />}
        </>
      )}
    </>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string; sub: string }) {
  return <div className="fm-sheet hm-kpi"><small>{label}</small><b>{value}</b><span>{sub}</span></div>;
}

function MonthBars({ months }: { months: NonNullable<DagbogStats['months']> }) {
  const shown = months.slice(-12);
  return (
    <section className="fm-sheet hm-stat" aria-label="Humør pr. måned">
      <h3 className="hm-field-label">Humør pr. måned</h3>
      <div className="hm-vbars">
        {shown.map((m) => (
          <div key={m.month} className="hm-vbar" title={`${monthTitle(m.month)}: ${m.days} dage`}>
            <em>{m.mood == null ? '' : one(m.mood)}</em>
            <i><b className={`hm-m${m.mood == null ? 0 : Math.round(m.mood)}`} style={{ height: `${m.mood == null ? 0 : (m.mood / 5) * 100}%` }} /></i>
            <span>{monthShort(m.month)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function TopList({ title, items, days }: { title: string; items: DagbogCount[]; days: number }) {
  if (!items.length) return null;
  const top = items[0].days;
  return (
    <section className="fm-sheet hm-stat" aria-label={title}>
      <h3 className="hm-field-label">{title}</h3>
      {items.map((t) => (
        <div key={t.name} className="hm-hbar hm-hbar-wide"><span>{t.name}</span>
          <i><b style={{ width: `${(t.days / top) * 100}%` }} /></i>
          <em>{t.days} {t.days === 1 ? 'dag' : 'dage'} · {Math.round((t.days / days) * 100)}%</em></div>
      ))}
    </section>
  );
}
