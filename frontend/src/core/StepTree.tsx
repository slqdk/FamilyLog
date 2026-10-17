import { useEffect, useState } from 'react';
import type { StepDto, StepsPayload } from './types';

/** Steps: where an answer's seconds and tokens went (backend telemetry).
    A collapsed one-line summary; open, a tree with a dot per row (done,
    running, failed), tokens and time in right-hand columns. Running rows
    tick live, using the server's clock offset. */
export function StepTree({ payload, streaming = false }: { payload: StepsPayload; streaming?: boolean }) {
  const [open, setOpen] = useState(false);
  const [, tick] = useState(0);
  const live = streaming && payload.summary.running;
  useEffect(() => {
    if (!live) return;
    const t = window.setInterval(() => tick((n) => n + 1), 250);
    return () => window.clearInterval(t);
  }, [live]);

  const offset = payload.serverNow - Date.now() / 1000;
  const nowS = Date.now() / 1000 + offset - payload.startedAt;
  const sm = payload.summary;
  const total = live ? Math.max(sm.totalS, nowS) : sm.totalS;
  const bits = [`${total.toFixed(1)} s`];
  if (sm.firstTokenS != null) bits.push(`first token ${sm.firstTokenS.toFixed(1)} s`);
  if (sm.tokensOut) bits.push(`${num(sm.tokensOut)} tokens out`);
  if (sm.tps) bits.push(`${sm.tps} t/s`);
  if (sm.model) bits.push(sm.model);

  const children = new Map<number | null, StepDto[]>();
  for (const s of payload.steps) {
    const list = children.get(s.parent) ?? [];
    list.push(s);
    children.set(s.parent, list);
  }
  const rows: { s: StepDto; prefix: string }[] = [];
  const walk = (pid: number | null, prefix: string) => {
    const kids = children.get(pid) ?? [];
    kids.forEach((s, i) => {
      const last = i === kids.length - 1;
      rows.push({ s, prefix: prefix + (pid === null ? '' : last ? '└ ' : '├ ') });
      walk(s.id, pid === null ? '' : prefix + (last ? '   ' : '│  '));
    });
  };
  walk(null, '');

  return (
    <div className={`steps${live ? ' live' : ''}`}>
      <button className="steps-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="steps-caret">{open ? '▾' : '▸'}</span>
        <span className="steps-title">Steps</span>
        <span className="steps-sum">{bits.join(' · ')}</span>
      </button>
      {open && (
        <div className="steps-body">
          {rows.map(({ s, prefix }) => {
            const end = s.end ?? (live ? nowS : s.start);
            return (
              <div key={s.id} className={`steps-row s-${s.state} k-${s.kind}${s.flag ? ` f-${s.flag}` : ''}`}>
                <span className="steps-label">
                  <span className="steps-prefix">{prefix}</span>
                  <span className="steps-dot" />
                  {s.label}
                  {s.detail && <span className="steps-detail">{s.detail}</span>}
                </span>
                <span className="steps-tok">{s.tokens != null ? `${s.approx ? '≈' : ''}${num(s.tokens)} tok` : ''}</span>
                <span className="steps-time">{s.kind === 'info' ? '' : `${Math.max(0, end - s.start).toFixed(1)} s`}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function num(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}
