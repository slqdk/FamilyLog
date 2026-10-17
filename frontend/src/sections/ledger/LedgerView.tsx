import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  kr, ledgerApi, monthLabel,
  type CategoriseState, type LedgerAsk, type LedgerCategory, type LedgerImportResult,
  type LedgerMerchant, type LedgerOverview, type LedgerSummary, type LedgerTx,
} from './api';
import { api } from '../../core/api';
import { Markdown } from '../../core/Markdown';
import { StepTree } from '../../core/StepTree';

/** Økonomi (2.63.0): bank and card exports in, exact numbers out.

    The rows live in SQLite and every number here is counted by the backend.
    A chat model once read the first 200 rows of a long export and
    reported a fraction of one shop's payments - so the model only
    turns a question into a search and writes up the result, and the rows it
    is based on are shown under the answer. */

export type LedgerTab = 'overview' | 'ask' | 'transactions' | 'merchants' | 'import';

export const LEDGER_TABS: [LedgerTab, string][] = [
  ['overview', 'Overview'], ['ask', 'Ask'], ['transactions', 'Transactions'],
  ['merchants', 'Merchants'], ['import', 'Import'],
];

/** What a click on the overview opens in Transactions. */
interface TxFilter { q?: string; category?: string; merchant?: string; merchantName?: string;
                     frm?: string; to?: string; direction?: string }

const KIND_LABEL: Record<string, string> = {
  card: 'Card', mobilepay: 'MobilePay', betalingsservice: 'Betalingsservice', atm: 'Cash',
  transfer: 'Transfer', interest: 'Interest', fee: 'Fee', salary: 'Salary',
  'card-bill': 'Card bill', other: 'Other',
};

function catLabel(cats: LedgerCategory[], key: string): string {
  if (!key) return 'Not categorised';
  return cats.find((c) => c.key === key)?.label ?? key;
}

export function LedgerView({ tab, onTab }: { tab: LedgerTab; onTab: (t: LedgerTab) => void }) {
  const [summary, setSummary] = useState<LedgerSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [txFilter, setTxFilter] = useState<TxFilter | null>(null);
  const [cat, setCat] = useState<CategoriseState | null>(null);

  const refresh = useCallback(() => {
    ledgerApi.summary()
      .then((s) => { setSummary(s); setCat(s.categorise); setError(null); })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  // The model places unknown merchants in the background after an import;
  // follow it so the counts on the page move with it.
  const running = cat?.state === 'queued' || cat?.state === 'working';
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => {
      ledgerApi.categoriseState().then((c) => {
        setCat(c);
        if (c.state !== 'queued' && c.state !== 'working') refresh();
      }).catch(() => {});
    }, 1500);
    return () => window.clearInterval(t);
  }, [running, refresh]);

  const openTx = (f: TxFilter) => { setTxFilter(f); onTab('transactions'); };
  const empty = summary != null && summary.count === 0;

  return (
    <div className="fma led">
      <header className="fma-head" data-help="ledger.header">
        <span className="fma-title">Økonomi</span>
        {summary && summary.count > 0 && (
          <span className="fma-stats">
            {summary.count.toLocaleString('da-DK')} transactions · {summary.firstDate} – {summary.lastDate}
            {summary.accounts.length > 1 && ` · ${summary.accounts.length} accounts`}
          </span>
        )}
        {summary && !empty && <CategoriseBadge state={cat} onStart={async () => {
          try { setCat(await ledgerApi.categorise()); } catch (e) { setError((e as Error).message); }
        }} onStop={async () => setCat(await ledgerApi.categoriseStop())} />}
      </header>
      {error && <p className="fma-error">{error}</p>}
      {!summary ? <div className="empty">Loading…</div>
        : (empty && tab !== 'import') ? (
          <div className="led-empty">
            <h2>No transactions yet</h2>
            <p>Export your account from the bank's netbank as CSV or Excel and import it here.
               Do it again whenever you like - rows already in the ledger are recognised and
               skipped.</p>
            <button className="primary-btn" onClick={() => onTab('import')}>Import a bank export</button>
          </div>
        )
        : tab === 'overview' ? <OverviewTab summary={summary} onOpenTx={openTx} />
        : tab === 'ask' ? <AskTab summary={summary} onModel={refresh} />
        : tab === 'transactions' ? <TransactionsTab summary={summary} filter={txFilter}
                                                    onChanged={refresh} />
        : tab === 'merchants' ? <MerchantsTab summary={summary} onChanged={refresh} onOpenTx={openTx} />
        : <ImportTab summary={summary} onImported={(r) => {
            if (r.categorise) setCat(r.categorise);
            refresh();
          }} onCleared={refresh} />}
    </div>
  );
}

function CategoriseBadge({ state, onStart, onStop }: {
  state: CategoriseState | null; onStart: () => void; onStop: () => void;
}) {
  if (!state) return null;
  const busy = state.state === 'queued' || state.state === 'working';
  if (busy) {
    return (
      <span className="led-cat-badge" data-help="ledger.categorise">
        <span className="led-spin" /> Categorising merchants… {state.placed ?? 0} placed, {state.left} left
        {state.state === 'queued' && state.ahead ? ` (${state.ahead} ahead)` : ''}
        <button className="ghost-btn sm" onClick={onStop}>Stop</button>
      </span>
    );
  }
  if (state.left > 0) {
    return (
      <span className="led-cat-badge" data-help="ledger.categorise">
        {state.left} merchants not categorised
        {state.state === 'failed' && state.error ? ` - ${state.error}` : ''}
        <button className="ghost-btn sm" onClick={onStart}>Categorise with the model</button>
      </span>
    );
  }
  return null;
}

// ---- overview ----------------------------------------------------------------------------

/** The period the overview covers (2.63.1): the last 12 months, one month
    or one year (with ‹ › to step), everything, or a custom range. */
type Mode = '12m' | 'month' | 'year' | 'all' | 'custom';
interface Period { mode: Mode; month: string; year: number; frm: string; to: string }

const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
                     'September', 'October', 'November', 'December'];
const longMonth = (m: string) => `${MONTH_NAMES[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}`;

function monthsBetween(first: string | null, last: string | null): string[] {
  if (!first || !last) return [];
  const out: string[] = [];
  let y = Number(first.slice(0, 4)), m = Number(first.slice(5, 7));
  const ly = Number(last.slice(0, 4)), lm = Number(last.slice(5, 7));
  while (y < ly || (y === ly && m <= lm)) {
    out.push(`${y}-${String(m).padStart(2, '0')}`);
    m += 1; if (m > 12) { m = 1; y += 1; }
  }
  return out.reverse();                     // newest first, as the steppers list them
}

function loadPeriod(last: string | null): Period {
  const lastMonth = (last ?? new Date().toISOString()).slice(0, 7);
  const base: Period = { mode: '12m', month: lastMonth, year: Number(lastMonth.slice(0, 4)), frm: '', to: '' };
  try {
    const raw = localStorage.getItem('ledger.period');
    if (raw) return { ...base, ...JSON.parse(raw) };
    const old = localStorage.getItem('ledger.preset');            // 2.63.0's chips
    if (old === 'year') return { ...base, mode: 'year' };
    if (old === 'lastyear') return { ...base, mode: 'year', year: base.year - 1 };
    if (old === 'all' || old === 'custom') return { ...base, mode: old };
  } catch { /* private mode */ }
  return base;
}

function rangeOf(p: Period, last: string | null): { frm: string; to: string } {
  const end = last ? new Date(last + 'T12:00:00') : new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  if (p.mode === 'all') return { frm: '', to: '' };
  if (p.mode === 'custom') return { frm: p.frm, to: p.to };
  if (p.mode === 'month') return { frm: `${p.month}-01`, to: monthEnd(p.month) };
  if (p.mode === 'year') return { frm: `${p.year}-01-01`, to: `${p.year}-12-31` };
  // The last 12 months up to the newest row, the current month included.
  const start = new Date(end.getFullYear(), end.getMonth() - 11, 1, 12);
  return { frm: iso(start), to: iso(end) };
}

const TOP_CHOICES = [25, 50, 100, 250];

function OverviewTab({ summary, onOpenTx }: { summary: LedgerSummary; onOpenTx: (f: TxFilter) => void }) {
  const [period, setPeriod] = useState<Period>(() => loadPeriod(summary.lastDate));
  const [account, setAccount] = useState('');
  const [top, setTop] = useState<number>(() => {
    try { return Number(localStorage.getItem('ledger.top')) || 50; } catch { return 50; }
  });
  const [ov, setOv] = useState<LedgerOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const range = rangeOf(period, summary.lastDate);
  const months = useMemo(() => monthsBetween(summary.firstDate, summary.lastDate),
                         [summary.firstDate, summary.lastDate]);
  const years = useMemo(() => Array.from(new Set(months.map((m) => Number(m.slice(0, 4))))), [months]);
  const isMonth = period.mode === 'month';

  useEffect(() => {
    try { localStorage.setItem('ledger.period', JSON.stringify(period)); } catch { /* private mode */ }
  }, [period]);
  useEffect(() => {
    try { localStorage.setItem('ledger.top', String(top)); } catch { /* private mode */ }
  }, [top]);
  useEffect(() => {
    ledgerApi.overview(range.frm, range.to, account, top, isMonth ? 12 : 0)
      .then((o) => { setOv(o); setError(null); }).catch((e) => setError(e.message));
  }, [range.frm, range.to, account, top, isMonth, summary.count, summary.uncategorised]);

  const set = (p: Partial<Period>) => setPeriod((cur) => ({ ...cur, ...p }));
  const stepMonth = (d: number) => {
    const i = months.indexOf(period.month) - d;      // newest first
    if (i >= 0 && i < months.length) set({ month: months[i] });
  };
  const stepYear = (d: number) => {
    const y = period.year + d;
    if (years.includes(y)) set({ year: y });
  };

  const spentPos = Math.max(0, ov?.spent ?? 0);
  const maxCat = Math.max(1, ...(ov?.categories.map((c) => c.spent) ?? [1]));
  const base = isMonth ? ov?.baseline ?? null : null;
  const vsBase = base && base.perMonth > 0 && ov ? Math.round((ov.spent / base.perMonth - 1) * 100) : null;
  const periodName = isMonth ? longMonth(period.month)
    : period.mode === 'year' ? String(period.year)
    : `${ov?.firstDate ?? ''} – ${ov?.lastDate ?? ''}`;

  return (
    <div className="fma-main fma-scroll led-overview">
      <div className="fma-toolbar led-period" data-help="ledger.overview">
        {([['12m', 'Last 12 months'], ['month', 'Month'], ['year', 'Year'],
           ['all', 'All'], ['custom', 'Custom']] as [Mode, string][]).map(([m, label]) => (
          <button key={m} className={`led-chip${period.mode === m ? ' on' : ''}`}
                  onClick={() => set({ mode: m })}>{label}</button>
        ))}
        {isMonth && (
          <span className="led-stepper" data-help="ledger.period">
            <button className="ghost-btn sm" title="Month before" disabled={months.indexOf(period.month) >= months.length - 1}
                    onClick={() => stepMonth(-1)}>‹</button>
            <select value={period.month} onChange={(e) => set({ month: e.target.value })}>
              {!months.includes(period.month) && <option value={period.month}>{longMonth(period.month)}</option>}
              {months.map((m) => <option key={m} value={m}>{longMonth(m)}</option>)}
            </select>
            <button className="ghost-btn sm" title="Month after" disabled={months.indexOf(period.month) <= 0}
                    onClick={() => stepMonth(1)}>›</button>
          </span>
        )}
        {period.mode === 'year' && (
          <span className="led-stepper" data-help="ledger.period">
            <button className="ghost-btn sm" title="Year before" disabled={!years.includes(period.year - 1)}
                    onClick={() => stepYear(-1)}>‹</button>
            <select value={period.year} onChange={(e) => set({ year: Number(e.target.value) })}>
              {!years.includes(period.year) && <option value={period.year}>{period.year}</option>}
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
            <button className="ghost-btn sm" title="Year after" disabled={!years.includes(period.year + 1)}
                    onClick={() => stepYear(1)}>›</button>
          </span>
        )}
        {period.mode === 'custom' && (
          <>
            <input type="date" value={period.frm} onChange={(e) => set({ frm: e.target.value })} />
            <input type="date" value={period.to} onChange={(e) => set({ to: e.target.value })} />
          </>
        )}
        {summary.accounts.length > 1 && (
          <select value={account} onChange={(e) => setAccount(e.target.value)}>
            <option value="">All accounts</option>
            {summary.accounts.map((a) => <option key={a.account} value={a.account}>{a.account}</option>)}
          </select>
        )}
      </div>
      {error && <p className="fma-error">{error}</p>}
      {!ov ? <div className="empty">Loading…</div> : (
        <div className="led-pad">
          <div className="led-tiles">
            <Tile label="Money out" value={kr(ov.spent, 0)} sub={periodName} />
            {isMonth ? (
              <Tile label="Average month" value={base ? kr(base.perMonth, 0) : '–'}
                    sub={base ? `${base.months} months before`
                      + (vsBase != null ? ` · this month ${vsBase >= 0 ? '+' : ''}${vsBase}%` : '')
                      : 'no earlier months'} />
            ) : (
              <Tile label="Per month" value={kr(ov.perMonth, 0)} sub={`${ov.months.length} months`} />
            )}
            <Tile label="Income" value={kr(ov.income, 0)}
                  sub={ov.otherIn > 0 ? `+ ${kr(ov.otherIn, 0)} other money in` : 'category Income'} />
            <Tile label="Own transfers" value={`${kr(ov.transfersOut, 0)} out`}
                  sub={`${kr(ov.transfersIn, 0)} in · not counted`} />
          </div>
          {ov.transfersIn > 0 && ov.income < ov.transfersIn / 4 && (
            <p className="led-hint">
              {kr(ov.transfersIn, 0)} came in as transfers and counts as neither income nor
              spending. If your salary is among them (a monthly "OVERFØRSEL", say), set that
              merchant to <b>Income</b> on the Merchants page.
            </p>
          )}

          <div className="led-h3-row">
            <h3 className="led-h3">{isMonth ? `Money out per day - ${longMonth(period.month)}` : 'Money out per month'}</h3>
            <button className="ghost-btn sm" onClick={() => onOpenTx({ frm: range.frm, to: range.to, direction: 'out' })}>
              Transactions of {isMonth ? longMonth(period.month) : 'this period'} →
            </button>
          </div>
          {isMonth && ov.days ? (
            <Bars aria="Money out per day" hint="Click to see the day's transactions"
                  bars={ov.days.map((d) => ({
                    key: d.date, label: String(Number(d.date.slice(8, 10))), value: d.spent,
                    tip: <><b>{dayName(d.date)}</b> · {kr(d.spent, 0)} out</>,
                  }))}
                  onPick={(k) => onOpenTx({ frm: k, to: k })} />
          ) : (
            <Bars aria="Money out per month" hint="Click to open the month"
                  bars={ov.months.map((m) => ({
                    key: m.month, label: monthLabel(m.month), value: m.spent,
                    tip: <MonthTip m={m} categories={summary.categories} />,
                  }))}
                  onPick={(k) => set({ mode: 'month', month: k })} />
          )}

          <div className="led-cols">
            <section>
              <h3 className="led-h3">By category</h3>
              <table className="led-cats">
                <thead>
                  <tr><th>Category</th><th /><th className="num">Spent</th><th className="num">Share</th>
                    {isMonth && base && <><th className="num" title={`Average month, ${base.from} – ${base.to}`}>Avg month</th>
                      <th className="num">vs avg</th></>}</tr>
                </thead>
                <tbody>
                  {ov.categories.map((c) => {
                    const avg = base?.categories[c.key];
                    const diff = avg != null ? c.spent - avg : null;
                    return (
                      <tr key={c.key} onClick={() => onOpenTx({ category: c.key, frm: range.frm, to: range.to })}
                          title={`${c.count} transactions - click to see them`}>
                        <td className="led-cat-name">{c.key ? c.label : <i>Not categorised</i>}</td>
                        <td className="led-cat-bar"><span style={{ width: `${(Math.max(0, c.spent) / maxCat) * 100}%` }} /></td>
                        <td className="num">{kr(c.spent, 0)}</td>
                        <td className="num dim">{spentPos > 0 ? `${Math.round((c.spent / spentPos) * 100)}%` : ''}</td>
                        {isMonth && base && <>
                          <td className="num dim">{avg != null ? kr(avg, 0) : '–'}</td>
                          <td className={`num ${diff != null && diff > 0 ? 'led-more' : 'dim'}`}>
                            {diff != null ? `${diff >= 0 ? '+' : '−'}${kr(Math.abs(diff), 0)}` : 'new'}
                          </td>
                        </>}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </section>
            <section>
              <h3 className="led-h3" data-help="ledger.recurring">Recurring payments</h3>
              {ov.recurring.length === 0 ? <p className="dim led-small">None found in the last 6 months of data.</p> : (
                <table className="fma-table led-table">
                  <thead><tr><th>Merchant</th><th className="num">Typical / month</th>
                    <th className="num">Per year</th><th>Last</th></tr></thead>
                  <tbody>
                    {ov.recurring.map((r) => (
                      <tr key={r.key} onClick={() => onOpenTx({ merchant: r.key, merchantName: r.name })}
                          title={`${catLabel(summary.categories, r.category)} · paid in ${r.months} of the last 6 months`}>
                        <td>{r.name}</td>
                        <td className="num">{kr(r.typical)}</td>
                        <td className="num">{kr(r.yearly, 0)}</td>
                        <td className="dim">{r.last}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          </div>

          <div className="led-h3-row">
            <h3 className="led-h3" data-help="ledger.top">Top merchants</h3>
            <label className="led-model">
              <span>Show</span>
              <select value={top} onChange={(e) => setTop(Number(e.target.value))}>
                {TOP_CHOICES.map((n) => <option key={n} value={n}>top {n}</option>)}
              </select>
            </label>
          </div>
          <table className="fma-table led-table led-top">
            <thead><tr><th className="num">#</th><th>Merchant</th><th>Category</th><th className="num">Times</th>
              <th className="num">Spent</th><th className="num">Share</th><th className="num">Average</th><th>Last</th></tr></thead>
            <tbody>
              {ov.topMerchants.map((m, i) => (
                <tr key={m.key} onClick={() => onOpenTx({ merchant: m.key, merchantName: m.name, frm: range.frm, to: range.to })}>
                  <td className="num dim">{i + 1}</td>
                  <td>{m.name}</td>
                  <td className="dim">{catLabel(summary.categories, m.category)}</td>
                  <td className="num">{m.count}</td>
                  <td className="num">{kr(m.spent, 0)}</td>
                  <td className="num dim">{spentPos > 0 ? `${((m.spent / spentPos) * 100).toFixed(1)}%` : ''}</td>
                  <td className="num dim">{m.count ? kr(m.spent / m.count, 0) : ''}</td>
                  <td className="dim">{m.last}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {ov.topMerchants.length >= top && (
            <p className="dim led-small">Showing the top {top}. Pick a larger number above, or see every
              merchant on the Merchants page.</p>
          )}
        </div>
      )}
    </div>
  );
}

function dayName(d: string): string {
  const dt = new Date(d + 'T12:00:00');
  const wd = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][dt.getDay()];
  return `${wd} ${dt.getDate()} ${MONTH_NAMES[dt.getMonth()].slice(0, 3)}`;
}

function MonthTip({ m, categories }: { m: LedgerOverview['months'][number]; categories: LedgerCategory[] }) {
  const cats = Object.entries(m.byCategory).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).slice(0, 4);
  return (
    <>
      <b>{monthLabel(m.month)}</b> · {kr(m.spent, 0)} out{m.income ? ` · ${kr(m.income, 0)} income` : ''}
      {cats.map(([k, v]) => <div key={k} className="dim">{catLabel(categories, k)}: {kr(v, 0)}</div>)}
    </>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="led-tile">
      <div className="led-tile-label">{label}</div>
      <div className="led-tile-value">{value}</div>
      {sub && <div className="led-tile-sub">{sub}</div>}
    </div>
  );
}

interface BarDatum { key: string; label: string; value: number; tip: ReactNode }

/** One series, one hue, a tooltip per bar - months or days. */
function Bars({ bars, onPick, hint, aria }: {
  bars: BarDatum[]; onPick: (key: string) => void; hint: string; aria: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  // Drawn at the box's real pixel width: a stretched viewBox stretched the
  // axis text with it.
  const [width, setWidth] = useState(800);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const measure = () => setWidth(Math.max(260, el.clientWidth - 16));
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [bars.length]);
  if (bars.length === 0 || bars.every((b) => b.value <= 0)) {
    return <p className="dim led-small">No spending in this period.</p>;
  }
  const H = 180, padL = 44, padB = 22, padT = 8;
  const n = bars.length;
  const W = width;
  const max = Math.max(...bars.map((b) => b.value), 1);
  const step = niceStep(max / 4);
  const topV = Math.ceil(max / step) * step;
  const bw = (W - padL) / n;
  const y = (v: number) => padT + (H - padT - padB) * (1 - Math.max(0, v) / topV);
  const ticks = Array.from({ length: Math.round(topV / step) + 1 }, (_, i) => i * step);
  const labelW = Math.max(...bars.map((b) => b.label.length)) * 7 + 10;
  const labelEvery = Math.max(1, Math.ceil(labelW / bw));
  const h = hover != null ? bars[hover] : null;
  return (
    <div className="led-chart" ref={wrap} onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={aria}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W} y1={y(t)} y2={y(t)} className="led-grid" />
            <text x={padL - 6} y={y(t) + 4} className="led-axis" textAnchor="end">
              {t >= 1000 ? `${Math.round(t / 1000)}k` : t}
            </text>
          </g>
        ))}
        {bars.map((b, i) => {
          const x = padL + i * bw + 1;
          const w = Math.max(2, bw - 2);
          const yy = y(b.value);
          const hgt = Math.max(0, H - padB - yy);
          return (
            <g key={b.key} onMouseEnter={() => setHover(i)} onClick={() => onPick(b.key)} className="led-bar-g">
              <rect x={padL + i * bw} y={padT} width={bw} height={H - padT - padB} fill="transparent" />
              <path className={`led-bar${hover === i ? ' on' : ''}`}
                    d={roundTop(x, yy, w, hgt, Math.min(4, w / 2))} />
              {i % labelEvery === 0 && (
                <text x={x + w / 2} y={H - 6} className="led-axis" textAnchor="middle">{b.label}</text>
              )}
            </g>
          );
        })}
      </svg>
      {h && (
        <div className="led-tip" style={{
          left: `${Math.min(Math.max(8 + padL + (hover! + 0.5) * bw, 110), W - 110)}px` }}>
          {h.tip}
          <div className="dim led-tip-hint">{hint}</div>
        </div>
      )}
    </div>
  );
}

/** "2026-02" -> "2026-02-28". */
function monthEnd(m: string): string {
  const [y, mm] = m.split('-').map(Number);
  const d = new Date(Date.UTC(y, mm, 0));
  return d.toISOString().slice(0, 10);
}

function niceStep(raw: number): number {
  const p = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1))));
  for (const m of [1, 2, 2.5, 5, 10]) if (raw <= m * p) return m * p;
  return 10 * p;
}

function roundTop(x: number, y: number, w: number, h: number, r: number): string {
  if (h <= 0) return '';
  r = Math.min(r, h);
  return `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + w - r},${y} `
    + `Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h} Z`;
}

// ---- ask -----------------------------------------------------------------------------------

const EXAMPLES = [
  'How much have I spent at Netto this year?',
  'Groceries per month in 2025',
  'My 5 most expensive purchases this year',
  'Hvad bruger jeg flest penge på det sidste år?',
];

function AskTab({ summary, onModel }: { summary: LedgerSummary; onModel: () => void }) {
  const [models, setModels] = useState<string[]>([]);
  // FamilyLog: '' = the chat model from Settings; anything else is this
  // person's own choice for Økonomi (questions and categorising).
  const [model, setModel] = useState(summary.settings.override ?? summary.settings.model);
  const fromSettings = summary.settings.chatRole ?? '';
  const [question, setQuestion] = useState('');
  const [ask, setAsk] = useState<LedgerAsk | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { void api.listOllamaModels().then(setModels).catch(() => setModels([])); }, []);
  useEffect(() => { ledgerApi.askState().then(setAsk).catch(() => {}); }, []);
  const busy = ask?.state === 'queued' || ask?.state === 'working';
  useEffect(() => {
    if (!busy) return;
    const t = window.setInterval(() => { ledgerApi.askState().then(setAsk).catch(() => {}); }, 500);
    return () => window.clearInterval(t);
  }, [busy]);

  async function go(q = question) {
    if (!q.trim() || busy) return;
    setError(null);
    try {
      setAsk(await ledgerApi.ask(q.trim(), model || undefined));
      setQuestion('');
    } catch (e) { setError((e as Error).message); }
  }

  const res = ask?.result;
  return (
    <div className="fma-main fma-scroll">
      <div className="led-pad led-ask">
        <div className="led-ask-box" data-help="ledger.ask">
          <textarea value={question} rows={2} placeholder={ask?.state === 'done'
            ? 'Ask another question - or a follow-up ("and in 2024?", "per month?")'
            : 'Ask about your transactions…'}
                    onChange={(e) => setQuestion(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void go(); } }} />
          <div className="led-ask-row">
            <label className="led-model" data-help="ledger.model">
              <span>Model</span>
              <select value={model} onChange={async (e) => {
                setModel(e.target.value);
                await ledgerApi.setModel(e.target.value).catch(() => {});
                onModel();
              }}>
                {summary.settings.override !== undefined && (
                  <option value="">{fromSettings
                    ? `Settings: ${fromSettings}` : 'Settings (no chat model set)'}</option>)}
                {model && !models.includes(model) && <option value={model}>{model}</option>}
                {models.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </label>
            <span className="appbar-spacer" />
            {busy
              ? <button className="ghost-btn" onClick={async () => setAsk(await ledgerApi.askStop())}>Stop</button>
              : <button className="primary-btn" disabled={!question.trim()} onClick={() => void go()}>Ask</button>}
          </div>
          {!ask || ask.state === 'none' ? (
            <div className="led-examples">
              {EXAMPLES.map((q) => <button key={q} className="led-chip" onClick={() => void go(q)}>{q}</button>)}
            </div>
          ) : null}
        </div>
        {error && <p className="fma-error">{error}</p>}

        {ask && ask.state !== 'none' && (
          <div className="led-answer">
            <div className="led-q">
              <span className="led-q-text">{ask.question}</span>
              {ask.state === 'done' && <a className="ghost-btn sm" href={ledgerApi.askExportUrl}
                                         data-help="ledger.export" title="Download as Markdown">⬇ .md</a>}
            </div>
            {ask.previous && <div className="dim led-small">Follow-up to: {ask.previous}</div>}
            {ask.state === 'queued' && <div className="dim led-small">Waiting for the card{ask.ahead ? ` - ${ask.ahead} job${ask.ahead === 1 ? '' : 's'} ahead` : ''}…</div>}
            {ask.steps && <div className="rag-steps"><StepTree payload={ask.steps} streaming={busy} /></div>}
            {ask.text ? <div className="led-md"><Markdown text={ask.text} streaming={busy} /></div>
              : busy ? <div className="dim led-small"><span className="led-spin" /> {ask.step}</div> : null}
            {ask.error && <p className="fma-error">{ask.error}</p>}
            {ask.state === 'stopped' && <p className="dim led-small">Stopped.</p>}
            {ask.counted && (
              <p className="led-counted" data-help="ledger.counted">
                <b>Counted by the app:</b> {ask.counted}
                {res && <> - <b>{res.count.toLocaleString('da-DK')}</b> transactions, <b>{kr(res.total)}</b></>}
              </p>
            )}
            {res && res.notes.map((n) => <p key={n} className="led-hint">{n}</p>)}
            {res && res.groups.length > 0 && (
              <table className="fma-table led-table led-groups">
                <thead><tr><th>Group</th><th className="num">Total</th><th className="num">Count</th><th className="num">Average</th></tr></thead>
                <tbody>
                  {res.groups.map((g) => (
                    <tr key={g.group}><td>{g.group}</td><td className="num">{kr(g.total)}</td>
                      <td className="num">{g.count}</td><td className="num">{kr(g.average)}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
            {res && res.rows.length > 0 && (
              <>
                <div className="dim led-small">
                  {res.rows.length < res.count
                    ? `The ${res.rows.length} ${ask.spec?.order === 'newest' ? 'newest' : 'largest'} of ${res.count} matching transactions`
                    : `All ${res.count} matching transactions`}
                </div>
                <TxTable rows={res.rows} categories={summary.categories} />
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function TxTable({ rows, categories, onCategory }: {
  rows: LedgerTx[]; categories: LedgerCategory[];
  onCategory?: (row: LedgerTx, cat: string) => void;
}) {
  return (
    <div className="fma-table-wrap led-tx-wrap">
      <table className="fma-table led-table led-tx">
        <thead><tr><th>Date</th><th>Merchant</th><th>Category</th><th>Paid by</th>
          <th className="num">Amount</th><th className="led-text">Bank text</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.date}</td>
              <td title={r.merchant}>{r.merchant}</td>
              <td>
                {onCategory ? (
                  <select className="led-cat-select" value={r.category}
                          title="The merchant's category - changes every row of this merchant"
                          onChange={(e) => onCategory(r, e.target.value)}>
                    {!r.category && <option value="">Not categorised</option>}
                    {categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                  </select>
                ) : <span className="dim">{catLabel(categories, r.category)}</span>}
              </td>
              <td className="dim">{KIND_LABEL[r.kind] ?? r.kind}</td>
              <td className={`num${r.amount > 0 ? ' led-in' : ''}`}>
                {kr(r.amount)}
                {r.foreignCurrency && r.foreignAmount != null && (
                  <div className="dim led-fx">{r.foreignCurrency} {r.foreignAmount.toLocaleString('da-DK', { minimumFractionDigits: 2 })}</div>
                )}
              </td>
              <td className="dim led-text" title={r.text}>{r.text}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---- transactions ---------------------------------------------------------------------------

function TransactionsTab({ summary, filter, onChanged }: {
  summary: LedgerSummary; filter: TxFilter | null; onChanged: () => void;
}) {
  const [q, setQ] = useState(filter?.q ?? '');
  const [category, setCategory] = useState(filter?.category ?? '*');
  const [merchant, setMerchant] = useState<{ key: string; name: string } | null>(
    filter?.merchant ? { key: filter.merchant, name: filter.merchantName ?? filter.merchant } : null);
  const [frm, setFrm] = useState(filter?.frm ?? '');
  const [to, setTo] = useState(filter?.to ?? '');
  const [direction, setDirection] = useState(filter?.direction ?? '');
  const [order, setOrder] = useState('newest');
  const [account, setAccount] = useState('');
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ total: number; sum: number; rows: LedgerTx[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const PAGE = 100;

  useEffect(() => {
    if (!filter) return;
    setQ(filter.q ?? ''); setCategory(filter.category ?? '*'); setFrm(filter.frm ?? '');
    setTo(filter.to ?? ''); setDirection(filter.direction ?? '');
    setMerchant(filter.merchant ? { key: filter.merchant, name: filter.merchantName ?? filter.merchant } : null);
    setOffset(0);
  }, [filter]);

  const load = useCallback(() => {
    ledgerApi.transactions({ q, category, merchant: merchant?.key, frm, to: to, account, direction,
                             order, offset, limit: PAGE })
      .then((d) => { setData(d); setError(null); }).catch((e) => setError(e.message));
  }, [q, category, merchant, frm, to, account, direction, order, offset]);
  useEffect(() => {
    const t = window.setTimeout(load, q ? 250 : 0);
    return () => window.clearTimeout(t);
  }, [load, q]);

  return (
    <div className="fma-main">
      <div className="fma-toolbar led-toolbar" data-help="ledger.transactions">
        <input value={q} placeholder="Search text or merchant…" onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
        <select value={category} onChange={(e) => { setCategory(e.target.value); setOffset(0); }}>
          <option value="*">All categories</option>
          <option value="">Not categorised</option>
          {summary.categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
        <select value={direction} onChange={(e) => { setDirection(e.target.value); setOffset(0); }}>
          <option value="">In and out</option><option value="out">Money out</option><option value="in">Money in</option>
        </select>
        <input type="date" value={frm} onChange={(e) => { setFrm(e.target.value); setOffset(0); }} title="From" />
        <input type="date" value={to} onChange={(e) => { setTo(e.target.value); setOffset(0); }} title="To" />
        {summary.accounts.length > 1 && (
          <select value={account} onChange={(e) => { setAccount(e.target.value); setOffset(0); }}>
            <option value="">All accounts</option>
            {summary.accounts.map((a) => <option key={a.account} value={a.account}>{a.account}</option>)}
          </select>
        )}
        <select value={order} onChange={(e) => { setOrder(e.target.value); setOffset(0); }}>
          <option value="newest">Newest first</option><option value="oldest">Oldest first</option>
          <option value="largest">Largest out first</option><option value="income">Largest in first</option>
        </select>
      </div>
      {merchant && (
        <div className="led-filter-chip">
          Merchant: <b>{merchant.name}</b>
          <button className="ghost-btn sm" onClick={() => { setMerchant(null); setOffset(0); }}>× clear</button>
        </div>
      )}
      {error && <p className="fma-error">{error}</p>}
      {data && (
        <div className="led-sum">
          <b>{data.total.toLocaleString('da-DK')}</b> transactions · sum <b>{kr(data.sum)}</b>
          {data.total > PAGE && (
            <span className="led-pager">
              <button className="ghost-btn sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>‹</button>
              {offset + 1}–{Math.min(offset + PAGE, data.total)}
              <button className="ghost-btn sm" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>›</button>
            </span>
          )}
        </div>
      )}
      {data && <TxTable rows={data.rows} categories={summary.categories} onCategory={async (r, c) => {
        await ledgerApi.setMerchant(r.merchantKey, { category: c });
        load();
        onChanged();
      }} />}
    </div>
  );
}

// ---- merchants -------------------------------------------------------------------------------

const SOURCE_LABEL: Record<string, string> = { rule: 'rule', model: 'model', user: 'you', none: '' };

function MerchantsTab({ summary, onChanged, onOpenTx }: {
  summary: LedgerSummary; onChanged: () => void; onOpenTx: (f: TxFilter) => void;
}) {
  const [q, setQ] = useState('');
  const [category, setCategory] = useState(summary.uncategorised > 0 ? '' : '*');
  const [list, setList] = useState<LedgerMerchant[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    ledgerApi.merchants(q, category).then((l) => { setList(l); setError(null); })
      .catch((e) => setError(e.message));
  }, [q, category]);
  useEffect(() => {
    const t = window.setTimeout(load, q ? 250 : 0);
    return () => window.clearTimeout(t);
  }, [load, q, summary.uncategorised]);

  async function change(m: LedgerMerchant, c: { category?: string; name?: string }) {
    try {
      await ledgerApi.setMerchant(m.key, c);
      load();
      onChanged();
    } catch (e) { setError((e as Error).message); }
  }

  return (
    <div className="fma-main">
      <div className="fma-toolbar" data-help="ledger.merchants">
        <input value={q} placeholder="Search merchants…" onChange={(e) => setQ(e.target.value)} />
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="*">All categories</option>
          <option value="">Not categorised ({summary.uncategorised})</option>
          {summary.categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
      </div>
      <p className="fma-note led-pad-x">
        A category belongs to the merchant, so changing it moves all its transactions. Your
        choice is never overwritten - not by a new import, not by the model.
        <b> Own transfers</b> count as neither spending nor income.
      </p>
      {error && <p className="fma-error">{error}</p>}
      <div className="fma-table-wrap">
        <table className="fma-table led-table">
          <thead><tr><th>Merchant</th><th>Category</th><th>Set by</th><th className="num">Times</th>
            <th className="num">Total</th><th>Last</th><th className="led-text">Example bank text</th></tr></thead>
          <tbody>
            {list.map((m) => (
              <tr key={m.key}>
                <td>
                  {editing === m.key ? (
                    <input className="fma-inline" autoFocus value={name}
                           onChange={(e) => setName(e.target.value)}
                           onKeyDown={(e) => {
                             if (e.key === 'Enter') { setEditing(null); void change(m, { name }); }
                             if (e.key === 'Escape') setEditing(null);
                           }}
                           onBlur={() => setEditing(null)} />
                  ) : (
                    <span className="led-mname" title="Click to rename"
                          onClick={() => { setEditing(m.key); setName(m.name); }}>{m.name}</span>
                  )}
                </td>
                <td>
                  <select className="led-cat-select" value={m.category}
                          onChange={(e) => void change(m, { category: e.target.value })}>
                    {!m.category && <option value="">Not categorised</option>}
                    {summary.categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                  </select>
                </td>
                <td className="dim">{SOURCE_LABEL[m.source] ?? m.source}</td>
                <td className="num"><a className="led-link" onClick={() => onOpenTx({ merchant: m.key, merchantName: m.name })}>{m.count}</a></td>
                <td className={`num${m.total > 0 ? ' led-in' : ''}`}>{kr(m.total, 0)}</td>
                <td className="dim">{m.last}</td>
                <td className="dim led-text" title={m.sample}>{m.sample}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.length === 0 && <p className="fp-empty led-pad-x">No merchants match.</p>}
      </div>
    </div>
  );
}

// ---- import ------------------------------------------------------------------------------------

function ImportTab({ summary, onImported, onCleared }: {
  summary: LedgerSummary; onImported: (r: LedgerImportResult) => void; onCleared: () => void;
}) {
  const [account, setAccount] = useState(summary.imports[0]?.account ?? 'Lønkonto');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<LedgerImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const knownAccounts = useMemo(() => summary.accounts.map((a) => a.account), [summary.accounts]);

  async function upload(file: File) {
    setBusy(true); setError(null); setResult(null);
    try {
      const r = await ledgerApi.importFile(file, account);
      setResult(r);
      onImported(r);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); if (fileRef.current) fileRef.current.value = ''; }
  }

  return (
    <div className="fma-main fma-scroll">
      <div className="led-pad led-import" data-help="ledger.import">
        <label className="fma-row led-account">
          Account
          <input value={account} list="led-accounts" onChange={(e) => setAccount(e.target.value)}
                 placeholder="Lønkonto, MasterCard…" />
          <datalist id="led-accounts">{knownAccounts.map((a) => <option key={a} value={a} />)}</datalist>
        </label>
        <div className={`led-drop${drag ? ' on' : ''}`}
             onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
             onDragLeave={() => setDrag(false)}
             onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) void upload(f); }}
             onClick={() => fileRef.current?.click()}>
          {busy ? <><span className="led-spin" /> Reading the file…</>
            : <>Drop the bank's <b>CSV</b> or <b>Excel</b> export here, or click to choose it</>}
          <input ref={fileRef} type="file" accept=".csv,.txt,.tsv,.xlsx,.xlsm" hidden
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); }} />
        </div>
        {error && <p className="fma-error">{error}</p>}
        {result && (
          <p className="fma-ok">
            {result.rowsInFile.toLocaleString('da-DK')} rows read ({result.firstDate} – {result.lastDate}):{' '}
            <b>{result.added.toLocaleString('da-DK')} new</b>, {result.alreadyThere.toLocaleString('da-DK')} already in the ledger
            {result.skipped ? `, ${result.skipped} unreadable rows skipped` : ''}.
            {result.newUncategorised > 0 && ` ${result.newUncategorised} new merchants no rule knows`
              + (result.categorise ? ' - the model is placing them now.' : '.')}
          </p>
        )}
        <ul className="fma-note led-notes">
          <li>Import again whenever you like: overlapping rows are recognised (date, text, amount -
              and two identical purchases on the same day stay two).</li>
          <li>Give each account its own name. If you import a credit card's own statement too, set
              the bank's monthly "Forbrug på MasterCard" line to <b>Own transfers</b> on the
              Merchants page, or the card's spending is counted twice.</li>
          <li>The rows stay on this server, in the app's own database. Questions are read by the
              Ollama model chosen on the Ask page.</li>
        </ul>

        {summary.imports.length > 0 && (
          <>
            <h3 className="led-h3">Imports</h3>
            <table className="fma-table led-table fma-import">
              <thead><tr><th>When</th><th>Account</th><th>File</th><th>Period</th>
                <th className="num">Rows</th><th className="num">New</th><th /></tr></thead>
              <tbody>
                {summary.imports.map((i) => (
                  <tr key={i.id}>
                    <td className="dim">{i.importedAt.slice(0, 16).replace('T', ' ')}</td>
                    <td>{i.account}</td>
                    <td>{i.filename}</td>
                    <td className="dim">{i.firstDate} – {i.lastDate}</td>
                    <td className="num">{i.rowsInFile}</td>
                    <td className="num">{i.added}</td>
                    <td>
                      <button className="ghost-btn sm" title="Remove the rows this import added"
                              onClick={async () => {
                                if (!confirm(`Remove the ${i.added} rows imported from ${i.filename}?`)) return;
                                await ledgerApi.deleteImport(i.id); onCleared();
                              }}>Remove</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="fma-actions fma-gap">
              <button className="ghost-btn sm fma-bad" onClick={async () => {
                if (!confirm('Delete every transaction, merchant and category choice in Økonomi?')) return;
                await ledgerApi.clear(); setResult(null); onCleared();
              }}>Delete everything</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
