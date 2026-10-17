import { useCallback, useEffect, useMemo, useState } from 'react';
import { Markdown } from '../core/Markdown';
import { homeApi, type OkAsk, type OkMonth, type OkState, type OkTx } from './api';
import { Bar } from './Dagbog';
import { addMonths, kr, monthTitle, routeHash, shortDate } from './logic';

/** Økonomi on the phone (FamilyLog 0.3.0): one month at a time - what went
    out, where, compared with a usual month - and Alf to ask. Read only:
    importing and categories stay in the admin app. A family account the
    administrator gave access reads that account's Økonomi. */
export function OkonomiPage({ month }: { month: string | null }) {
  const [st, setSt] = useState<OkState | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { homeApi.okState().then(setSt).catch((e) => setError(e.message)); }, []);

  if (error) return <Shell><p className="fm-error">{error}</p></Shell>;
  if (!st) return <Shell><p className="fm-note">Henter…</p></Shell>;
  if (!st.access) {
    return <Shell><section className="fm-sheet hm-field"><p>Du har ikke adgang til Økonomi.</p>
      <p className="fm-dim">Administratoren kan give adgang under Indstillinger → Accounts.</p></section></Shell>;
  }
  if (st.count === 0) {
    return (
      <Shell>
        <section className="fm-sheet hm-field">
          <p>Der er ingen posteringer endnu.</p>
          {st.own && <a className="fm-link" href="/app/#ledger">Importér en bankudskrift i admin-appen</a>}
        </section>
      </Shell>
    );
  }
  const months = st.months;
  const m = month && months.includes(month) ? month : months[months.length - 1];
  return (
    <Shell>
      {!st.own && <p className="ok-whose">Du ser {st.owner}s økonomi · kun læsning</p>}
      <div className="hm-daynav">
        {m > months[0]
          ? <a className="hm-step" aria-label="Måneden før" href={routeHash({ name: 'okonomi', month: addMonths(m, -1) })}>‹</a>
          : <span className="hm-step hm-step-off" aria-hidden>‹</span>}
        <span className="hm-dayname">{monthTitle(m)}</span>
        {m < months[months.length - 1]
          ? <a className="hm-step" aria-label="Måneden efter" href={routeHash({ name: 'okonomi', month: addMonths(m, 1) })}>›</a>
          : <span className="hm-step hm-step-off" aria-hidden>›</span>}
      </div>
      <Month month={m} />
      <Ask initial={st.ask} model={st.model} />
      {st.own && (
        <p className="ok-foot">
          {st.uncategorised > 0 && <>{st.uncategorised} butikker mangler kategori. </>}
          <a href="/app/#ledger">Import og kategorier i admin-appen</a>
        </p>
      )}
    </Shell>
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

function Month({ month }: { month: string }) {
  const [d, setD] = useState<OkMonth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<{ category?: string; merchant?: string; label: string } | null>(null);
  useEffect(() => {
    setD(null); setOpen(null); setError(null);
    homeApi.okMonth(month).then(setD).catch((e) => setError(e.message));
  }, [month]);
  if (error) return <p className="fm-error">{error}</p>;
  if (!d) return <p className="fm-note">Henter…</p>;
  const base = d.baselinePerMonth;
  const diff = base ? (d.spent - base) / base : null;
  const top = Math.max(...d.categories.map((c) => Math.max(c.spent, c.usual ?? 0)), 1);
  return (
    <>
      <section className="fm-sheet ok-hero" aria-label="Måneden">
        <p className="ok-hero-label">Brugt</p>
        <p className="ok-hero-num">{kr(d.spent)}</p>
        <p className="ok-hero-sub">
          {d.income > 0 && <>Indtægter {kr(d.income)}</>}
          {d.income > 0 && diff != null && ' · '}
          {diff != null && (
            <span className={diff > 0.05 ? 'ok-up' : diff < -0.05 ? 'ok-down' : ''}>
              {Math.abs(diff) < 0.05 ? 'som en normal måned'
                : `${Math.round(Math.abs(diff) * 100)} % ${diff > 0 ? 'over' : 'under'} en normal måned`}
            </span>
          )}
        </p>
        {d.days && <DayBars days={d.days} />}
        {base != null && <p className="ok-note">Normal måned: snittet af de {d.baselineMonths} måneder før ({kr(base)}).</p>}
      </section>

      <section className="fm-sheet hm-field" aria-label="Kategorier">
        <h3 className="hm-field-label">Hvor gik pengene hen?</h3>
        {d.categories.length === 0 && <p className="fm-dim">Intet forbrug i måneden.</p>}
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
              {open?.category === c.key && <TxList month={month} filter={open} />}
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
                {open?.merchant === t.key && <TxList month={month} filter={open} />}
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
              <li key={r.name} className="ok-row ok-row-static">
                <span><span className="ok-row-name">{r.name}</span><small>{r.categoryName}</small></span>
                <span className="ok-right"><b>{kr(r.typical)}</b><small>{kr(r.yearly)} om året</small></span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
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

function TxList({ month, filter }: { month: string; filter: { category?: string; merchant?: string; label: string } }) {
  const [rows, setRows] = useState<OkTx[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    homeApi.okTx(month, filter).then((t) => { setRows(t.rows); setTotal(t.total); })
      .catch((e) => setError(e.message));
  }, [month, filter]);
  if (error) return <p className="fm-error">{error}</p>;
  if (!rows) return <p className="fm-note ok-tx-wait">Henter…</p>;
  return (
    <div className="ok-tx" aria-label={`Posteringer: ${filter.label}`}>
      {rows.map((r, i) => (
        <div key={i} className="ok-tx-row">
          <span className="ok-tx-date">{shortDate(r.date)}</span>
          <span className="ok-tx-text">{r.merchant}</span>
          <span className={r.amount < 0 ? '' : 'ok-in'}>{kr(r.amount, true)}</span>
        </div>
      ))}
      {total > rows.length && <p className="ok-note">… og {total - rows.length} mere</p>}
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
