import { useEffect, useState } from 'react';
import { dagbogAdmin, type DagbogAdminSettings } from './api';

/** Dagbog settings (FamilyLog 0.2.0): the activity tags everyone picks
    from, and which fields each person records. Entries themselves are not
    shown here - the highlight text and photo are their author's alone. */
export function DagbogAdmin() {
  const [s, setS] = useState<DagbogAdminSettings | null>(null);
  const [tags, setTags] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    dagbogAdmin.settings().then((v) => { setS(v); setTags(v.tags.join('\n')); })
      .catch((e) => setError((e as Error).message));
  }, []);

  async function save(body: Parameters<typeof dagbogAdmin.save>[0], done: string) {
    setError(null); setNote(null);
    try {
      const v = await dagbogAdmin.save(body);
      setS(v); setTags(v.tags.join('\n')); setNote(done);
    } catch (e) { setError((e as Error).message); }
  }

  if (!s) return <div className="empty">{error ?? 'Loading…'}</div>;
  const tagList = tags.split('\n').map((t) => t.trim()).filter(Boolean);
  return (
    <div className="fma">
      <header className="fma-head">
        <span className="fma-title">Dagbog</span>
        <span className="fma-stats">Everyone rates their day on the front page. The family sees ratings and
          activities; the day's highlight text and photo are only ever shown to their author.</span>
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
        <section className="settings-group" data-help="dagbog.tags">
          <div className="settings-group-head"><h2>Activities</h2></div>
          <p className="settings-note">One per line. Everyone picks from this list; removing one keeps it on the
            days that already have it.</p>
          <textarea rows={Math.max(6, tagList.length + 1)} value={tags} onChange={(e) => setTags(e.target.value)} />
          <div className="settings-inline dg-actions">
            <button className="primary-btn" disabled={tagList.join('\n') === s.tags.join('\n')}
                    onClick={() => void save({ tags: tagList }, 'Activities saved.')}>Save activities</button>
          </div>
        </section>
        {note && <p className="fma-ok">{note}</p>}
        {error && <p className="fma-error">{error}</p>}
      </div>
    </div>
  );
}
