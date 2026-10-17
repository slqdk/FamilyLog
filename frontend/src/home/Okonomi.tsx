import { useCallback, useEffect, useMemo, useState } from 'react';
import { Markdown } from '../core/Markdown';
import { CategoryOptions } from '../sections/ledger/CategoryOptions';
import {
  homeApi, type OkAsk, type OkData, type OkMerchant, type OkOverview, type OkState, type OkTrend, type OkTx,
  type OkTxQuery,
} from './api';
import { Bar } from './Dagbog';
import { addDays, addMonths, kr, monthShort, monthTitle, shortDate, todayLocal } from './logic';

/** Økonomi on the phone (FamilyLog 0.3.0; per person 0.3.3; 0.3.5 more of the
    admin app's options): your own bank data - an overview for any period and
    account, the transactions to search, your shops to move or rename, the
    months side by side - Alf to ask, and "Dine data". Nobody sees anyone
    else's. */

type Tab = 'overblik' | 'posteringer' | 'butikker' | 'udvikling';
type Mode = 'month' | 'year' | '12m' | 'all' | 'custom';
interface Period { mode: Mode; month: string; year: string; from: string; to: string }

const TABS: [Tab, string][] = [['overblik', 'Overblik'], ['posteringer', 'Posteringer'], ['butikker', 'Butikker'],
  ['udvikling', 'Udvikling']];

function lastDay(month: string) { return addDays(`${addMonths(month, 1)}-01`, -1); }

/** The period as dates (empty = from the beginning / to the end) and a title. */
export function periodRange(p: Period, lastData: string): { frm: string; to: string; title: string } {
  switch (p.mode) {
    case 'month': return { frm: `${p.month}-01`, to: lastDay(p.month), title: monthTitle(p.month) };
    case 'year': return { frm: `${p.year}-01-01`, to: `${p.year}-12-31`, title: p.year };
    case '12m': {
      const end = lastData.slice(0, 7);
      return { frm: `${addMonths(end, -11)}-01`, to: lastDay(end), title: 'Seneste 12 måneder' };
    }
    case 'all': return { frm: '', to: '', title: 'Hele perioden' };
    case 'custom': return { frm: p.from, to: p.to,
      title: p.from && p.to ? `${shortDate(p.from)} ${p.from.slice(0, 4)} - ${shortDate(p.to)} ${p.to.slice(0, 4)}` : 'Vælg datoer' };
  }
}

function load<T>(key: string, fallback: T): T {
  try { const v = localStorage.getItem(key); return v ? { ...fallback, ...JSON.parse(v) } : fallback; } catch { return fallback; }
}

export function OkonomiPage({ month, me }: { month: string | null; me?: { role: string } }) {
  const [st, setSt] = useState<OkState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [tab, setTab] = useState<Tab>(() => load('ok.view', { tab: 'overblik' as Tab }).tab);
  const [period, setPeriod] = useState<Period | null>(null);
  const [account, setAccount] = useState('');
  const [sheet, setSheet] = useState<{ key: string; name: string; category: string; sample?: string } | null>(null);
  useEffect(() => { homeApi.okState().then(setSt).catch((e) => setError(e.message)); }, [version]);
  useEffect(() => { try { localStorage.setItem('ok.view', JSON.stringify({ tab })); } catch { /* */ } }, [tab]);
  const reload = () => setVersion((v) => v + 1);
  const ready = st?.access && st.count > 0 ? st : null;
  useEffect(() => {
    if (!ready || period) return;
    const lastMonth = ready.months[ready.months.length - 1];
    const m = month && ready.months.includes(month) ? month : lastMonth;
    setPeriod({ mode: 'month', month: m, year: m.slice(0, 4), from: `${m}-01`, to: lastDay(m) });
  }, [ready, period, month]);

  if (error) return <Shell><p className="fm-error">{error}</p></Shell>;
  if (!st) return <Shell><p className="fm-note">Henter…</p></Shell>;
  if (!st.access) {
    return <Shell><section className="fm-sheet hm-field"><p>Du har ikke Økonomi.</p>
      <p className="fm-dim">Administratoren kan slå det til for dig under Indstillinger → Accounts.</p></section></Shell>;
  }
  if (st.count === 0) {
    return (
      <Shell>
        <section className="fm-sheet hm-field">
          <h3 className="hm-field-label">Kom i gang</h3>
          <p>Hent en udskrift af dine posteringer i netbanken (CSV eller Excel) og læs den ind her.
            Kun du kan se dine tal.</p>
        </section>
        <DataSection onChange={reload} open />
      </Shell>
    );
  }
  if (!period) return <Shell><p className="fm-note">Henter…</p></Shell>;
  const range = periodRange(period, st.lastDate ?? todayLocal());
  const edit = (m: { key: string; name: string; category: string; sample?: string }) => setSheet(m);
  return (
    <Shell>
      <nav className="hm-tabs ok-tabs" aria-label="Økonomi">
        {TABS.map(([k, label]) => (
          <button key={k} className={tab === k ? 'on' : ''} aria-pressed={tab === k} onClick={() => setTab(k)}>{label}</button>
        ))}
      </nav>
      {tab !== 'butikker' && tab !== 'udvikling' && (
        <PeriodBar st={st} period={period} setPeriod={setPeriod} account={account} setAccount={setAccount} title={range.title} />
      )}
      {tab === 'overblik' && (
        <>
          <Overview range={range} account={account} onEdit={edit} key={`${range.frm}|${range.to}|${account}|${version}`} />
          <Ask initial={st.ask} model={st.model} />
          <DataSection onChange={reload} />
          {me && me.role !== 'family' && <p className="ok-foot"><a href="/app/#ledger">Økonomi i admin-appen</a></p>}
        </>
      )}
      {tab === 'posteringer' && <Transactions range={range} account={account} onEdit={edit} version={version} />}
      {tab === 'butikker' && <Shops onEdit={edit} version={version} />}
      {tab === 'udvikling' && <Trend accounts={st.accounts} />}
      {sheet && <MerchantSheet m={sheet} onClose={() => setSheet(null)} onSaved={() => { setSheet(null); reload(); }} />}
    </Shell>
  );
}

/** Which period and account: a month or year to step through, the last 12
    months, everything, or your own dates. */
function PeriodBar({ st, period, setPeriod, account, setAccount, title }: {
  st: Extract<OkState, { access: true }>; period: Period; setPeriod: (p: Period) => void;
  account: string; setAccount: (a: string) => void; title: string;
}) {
  const months = st.months;
  const years = Array.from(new Set(months.map((m) => m.slice(0, 4))));
  const step = (n: number) => {
    if (period.mode === 'month') setPeriod({ ...period, month: addMonths(period.month, n) });
    if (period.mode === 'year') setPeriod({ ...period, year: String(Number(period.year) + n) });
  };
  const canBack = period.mode === 'month' ? period.month > months[0] : period.mode === 'year' ? period.year > years[0] : false;
  const canFwd = period.mode === 'month' ? period.month < months[months.length - 1]
    : period.mode === 'year' ? period.year < years[years.length - 1] : false;
  const steps = period.mode === 'month' || period.mode === 'year';
  return (
    <div className="ok-period">
      <div className="hm-daynav">
        {steps ? <button className="hm-step" aria-label="Før" disabled={!canBack} onClick={() => step(-1)}>‹</button>
          : <span className="hm-step hm-step-off" aria-hidden>‹</span>}
        <span className="hm-dayname">{title}</span>
        {steps ? <button className="hm-step" aria-label="Efter" disabled={!canFwd} onClick={() => step(1)}>›</button>
          : <span className="hm-step hm-step-off" aria-hidden>›</span>}
      </div>
      <div className="ok-filters">
        <select aria-label="Periode" value={period.mode} onChange={(e) => setPeriod({ ...period, mode: e.target.value as Mode })}>
          <option value="month">Måned</option>
          <option value="year">År</option>
          <option value="12m">Seneste 12 måneder</option>
          <option value="all">Hele perioden</option>
          <option value="custom">Vælg datoer</option>
        </select>
        {st.accounts.length > 1 && (
          <select aria-label="Konto" value={account} onChange={(e) => setAccount(e.target.value)}>
            <option value="">Alle konti</option>
            {st.accounts.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        )}
      </div>
      {period.mode === 'custom' && (
        <div className="ok-filters">
          <input type="date" aria-label="Fra" value={period.from} onChange={(e) => setPeriod({ ...period, from: e.target.value })} />
          <input type="date" aria-label="Til" value={period.to} onChange={(e) => setPeriod({ ...period, to: e.target.value })} />
        </div>
      )}
    </div>
  );
}

function Overview({ range, account, onEdit }: {
  range: { frm: string; to: string; title: string }; account: string;
  onEdit: (m: { key: string; name: string; category: string }) => void;
}) {
  const [d, setD] = useState<OkOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<{ category?: string; merchant?: string; label: string } | null>(null);
  useEffect(() => {
    if (range.frm && range.to && range.frm > range.to) { setError('Fra-datoen ligger efter til-datoen.'); return; }
    homeApi.okOverview(range.frm, range.to, account).then(setD).catch((e) => setError(e.message));
  }, [range.frm, range.to, account]);
  if (error) return <p className="fm-error">{error}</p>;
  if (!d) return <p className="fm-note">Henter…</p>;
  const base = d.baselinePerMonth;
  const diff = base ? (d.spent - base) / base : null;
  const top = Math.max(...d.categories.map((c) => Math.max(c.spent, c.usual ?? 0)), 1);
  const txBase = { frm: range.frm, to: range.to, account };
  return (
    <>
      <section className="fm-sheet ok-hero" aria-label="Perioden">
        <p className="ok-hero-label">Brugt{account ? ` · ${account}` : ''}</p>
        <p className="ok-hero-num">{kr(d.spent)}</p>
        <p className="ok-hero-sub">
          {d.income > 0 && <>Indtægter {kr(d.income)}</>}
          {d.income > 0 && (diff != null || !d.isMonth) && ' · '}
          {diff != null && (
            <span className={diff > 0.05 ? 'ok-up' : diff < -0.05 ? 'ok-down' : ''}>
              {Math.abs(diff) < 0.05 ? 'som en normal måned'
                : `${Math.round(Math.abs(diff) * 100)} % ${diff > 0 ? 'over' : 'under'} en normal måned`}
            </span>
          )}
          {!d.isMonth && d.months > 1 && <>{kr(d.perMonth)} pr. måned i snit</>}
        </p>
        {d.days && <DayBars days={d.days} />}
        {base != null && <p className="ok-note">Normal måned: snittet af de {d.baselineMonths} måneder før ({kr(base)}).</p>}
      </section>

      <section className="fm-sheet hm-field" aria-label="Kategorier">
        <h3 className="hm-field-label">Hvor gik pengene hen?</h3>
        {d.categories.length === 0 && <p className="fm-dim">Intet forbrug i perioden.</p>}
        <ul className="ok-cats">
          {d.categories.map((c) => (
            <li key={c.key || '-'}>
              <button className="ok-cat" aria-expanded={open?.category === c.key}
                      onClick={() => setOpen(open?.category === c.key ? null : { category: c.key, label: c.name })}>
                <span className="ok-cat-row"><span className="ok-cat-name">{c.name}</span>
                  <b>{kr(c.spent)}</b></span>
                <span className="ok-bar" aria-hidden>
                  <span style={{ width: `${(c.spent / top) * 100}%` }} />
                  {c.usual != null && <i style={{ left: `${(c.usual / top) * 100}%` }} title="Normal måned" />}
                </span>
              </button>
              {open?.category === c.key && <TxList query={{ ...txBase, category: c.key }} label={c.name} onEdit={onEdit} />}
            </li>
          ))}
        </ul>
        {d.categories.some((c) => c.usual != null) && <p className="ok-note"><i className="ok-tick" /> = en normal måned</p>}
      </section>

      {d.topMerchants.length > 0 && (
        <section className="fm-sheet hm-field" aria-label="Største butikker">
          <h3 className="hm-field-label">Største modtagere</h3>
          <ul className="ok-list">
            {d.topMerchants.map((t) => (
              <li key={t.key}>
                <button className="ok-row" onClick={() => setOpen(open?.merchant === t.key ? null : { merchant: t.key, label: t.name })}>
                  <span><span className="ok-row-name">{t.name}</span>
                    <small>{t.categoryName} · {t.count} {t.count === 1 ? 'gang' : 'gange'}</small></span>
                  <b>{kr(t.spent)}</b>
                </button>
                {open?.merchant === t.key && (
                  <>
                    <button className="fm-link ok-edit-link" onClick={() => onEdit(t)}>Flyt eller omdøb {t.name}</button>
                    <TxList query={{ ...txBase, merchant: t.key }} label={t.name} onEdit={onEdit} />
                  </>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {d.recurring.length > 0 && (
        <section className="fm-sheet hm-field" aria-label="Faste udgifter">
          <h3 className="hm-field-label">Faste udgifter</h3>
          <ul className="ok-list">
            {d.recurring.map((r) => (
              <li key={r.key}>
                <button className="ok-row" onClick={() => onEdit(r)}>
                  <span><span className="ok-row-name">{r.name}</span><small>{r.categoryName}</small></span>
                  <span className="ok-right"><b>{kr(r.typical)}</b><small>{kr(r.yearly)} om året</small></span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function TxRows({ rows, onEdit }: { rows: OkTx[]; onEdit: (m: { key: string; name: string; category: string; sample?: string }) => void }) {
  return (
    <>
      {rows.map((r, i) => (
        <button key={i} className="ok-tx-row" onClick={() => onEdit({ key: r.merchantKey, name: r.merchant, category: r.category, sample: r.text })}
                aria-label={`${shortDate(r.date)} ${r.merchant} ${kr(r.amount, true)} - ${r.categoryName}`}>
          <span className="ok-tx-date">{shortDate(r.date)}</span>
          <span className="ok-tx-text">{r.merchant}<small>{r.categoryName}</small></span>
          <span className={r.amount < 0 ? '' : 'ok-in'}>{kr(r.amount, true)}</span>
        </button>
      ))}
    </>
  );
}

function TxList({ query, label, onEdit }: {
  query: OkTxQuery; label: string; onEdit: (m: { key: string; name: string; category: string; sample?: string }) => void;
}) {
  const [rows, setRows] = useState<OkTx[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify(query);
  useEffect(() => {
    homeApi.okTx(JSON.parse(key)).then((t) => { setRows(t.rows); setTotal(t.total); }).catch((e) => setError(e.message));
  }, [key]);
  if (error) return <p className="fm-error">{error}</p>;
  if (!rows) return <p className="fm-note ok-tx-wait">Henter…</p>;
  return (
    <div className="ok-tx" aria-label={`Posteringer: ${label}`}>
      <TxRows rows={rows} onEdit={onEdit} />
      {total > rows.length && <p className="ok-note">… og {total - rows.length} mere (se Posteringer)</p>}
    </div>
  );
}

/** All transactions: search, category, in/out and order; 50 at a time. */
function Transactions({ range, account, onEdit, version }: {
  range: { frm: string; to: string }; account: string; version: number;
  onEdit: (m: { key: string; name: string; category: string; sample?: string }) => void;
}) {
  const [q, setQ] = useState('');
  const [typed, setTyped] = useState('');
  const [category, setCategory] = useState('*');
  const [direction, setDirection] = useState<'' | 'in' | 'out'>('');
  const [order, setOrder] = useState<OkTxQuery['order']>('newest');
  const [rows, setRows] = useState<OkTx[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [sum, setSum] = useState(0);
  const [cats, setCats] = useState<{ key: string; name: string; group?: string }[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { homeApi.okMerchants('', '*').then((r) => setCats(r.categories)).catch(() => {}); }, []);
  useEffect(() => { const t = window.setTimeout(() => setQ(typed.trim()), 300); return () => window.clearTimeout(t); }, [typed]);
  const query: OkTxQuery = useMemo(() => ({ frm: range.frm, to: range.to, account, q, direction, order,
    ...(category === '*' ? {} : { category }) }), [range.frm, range.to, account, q, direction, order, category]);
  useEffect(() => {
    setTotal(null); setError(null);
    homeApi.okTx({ ...query, offset: 0 }).then((t) => { setRows(t.rows); setTotal(t.total); setSum(t.sum); })
      .catch((e) => setError(e.message));
  }, [query, version]);
  async function more() {
    try { const t = await homeApi.okTx({ ...query, offset: rows.length }); setRows([...rows, ...t.rows]); }
    catch (e) { setError((e as Error).message); }
  }
  return (
    <section className="fm-sheet hm-field" aria-label="Posteringer">
      <input className="ok-search" type="search" placeholder="Søg i posteringer" aria-label="Søg i posteringer"
             value={typed} onChange={(e) => setTyped(e.target.value)} />
      <div className="ok-filters ok-filters-tight">
        <select aria-label="Kategori" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="*">Alle kategorier</option>
          <option value="">Ikke kategoriseret</option>
          <CategoryOptions categories={cats} label={(c) => c.name} />
        </select>
        <select aria-label="Ind eller ud" value={direction} onChange={(e) => setDirection(e.target.value as '' | 'in' | 'out')}>
          <option value="">Ind og ud</option><option value="out">Penge ud</option><option value="in">Penge ind</option>
        </select>
        <select aria-label="Sortering" value={order} onChange={(e) => setOrder(e.target.value as OkTxQuery['order'])}>
          <option value="newest">Nyeste først</option><option value="oldest">Ældste først</option>
          <option value="largest">Største udgift først</option><option value="income">Største indtægt først</option>
        </select>
      </div>
      {error && <p className="fm-error">{error}</p>}
      {total == null ? <p className="fm-note">Henter…</p> : (
        <>
          <p className="ok-note">{total} posteringer · i alt {kr(sum, true)}</p>
          <div className="ok-tx ok-tx-full"><TxRows rows={rows} onEdit={onEdit} /></div>
          {rows.length < total && <button className="fm-secondary ok-more" onClick={() => void more()}>Vis flere ({total - rows.length} tilbage)</button>}
          <p className="ok-note">Tryk på en postering for at flytte butikken til en anden kategori eller omdøbe den.</p>
        </>
      )}
    </section>
  );
}

/** Your shops and payees, the most money first. */
function Shops({ onEdit, version }: { onEdit: (m: { key: string; name: string; category: string; sample?: string }) => void; version: number }) {
  const [typed, setTyped] = useState('');
  const [q, setQ] = useState('');
  const [category, setCategory] = useState('*');
  const [data, setData] = useState<{ merchants: OkMerchant[]; categories: { key: string; name: string; group?: string }[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { const t = window.setTimeout(() => setQ(typed.trim()), 300); return () => window.clearTimeout(t); }, [typed]);
  useEffect(() => { homeApi.okMerchants(q, category).then(setData).catch((e) => setError(e.message)); }, [q, category, version]);
  return (
    <section className="fm-sheet hm-field" aria-label="Butikker">
      <input className="ok-search" type="search" placeholder="Søg efter butik" aria-label="Søg efter butik"
             value={typed} onChange={(e) => setTyped(e.target.value)} />
      <div className="ok-filters ok-filters-tight">
        <select aria-label="Kategori" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="*">Alle kategorier</option>
          <option value="">Ikke kategoriseret</option>
          {data && <CategoryOptions categories={data.categories} label={(c) => c.name} />}
        </select>
      </div>
      {error && <p className="fm-error">{error}</p>}
      {!data ? <p className="fm-note">Henter…</p> : (
        <ul className="ok-list">
          {data.merchants.length === 0 && <li className="fm-dim">Ingen butikker.</li>}
          {data.merchants.map((m) => (
            <li key={m.key}>
              <button className="ok-row" onClick={() => onEdit(m)}>
                <span><span className="ok-row-name">{m.name}</span>
                  <small>{m.categoryName}{m.source === 'user' ? ' · valgt af dig' : m.source === 'model' ? ' · placeret af Alf' : ''} · {m.count} {m.count === 1 ? 'gang' : 'gange'}</small></span>
                <b className={m.total > 0 ? 'ok-in' : ''}>{kr(m.total)}</b>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Move a shop to another category, or give it a better name. */
function MerchantSheet({ m, onClose, onSaved }: {
  m: { key: string; name: string; category: string; sample?: string }; onClose: () => void; onSaved: () => void;
}) {
  const [name, setName] = useState(m.name);
  const [category, setCategory] = useState(m.category === 'gas-station' ? 'fuel' : m.category);
  const [cats, setCats] = useState<{ key: string; name: string; group?: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { homeApi.okMerchants('', '*').then((r) => setCats(r.categories)).catch(() => {}); }, []);
  async function save() {
    setBusy(true); setError(null);
    try {
      const change: { category?: string; name?: string } = {};
      if (category && category !== m.category) change.category = category;
      if (name.trim() && name.trim() !== m.name) change.name = name.trim();
      if (Object.keys(change).length) await homeApi.okSetMerchant(m.key, change);
      onSaved();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return (
    <div className="fm-scrim ok-scrim" role="dialog" aria-modal="true" aria-label={`Ret ${m.name}`} onClick={onClose}>
      <section className="ok-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="ok-sheet-head"><h3>Ret butik</h3>
          <button className="fm-x" aria-label="Luk" onClick={onClose}>×</button></div>
        {m.sample && <p className="ok-note">{m.sample}</p>}
        <label className="fm-field"><span className="fm-label">Navn</span>
          <input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} /></label>
        <label className="fm-field"><span className="fm-label">Kategori</span>
          <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Kategori for butikken">
            {!category && <option value="">Ikke kategoriseret</option>}
            <CategoryOptions categories={cats} label={(c) => c.name} />
          </select></label>
        <p className="ok-note">Gælder alle køb hos butikken - også de næste, du læser ind.
          {category === 'fuel' ? ' Køb under 300 kr på en tankstation tæller som Tankstationer.' : ''}</p>
        {error && <p className="fm-error">{error}</p>}
        <button className="fm-primary" disabled={busy} onClick={() => void save()}>{busy ? 'Gemmer…' : 'Gem'}</button>
      </section>
    </div>
  );
}

/** The months side by side: what went out (and came in) each month, or one
    category's months. */
function Trend({ accounts }: { accounts: string[] }) {
  const [months, setMonths] = useState(12);
  const [account, setAccount] = useState('');
  const [category, setCategory] = useState('');
  const [d, setD] = useState<OkTrend | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setD(null); homeApi.okTrend(months, account).then(setD).catch((e) => setError(e.message)); }, [months, account]);
  const series = useMemo(() => (d?.months ?? []).map((m) => ({
    month: m.month, value: category ? (m.byCategory[category] ?? 0) : m.spent, income: m.income })), [d, category]);
  const max = Math.max(1, ...series.map((s) => Math.max(s.value, category ? 0 : s.income)));
  const avg = series.length ? series.reduce((a, s) => a + s.value, 0) / series.length : 0;
  const catName = d?.categories.find((c) => c.key === category)?.name;
  return (
    <section className="fm-sheet hm-field" aria-label="Udvikling">
      <div className="ok-filters ok-filters-tight">
        <select aria-label="Måneder" value={months} onChange={(e) => setMonths(Number(e.target.value))}>
          <option value={6}>6 måneder</option><option value={12}>12 måneder</option>
          <option value={24}>24 måneder</option><option value={0}>Alle måneder</option>
        </select>
        <select aria-label="Hvad" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">Alt forbrug</option>
          {(d?.categories ?? []).map((c) => <option key={c.key || '-'} value={c.key}>{c.name}</option>)}
        </select>
        {accounts.length > 1 && (
          <select aria-label="Konto" value={account} onChange={(e) => setAccount(e.target.value)}>
            <option value="">Alle konti</option>
            {accounts.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        )}
      </div>
      {error && <p className="fm-error">{error}</p>}
      {!d ? <p className="fm-note">Henter…</p> : (
        <>
          <p className="ok-note">{catName ?? 'Alt forbrug'}: {kr(avg)} pr. måned i snit
            {!category && ' · den lyse streg er indtægterne'}</p>
          <ul className="ok-trend">
            {series.map((s) => (
              <li key={s.month}>
                <span className="ok-trend-m">{monthShort(s.month)} {s.month.slice(2, 4)}</span>
                <span className="ok-trend-bar" aria-hidden>
                  <span style={{ width: `${(s.value / max) * 100}%` }} />
                  {!category && s.income > 0 && <i style={{ left: `${Math.min(100, (s.income / max) * 100)}%` }} />}
                </span>
                <b className={s.value > avg * 1.15 ? 'ok-up' : ''}>{kr(s.value)}</b>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

/** Your own data: import a bank export, the imports so far, and the shops
    still without a category (pick one, or let the model place them). */
function DataSection({ onChange, open = false }: { onChange: () => void; open?: boolean }) {
  const [d, setD] = useState<OkData | null>(null);
  const [show, setShow] = useState(open);
  const [account, setAccount] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => homeApi.okData().then(setD).catch((e) => setError(e.message)), []);
  useEffect(() => { if (show) void load(); }, [show, load]);
  const running = d?.categorise.state === 'queued' || d?.categorise.state === 'working';
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => { void load(); }, 1500);
    return () => window.clearInterval(t);
  }, [running, load]);

  async function upload(file: File | undefined) {
    if (!file) return;
    setBusy(true); setError(null); setNote(null);
    try {
      const r = await homeApi.okImport(file, account.trim() || 'Bank');
      setNote(`${r.added} nye posteringer${r.alreadyThere ? `, ${r.alreadyThere} kendte i forvejen` : ''}.`);
      await load(); onChange();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function place(key: string, category: string) {
    if (!category) return;
    setError(null);
    try { await homeApi.okSetCategory(key, category); await load(); onChange(); }
    catch (e) { setError((e as Error).message); }
  }

  return (
    <section className="fm-sheet hm-field ok-data" aria-label="Dine data">
      <button className="ok-data-head" aria-expanded={show} onClick={() => setShow(!show)}>
        <h3 className="hm-field-label">Dine data</h3>
        <span>{show ? '▴' : '▾'}</span>
      </button>
      {show && (
        <>
          <div className="ok-import">
            <input value={account} maxLength={60} placeholder="Konto, fx Lønkonto" aria-label="Konto"
                   onChange={(e) => setAccount(e.target.value)} />
            <label className={`fm-secondary ok-pick${busy ? ' ok-busy' : ''}`}>
              {busy ? 'Læser…' : 'Læs bankudskrift ind'}
              <input type="file" accept=".csv,.txt,.xlsx,text/csv" hidden disabled={busy}
                     onChange={(e) => { void upload(e.target.files?.[0]); e.target.value = ''; }} />
            </label>
          </div>
          <p className="ok-note">CSV eller Excel fra netbanken. Posteringer, der allerede er her, bliver genkendt.</p>
          {note && <p className="ok-ok">{note}</p>}
          {error && <p className="fm-error">{error}</p>}
          {d && d.left > 0 && (
            <div className="ok-uncat">
              <h4>Mangler kategori ({d.left})</h4>
              {running && <p className="fm-dim">Alf placerer butikkerne… {d.categorise.left} tilbage</p>}
              {!running && d.model && (
                <button className="fm-link" onClick={async () => {
                  try { setD(await homeApi.okCategorise()); } catch (e) { setError((e as Error).message); }
                }}>Lad Alf placere dem</button>
              )}
              <ul className="ok-list">
                {d.uncategorised.slice(0, 25).map((u) => (
                  <li key={u.key} className="ok-row ok-row-static">
                    <span><span className="ok-row-name">{u.name}</span>
                      <small>{u.count} {u.count === 1 ? 'gang' : 'gange'} · {kr(u.total)}</small></span>
                    <select aria-label={`Kategori for ${u.name}`} value="" onChange={(e) => void place(u.key, e.target.value)}>
                      <option value="">Vælg…</option>
                      <CategoryOptions categories={d.categories} label={(c) => c.name} />
                    </select>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {d && d.imports.length > 0 && (
            <div className="ok-imports">
              <h4>Indlæst</h4>
              <ul className="ok-list">
                {d.imports.map((i) => (
                  <li key={i.id} className="ok-row ok-row-static">
                    <span><span className="ok-row-name">{i.account}</span>
                      <small>{i.filename} · {i.added} nye{i.firstDate ? ` · ${shortDate(i.firstDate)} - ${shortDate(i.lastDate!)}` : ''}</small></span>
                    <button className="fm-link fm-danger" onClick={async () => {
                      if (!confirm(`Slet de ${i.added} posteringer fra ${i.filename}?`)) return;
                      try { await homeApi.okDeleteImport(i.id); await load(); onChange(); }
                      catch (e) { setError((e as Error).message); }
                    }}>Slet</button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="fm-page hm-page ok-page">
      <Bar title="Økonomi" />
      <main className="hm-form">{children}</main>
    </div>
  );
}

function DayBars({ days }: { days: { date: string; spent: number }[] }) {
  const max = Math.max(...days.map((x) => x.spent), 1);
  return (
    <div className="ok-days" role="img" aria-label="Forbrug per dag">
      {days.map((x) => (
        <span key={x.date} title={`${shortDate(x.date)}: ${kr(x.spent)}`}
              style={{ height: `${Math.max(2, (x.spent / max) * 100)}%` }} className={x.spent > 0 ? '' : 'ok-zero'} />
      ))}
    </div>
  );
}

const ASK_EXAMPLES = ['Hvad brugte vi på dagligvarer i år?', 'Hvad er vores største faste udgifter?',
  'Hvor meget har vi brugt på restauranter per måned?'];

function Ask({ initial, model }: { initial: OkAsk | null; model: boolean }) {
  const [ask, setAsk] = useState<OkAsk | null>(initial);
  const [q, setQ] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [showRows, setShowRows] = useState(false);
  const running = ask?.state === 'queued' || ask?.state === 'working';
  const poll = useCallback(() => homeApi.okAskState().then((r) => setAsk(r.ask)).catch(() => {}), []);
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(poll, 700);
    return () => window.clearInterval(t);
  }, [running, poll]);
  const rows = useMemo(() => ask?.rows ?? [], [ask]);

  async function send(question: string) {
    question = question.trim();
    if (!question) return;
    setError(null); setShowRows(false);
    try { setAsk((await homeApi.okAsk(question)).ask); setQ(''); }
    catch (e) { setError((e as Error).message); }
  }
  return (
    <section className="fm-sheet hm-field ok-ask" aria-label="Spørg Alf om økonomien">
      <h3 className="hm-field-label">Spørg Alf om økonomien</h3>
      {!model && <p className="fm-dim">Der er ikke valgt en model til Økonomi - administratoren vælger den under Indstillinger.</p>}
      {ask && (
        <div className="ok-answer">
          <p className="ok-q">{ask.question}</p>
          {running && <p className="fm-note">{ask.step || 'Alf tænker…'}{ask.ahead ? ` (${ask.ahead} foran i køen)` : ''}</p>}
          {ask.text && <div className="hm-md"><Markdown text={ask.text} streaming={running} /></div>}
          {ask.error && <p className="fm-error">{ask.error}</p>}
          {ask.state === 'stopped' && <p className="fm-dim">Stoppet.</p>}
          {ask.state === 'done' && ask.counted && <p className="ok-note">Talt: {ask.counted}</p>}
          {ask.state === 'done' && rows.length > 0 && (
            <>
              <button className="fm-link" onClick={() => setShowRows(!showRows)}>
                {showRows ? 'Skjul posteringerne' : `Vis posteringerne (${ask.count ?? rows.length})`}</button>
              {showRows && (
                <div className="ok-tx">
                  {rows.map((r, i) => (
                    <div key={i} className="ok-tx-row"><span className="ok-tx-date">{shortDate(r.date)}</span>
                      <span className="ok-tx-text">{r.merchant}</span>
                      <span className={r.amount < 0 ? '' : 'ok-in'}>{kr(r.amount, true)}</span></div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
      {!ask && model && (
        <div className="ok-examples">
          {ASK_EXAMPLES.map((e) => <button key={e} className="fm-example" onClick={() => void send(e)}>{e}</button>)}
        </div>
      )}
      <form className="ok-ask-row" onSubmit={(e) => { e.preventDefault(); void send(q); }}>
        <input value={q} maxLength={500} placeholder="Fx: Hvad brugte vi på benzin i september?"
               aria-label="Spørgsmål om økonomien" onChange={(e) => setQ(e.target.value)} disabled={!model} />
        {running
          ? <button type="button" className="hm-send hm-stop" aria-label="Stop"
                    onClick={() => homeApi.okAskStop().then((r) => setAsk(r.ask))}>■</button>
          : <button className="hm-send" aria-label="Spørg" disabled={!q.trim() || !model}>↑</button>}
      </form>
      {error && <p className="fm-error">{error}</p>}
    </section>
  );
}
