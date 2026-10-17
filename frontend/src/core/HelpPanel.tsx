import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api';
import type { HelpDto, HelpEntryDto } from './types';
import { Markdown } from './Markdown';

/**
 * The Help drawer (from SLQ 2.42.0): a fixed panel on the right, on every page.
 * Opened by Alt+click on any control (see help.ts) at that control's entry,
 * or by the ? in the top bar at the index. One search box filters title,
 * location and body; the index is grouped by where a control lives, in
 * the registry's order. An entry shows its `since` / `changed` versions so
 * stale help is visible, and the header shows the app version.
 */
export function HelpPanel({ requestedId, requestedLabel, requestKey, onClose }: {
  requestedId: string | null;
  requestedLabel?: string;
  /** bumps on every request so the same id re-scrolls */
  requestKey: number;
  onClose: () => void;
}) {
  const [help, setHelp] = useState<HelpDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [openId, setOpenId] = useState<string | null>(requestedId);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.getHelp().then(setHelp).catch((e) =>
      setError(e instanceof Error ? e.message : 'Could not load the help.'));
  }, []);

  useEffect(() => {
    setOpenId(requestedId);
    setQuery('');
  }, [requestedId, requestKey]);

  // Scroll the opened entry into view and flash it.
  useEffect(() => {
    if (!openId || !help) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[data-help-id="${CSS.escape(openId)}"]`);
    if (!el) return;
    el.scrollIntoView({ block: 'start' });
    el.classList.add('flash');
    const t = window.setTimeout(() => el.classList.remove('flash'), 1200);
    return () => window.clearTimeout(t);
  }, [openId, help, requestKey]);

  const entries = help?.entries ?? [];
  const byId = useMemo(() => new Map(entries.map((e) => [e.id, e])), [entries]);
  const missing = requestedId !== null && help !== null && !byId.has(requestedId);

  const q = query.trim().toLowerCase();
  const shown = q
    ? entries.filter((e) => `${e.title} ${e.where} ${e.body} ${e.id}`.toLowerCase().includes(q))
    : entries;

  // Group by location, keeping the registry's order (sorted by where, title).
  const groups: { where: string; items: HelpEntryDto[] }[] = [];
  for (const e of shown) {
    const last = groups[groups.length - 1];
    if (last && last.where === e.where) last.items.push(e);
    else groups.push({ where: e.where || 'Elsewhere', items: [e] });
  }

  return (
    <aside className="help-drawer" role="complementary" aria-label="Help">
      <div className="help-head">
        <span className="help-title">Help</span>
        {help && <span className="help-version" title="The version this help describes">v{help.version}</span>}
        <button className="ghost-btn sm" onClick={onClose} title="Close (Esc)">×</button>
      </div>
      <p className="help-tip">Alt + click any control to open its entry here.</p>
      <input className="help-search" placeholder="Search the help…" value={query}
             onChange={(e) => setQuery(e.target.value)} autoFocus={requestedId === null} />
      {error && <p className="fp-empty">{error}</p>}
      {!help && !error && <p className="fp-empty">Loading…</p>}
      {missing && (
        <p className="help-missing">
          No help entry for this yet{requestedLabel ? ` (${requestedLabel})` : ''} - that is a gap
          in <code>docs/HELP.md</code>, please report it.
        </p>
      )}
      <div className="help-list" ref={listRef}>
        {help && shown.length === 0 && <p className="fp-empty">Nothing matches.</p>}
        {groups.map((g) => (
          <section key={g.where} className="help-group">
            <h4>{g.where}</h4>
            {g.items.map((e) => {
              const open = e.id === openId;
              return (
                <article key={e.id} data-help-id={e.id} className={`help-entry${open ? ' open' : ''}`}>
                  <button className="help-entry-head" onClick={() => setOpenId(open ? null : e.id)}>
                    <span className="help-entry-title">{e.title}</span>
                    {e.changed ? <span className="help-stamp" title="Last changed in">{e.changed}</span>
                      : e.since ? <span className="help-stamp" title="Since">{e.since}</span> : null}
                  </button>
                  {open && (
                    <div className="help-body">
                      <Markdown text={e.body} />
                      {(e.since || e.changed) && (
                        <p className="help-stamps">
                          {e.since && <span>since {e.since}</span>}
                          {e.changed && <span>changed {e.changed}</span>}
                        </p>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
          </section>
        ))}
      </div>
    </aside>
  );
}
