import { useEffect, useState } from 'react';
import { dagbogAdmin, type DagbogAdminSettings } from './api';

/** Dagbog settings (FamilyLog 0.2.0): the activity tags everyone picks
    from, and which fields each person records. Entries themselves are not
    shown here - the highlight text and photo are their author's alone. */
export function DagbogAdmin() {
  const [s, setS] = useState<DagbogAdminSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    dagbogAdmin.settings().then(setS).catch((e) => setError((e as Error).message));
  }, []);

  async function save(body: Parameters<typeof dagbogAdmin.save>[0], done: string) {
    setError(null); setNote(null);
    try { setS(await dagbogAdmin.save(body)); setNote(done); }
    catch (e) { setError((e as Error).message); }
  }

  if (!s) return <div className="empty">{error ?? 'Loading…'}</div>;
  return (
    <div className="fma">
      <header className="fma-head">
        <span className="fma-title">Dagbog</span>
        <span className="fma-stats">Everyone rates their day on the front page. The family sees each other's days -
          the text and photo too, unless the author keeps that day to themselves.</span>
      </header>
      <div className="fma-main fma-scroll fma-pad dg-admin">
        <section className="settings-group" data-help="dagbog.members">
          <div className="settings-group-head"><h2>Fields per person</h2></div>
          <p className="settings-note">Which fields each person fills in. A field that is off is not asked and not stored.</p>
          <div className="dg-table-wrap">
            <table className="dg-table">
              <thead>
                <tr><th>Person</th>{s.fields.map((f) => <th key={f.key}>{f.label}</th>)}</tr>
              </thead>
              <tbody>
                {s.members.map((m) => (
                  <tr key={m.id}>
                    <th scope="row">{m.username} <span className="dim">{m.role}</span></th>
                    {s.fields.map((f) => {
                      const on = m.fields.includes(f.key);
                      return (
                        <td key={f.key}>
                          <input type="checkbox" checked={on} aria-label={`${m.username}: ${f.label}`}
                                 disabled={on && m.fields.length === 1}
                                 onChange={() => {
                                   const next = on ? m.fields.filter((x) => x !== f.key) : [...m.fields, f.key];
                                   void save({ members: { [m.id]: next } }, `${m.username}: saved.`);
                                 }} />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <ListEditor title="Food" help="dagbog.foods" saved={s.foods} button="Save food"
                    note="What people tick under Mad, one per line (homemade, fast food, cake, chips…)."
                    onSave={(list) => save({ foods: list }, 'Food saved.')} />
        <ListEditor title="Activities" help="dagbog.tags" saved={s.tags} button="Save activities"
                    note="What people tick under Aktiviteter, one per line."
                    onSave={(list) => save({ tags: list }, 'Activities saved.')} />
        {note && <p className="fma-ok">{note}</p>}
        {error && <p className="fma-error">{error}</p>}
      </div>
    </div>
  );
}

/** One list the family picks from. Removing an item keeps it on the days
    that already have it. */
function ListEditor({ title, help, saved, note, button, onSave }: {
  title: string; help: string; saved: string[]; note: string; button: string;
  onSave: (list: string[]) => void;
}) {
  const [text, setText] = useState(saved.join('\n'));
  useEffect(() => setText(saved.join('\n')), [saved]);
  const list = text.split('\n').map((t) => t.trim()).filter(Boolean);
  return (
    <section className="settings-group" data-help={help}>
      <div className="settings-group-head"><h2>{title}</h2></div>
      <p className="settings-note">{note} Removing one keeps it on the days that already have it.</p>
      <textarea rows={Math.max(6, list.length + 1)} value={text} aria-label={title}
                onChange={(e) => setText(e.target.value)} />
      <div className="settings-inline dg-actions">
        <button className="primary-btn" disabled={list.join('\n') === saved.join('\n')}
                onClick={() => onSave(list)}>{button}</button>
      </div>
    </section>
  );
}
