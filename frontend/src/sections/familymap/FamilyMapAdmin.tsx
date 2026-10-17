import { useCallback, useEffect, useState } from 'react';
import { fmAdmin } from './api';
import {
  photoUrl, type FmCategories, type FmImportState, type FmPlace, type FmReview,
  type FmSettings, type FmStats, type FmUser,
} from './phone/types';

export type FamilyMapTab = 'places' | 'reviews' | 'family' | 'import' | 'settings';

export const FAMILYMAP_TABS: [FamilyMapTab, string][] = [
  ['places', 'Places'], ['reviews', 'Reviews'], ['family', 'Family accounts'],
  ['import', 'Import from OSM'], ['settings', 'Settings'],
];

/** FamilyMap's admin section (2.43.0). The family writes on their own page
    at /fm/; this is where places are corrected, reviews and photos
    removed, and the family's accounts managed. */
export function FamilyMapAdmin({ tab }: { tab: FamilyMapTab }) {
  const [cats, setCats] = useState<FmCategories | null>(null);
  const [stats, setStats] = useState<FmStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refreshStats = useCallback(() => {
    fmAdmin.stats().then(setStats).catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    fmAdmin.categories().then(setCats).catch((e) => setError(e.message));
    refreshStats();
  }, [refreshStats]);

  return (
    <div className="fma">
      <header className="fma-head" data-help="familymap.header">
        <span className="fma-title">FamilyMap</span>
        {stats && (
          <span className="fma-stats">
            {stats.places} places ({stats.reviewedPlaces} reviewed), {stats.reviews} reviews,{' '}
            {stats.photos} photos
          </span>
        )}
        <a className="ghost-btn sm" href="/fm/" target="_blank" rel="noreferrer">Open family page</a>
      </header>
      {error && <p className="fma-error">{error}</p>}
      {!cats ? <div className="empty">Loading…</div>
        : tab === 'places' ? <PlacesTab cats={cats} onChanged={refreshStats} />
        : tab === 'reviews' ? <ReviewsTab cats={cats} onChanged={refreshStats} />
        : tab === 'import' ? <ImportTab cats={cats} onChanged={refreshStats} />
        : tab === 'settings' ? <SettingsTab stats={stats} onChanged={refreshStats} />
        : <FamilyTab />}
    </div>
  );
}

// ---- places ------------------------------------------------------------------------

function PlacesTab({ cats, onChanged }: { cats: FmCategories; onChanged: () => void }) {
  const [q, setQ] = useState('');
  const [category, setCategory] = useState('');
  const [reviewed, setReviewed] = useState('');
  const [places, setPlaces] = useState<FmPlace[]>([]);
  const [selected, setSelected] = useState<FmPlace | 'new' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    fmAdmin.places(q, category, reviewed)
      .then((p) => { setPlaces(p); setError(null); })
      .catch((e) => setError(e.message));
  }, [q, category, reviewed]);
  useEffect(() => {
    const t = window.setTimeout(load, q ? 250 : 0);
    return () => window.clearTimeout(t);
  }, [load, q]);

  return (
    <div className="fma-split">
      <section className="fma-main">
        <div className="fma-toolbar" data-help="familymap.places">
          <input value={q} placeholder="Search name or address…" onChange={(e) => setQ(e.target.value)} />
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>
            {Object.entries(cats).map(([k, c]) => <option key={k} value={k}>{c.label}</option>)}
          </select>
          <select value={reviewed} onChange={(e) => setReviewed(e.target.value)}>
            <option value="">Reviewed or not</option>
            <option value="yes">Reviewed by the family</option>
            <option value="no">Not reviewed</option>
          </select>
          <button className="primary-btn sm" onClick={() => setSelected('new')}>+ Place</button>
        </div>
        {error && <p className="fma-error">{error}</p>}
        <div className="fma-table-wrap">
          <table className="fma-table">
            <thead>
              <tr><th>Name</th><th>Category</th><th>Address</th><th className="num">Family</th>
                <th className="num">Reviews</th><th className="num">Web</th><th>Source</th></tr>
            </thead>
            <tbody>
              {places.map((p) => (
                <tr key={p.id} className={selected !== 'new' && selected?.id === p.id ? 'sel' : ''}
                    onClick={() => setSelected(p)}>
                  <td>{p.name}</td>
                  <td>{cats[p.category]?.label ?? p.category}</td>
                  <td className="dim">{p.address}</td>
                  <td className="num">{p.familyScore ?? ''}</td>
                  <td className="num">{p.reviewCount || ''}</td>
                  <td className="num">{p.webRating != null ? p.webRating.toFixed(1) : ''}</td>
                  <td className="dim" title={p.locked ? 'Corrected here - imports leave it alone' : undefined}>
                    {p.source}{p.locked ? ' (edited)' : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {places.length === 0 && !error && (
            <p className="fp-empty fma-pad">No places match. The family adds them from their page,
              or add one with + Place.</p>
          )}
        </div>
      </section>
      {selected && (
        <PlaceEditor key={selected === 'new' ? 'new' : selected.id} place={selected === 'new' ? null : selected}
                     cats={cats} onClose={() => setSelected(null)}
                     onSaved={(p) => { setSelected(p); load(); onChanged(); }}
                     onDeleted={() => { setSelected(null); load(); onChanged(); }} />
      )}
    </div>
  );
}

function PlaceEditor({ place, cats, onClose, onSaved, onDeleted }: {
  place: FmPlace | null; cats: FmCategories; onClose: () => void;
  onSaved: (p: FmPlace) => void; onDeleted: () => void;
}) {
  const [form, setForm] = useState({
    name: place?.name ?? '', category: place?.category ?? Object.keys(cats)[0],
    address: place?.address ?? '', lat: place?.lat?.toString() ?? '',
    lng: place?.lng?.toString() ?? '', website: place?.website ?? '', notes: place?.notes ?? '',
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      setForm((f) => ({ ...f, [k]: e.target.value }));

  async function save() {
    setBusy(true); setError(null);
    const body = { ...form, lat: form.lat.trim() === '' ? null : Number(form.lat),
                   lng: form.lng.trim() === '' ? null : Number(form.lng) };
    try {
      onSaved(place ? await fmAdmin.updatePlace(place.id, body)
                    : await fmAdmin.createPlace(body));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!place) return;
    const n = place.reviewCount;
    if (!confirm(`Delete "${place.name}"${n ? ` with its ${n} review(s) and their photos` : ''}?`)) return;
    try { await fmAdmin.deletePlace(place.id); onDeleted(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }

  return (
    <aside className="files-panel fma-editor" data-help="familymap.placeEdit">
      <div className="fma-editor-head">
        <strong>{place ? 'Edit place' : 'New place'}</strong>
        <button className="ghost-btn sm" onClick={onClose}>Close</button>
      </div>
      <label className="fma-row"><span>Name</span><input value={form.name} onChange={set('name')} /></label>
      <label className="fma-row"><span>Category</span>
        <select value={form.category} onChange={set('category')}>
          {Object.entries(cats).map(([k, c]) => <option key={k} value={k}>{c.label}</option>)}
        </select>
      </label>
      {place && place.reviewCount > 0 && form.category !== place.category && (
        <p className="fma-note">Its reviews keep their fields, but only the new category's
          fields are shown.</p>
      )}
      <label className="fma-row"><span>Address</span><input value={form.address} onChange={set('address')} /></label>
      <div className="fma-row2">
        <label className="fma-row"><span>Latitude</span><input value={form.lat} onChange={set('lat')} inputMode="decimal" /></label>
        <label className="fma-row"><span>Longitude</span><input value={form.lng} onChange={set('lng')} inputMode="decimal" /></label>
      </div>
      <label className="fma-row"><span>Website</span><input value={form.website} onChange={set('website')} /></label>
      <label className="fma-row"><span>Notes</span><textarea rows={3} value={form.notes} onChange={set('notes')} /></label>
      {place && (
        <p className="fma-note">
          Source: {place.source}{place.sourceId ? ` (${place.sourceId})` : ''}.
          {place.source === 'osm' && (place.locked
            ? ' Edited here, so imports no longer change it.'
            : ' Saving an edit stops imports from changing it.')}
          {Object.keys(place.extra ?? {}).length > 0 &&
            ` OSM details: ${Object.entries(place.extra).map(([k, v]) => `${k}=${v}`).join('; ')}.`}
        </p>
      )}
      {error && <p className="fma-error">{error}</p>}
      <div className="fma-actions">
        <button className="primary-btn sm" disabled={busy || !form.name.trim()} onClick={save}>
          {busy ? 'Saving…' : place ? 'Save' : 'Create'}
        </button>
        {place && <button className="ghost-btn sm danger" onClick={remove}>Delete place</button>}
      </div>
    </aside>
  );
}

// ---- reviews -----------------------------------------------------------------------

function ReviewsTab({ cats, onChanged }: { cats: FmCategories; onChanged: () => void }) {
  const [reviews, setReviews] = useState<FmReview[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    fmAdmin.reviews().then(setReviews).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  async function removeReview(r: FmReview) {
    if (!confirm(`Delete ${r.author}'s review of "${r.placeName}"${r.photos.length ? ` and its ${r.photos.length} photo(s)` : ''}?`)) return;
    try { await fmAdmin.deleteReview(r.id); load(); onChanged(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  async function removePhoto(id: number) {
    if (!confirm('Delete this photo?')) return;
    try { await fmAdmin.deletePhoto(id); load(); onChanged(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }

  return (
    <section className="fma-main fma-scroll" data-help="familymap.reviews">
      {error && <p className="fma-error">{error}</p>}
      {reviews?.length === 0 && <p className="fp-empty fma-pad">No reviews yet.</p>}
      {reviews?.map((r) => {
        const cat = cats[r.placeCategory ?? ''];
        const fields = (cat?.fields ?? []).filter((f) => r.fields[f.key] != null);
        return (
          <article key={r.id} className="fma-review">
            <div className="fma-review-head">
              <strong>{r.placeName}</strong>
              <span className="dim">{cat?.label}</span>
              <span className="fma-score">{r.overall}</span>
              <span className="dim">{r.author}, visited {r.visitedOn ?? '?'}{r.who ? `, with ${r.who}` : ''}</span>
              <span className="appbar-spacer" />
              <button className="ghost-btn sm danger" onClick={() => removeReview(r)}>Delete</button>
            </div>
            {fields.length > 0 && (
              <div className="fma-fields">
                {fields.map((f) => (
                  <span key={f.key}>{f.label}: <b>{f.kind === 'bool' ? (r.fields[f.key] ? 'ja' : 'nej') : String(r.fields[f.key])}</b></span>
                ))}
                {r.again != null && <span>Igen: <b>{r.again ? 'ja' : 'nej'}</b></span>}
              </div>
            )}
            {r.text && <p className="fma-text">{r.text}</p>}
            {r.photos.length > 0 && (
              <div className="fma-photos">
                {r.photos.map((p) => (
                  <span key={p.id} className="fma-photo"
                        title={p.description ?? (p.describeState === 'failed'
                          ? `Description failed: ${p.describeError ?? ''}`
                          : `Description: ${p.describeState ?? 'waiting'}`)}>
                    <a href={photoUrl(p.id)} target="_blank" rel="noreferrer">
                      <img src={photoUrl(p.id, true)} alt="" loading="lazy" />
                    </a>
                    <button title="Delete this photo" onClick={() => removePhoto(p.id)}>×</button>
                    <span className={`fma-desc-dot ${p.describeState ?? 'pending'}`} />
                  </span>
                ))}
              </div>
            )}
            {r.photos.some((p) => p.description) && (
              <ul className="fma-descs">
                {r.photos.filter((p) => p.description).map((p) => <li key={p.id}>{p.description}</li>)}
              </ul>
            )}
          </article>
        );
      })}
    </section>
  );
}

// ---- family accounts ------------------------------------------------------------------

function FamilyTab() {
  const [users, setUsers] = useState<FmUser[]>([]);
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [resetFor, setResetFor] = useState<number | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    fmAdmin.users().then(setUsers).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  /** True when it worked, so a form clears only then. */
  const run = async (fn: () => Promise<unknown>, done: string) => {
    setError(null); setNote(null);
    try { await fn(); setNote(done); load(); return true; }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); return false; }
  };

  return (
    <section className="fma-main fma-scroll fma-pad" data-help="familymap.family">
      <p className="fp-empty">
        Family accounts sign in on the family page only. Every other part of this app refuses
        them, and they do not count towards the app's account limit.
      </p>
      <ul className="user-list">
        {users.map((u) => (
          <li key={u.id}>
            <span className={`user-dot${u.online ? ' on' : ''}`} title={u.online ? 'Signed in' : 'Not signed in'} />
            <span className="user-name">{u.username}</span>
            <span className="user-role">family</span>
            {resetFor === u.id ? (
              <>
                <input type="password" className="fma-inline" placeholder="New password (10+)"
                       value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
                <button className="ghost-btn sm" disabled={newPassword.length < 10}
                        onClick={() => run(() => fmAdmin.setPassword(u.id, newPassword),
                          `${u.username}'s password changed; their phone signs in again.`)
                          .then((ok) => { if (ok) { setResetFor(null); setNewPassword(''); } })}>Set</button>
                <button className="ghost-btn sm" onClick={() => setResetFor(null)}>Cancel</button>
              </>
            ) : (
              <>
                <button className="ghost-btn sm" onClick={() => { setResetFor(u.id); setNewPassword(''); }}>Password</button>
                <button className="ghost-btn sm" disabled={!u.online}
                        onClick={() => run(() => fmAdmin.signOut(u.id), `${u.username} signed out everywhere.`)}>Sign out</button>
                <button className="ghost-btn sm danger"
                        onClick={() => confirm(`Delete ${u.username}? Their reviews stay, shown as a deleted user.`)
                          && run(() => fmAdmin.deleteUser(u.id), `${u.username} deleted.`)}>Delete</button>
              </>
            )}
          </li>
        ))}
        {users.length === 0 && <li className="fp-empty">No family accounts yet.</li>}
      </ul>
      <div className="fma-toolbar">
        <input value={name} placeholder="Username" onChange={(e) => setName(e.target.value)} />
        <input type="password" value={password} placeholder="Password (10+ characters)"
               onChange={(e) => setPassword(e.target.value)} />
        <button className="primary-btn sm" disabled={!name.trim() || password.length < 10}
                onClick={() => run(() => fmAdmin.createUser(name, password), `${name.trim()} can now sign in at /fm/.`)
                  .then((ok) => { if (ok) { setName(''); setPassword(''); } })}>Add family member</button>
      </div>
      {note && <p className="fma-ok">{note}</p>}
      {error && <p className="fma-error">{error}</p>}
    </section>
  );
}

// ---- OSM import (2.44.0) ----------------------------------------------------------------

/** The import's rows: the six categories, plus the town names that
    Spørg Alf looks places up by (2.46.0). */
const catLabel = (cats: FmCategories, c: string) =>
  cats[c]?.label ?? (c === 'localities' ? 'Town names' : c);

const STATE_TEXT: Record<string, string> = {
  waiting: 'waiting', fetching: 'asking Overpass…', retrying: 'Overpass busy', saving: 'saving…',
  done: 'done', failed: 'failed', stopped: 'stopped',
};

function ImportTab({ cats, onChanged }: { cats: FmCategories; onChanged: () => void }) {
  const [st, setSt] = useState<FmImportState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    fmAdmin.importState().then(setSt).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  // Poll while an import runs; one category can take minutes on Overpass.
  useEffect(() => {
    if (!st?.running) return;
    const t = window.setInterval(() => {
      fmAdmin.importState().then((n) => { setSt(n); if (!n.running) onChanged(); })
        .catch(() => {});
    }, 2000);
    return () => window.clearInterval(t);
  }, [st?.running, onChanged]);

  const run = async (fn: () => Promise<FmImportState>) => {
    setError(null);
    try { setSt(await fn()); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  if (!st) return <div className="empty">{error ?? 'Loading…'}</div>;
  const ran = Object.keys(st.categories ?? {}).length > 0;
  const failed = Object.entries(st.categories ?? {})
    .filter(([, e]) => e.state === 'failed' || e.state === 'stopped').map(([c]) => c);

  return (
    <section className="fma-main fma-scroll fma-pad" data-help="familymap.import">
      <p className="fp-empty">
        Places come from OpenStreetMap for {st.region}, one Overpass query per category. Only
        places with a name are taken. Running it again updates what OSM changed and adds what
        is new; it never deletes, and never changes a place you edited. The family page
        credits "© OpenStreetMap-bidragydere".
      </p>
      <table className="fma-table fma-import">
        <thead>
          <tr><th>Category</th><th>From OSM</th><th>State</th><th className="num">Found</th>
            <th className="num">Added</th><th className="num">Updated</th>
            <th className="num">Same</th><th className="num">Edited</th><th className="num">s</th></tr>
        </thead>
        <tbody>
          {Object.entries(st.sources ?? {}).map(([c, sel]) => {
            const e = st.categories?.[c];
            return (
              <tr key={c}>
                <td>{catLabel(cats, c)}</td>
                <td className="dim fma-wrap">{sel.join('; ')}</td>
                <td className={e?.state === 'failed' ? 'fma-bad' : ''} title={e?.error}>
                  {e ? STATE_TEXT[e.state] ?? e.state : ''}{e?.error ? `: ${e.error}` : ''}
                </td>
                <td className="num">{e?.found ?? ''}</td>
                <td className="num">{e?.added ?? ''}</td>
                <td className="num">{e?.updated ?? ''}</td>
                <td className="num">{e?.unchanged ?? ''}</td>
                <td className="num">{e?.locked ?? ''}</td>
                <td className="num">{e?.seconds ?? ''}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="fma-actions fma-gap">
        {st.running ? (
          <button className="ghost-btn sm danger" onClick={() => run(fmAdmin.stopImport)}>Stop import</button>
        ) : (
          <>
            {failed.length > 0 && (
              <button className="primary-btn sm" onClick={() => run(() => fmAdmin.startImport(failed))}>
                Retry failed ({failed.map((c) => catLabel(cats, c)).join(', ')})
              </button>
            )}
            <button className={failed.length ? 'ghost-btn sm' : 'primary-btn sm'}
                    onClick={() => run(() => fmAdmin.startImport())}>
              {ran ? 'Import all again' : 'Import all categories'}
            </button>
          </>
        )}
        <span className="dim fma-small">
          {st.running ? `Running since ${st.startedAt?.slice(11, 16)} UTC. You can leave this page.`
            : st.finishedAt ? `Last run finished ${st.finishedAt.replace('T', ' ').slice(0, 16)} UTC${st.error ? ` (${st.error})` : ''}.`
            : 'Not run since the backend started.'}
        </span>
      </div>
      {error && <p className="fma-error">{error}</p>}
    </section>
  );
}

// ---- settings (2.44.0) ----------------------------------------------------------------

function SettingsTab({ stats, onChanged }: { stats: FmStats | null; onChanged: () => void }) {
  const [s, setS] = useState<FmSettings | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [overpass, setOverpass] = useState('');
  const [appName, setAppName] = useState('');
  const [roles, setRoles] = useState<{ chat: string; vision: string } | null>(null);
  useEffect(() => {
    fmAdmin.roles().then(setRoles).catch(() => setRoles(null));
    fmAdmin.settings().then((v) => { setS(v); setOverpass(v.overpassUrl); setAppName(v.appName); })
      .catch((e) => setError(e.message));
    fmAdmin.models().then(setModels).catch(() => setModels([]));
  }, []);

  // One key per write, never the whole object: a stale copy must not undo
  // a change made meanwhile.
  const save = async (key: keyof FmSettings, value: string) => {
    setError(null); setNote(null);
    try {
      const next = await fmAdmin.setSetting(key, value);
      setS(next);
      if (key === 'appName') setAppName(next.appName);    // empty falls back to the default
      setNote('Saved.');
    }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  const describe = async () => {
    setError(null); setNote(null);
    try {
      const r = await fmAdmin.describeWaiting();
      setNote(`${r.queued} photo(s) queued for the vision model.`);
      onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  if (!s) return <div className="empty">{error ?? 'Loading…'}</div>;
  const ps = stats?.photoStates;
  const waiting = ps ? ps.pending + ps.failed + ps.nomodel : 0;
  // FamilyLog: empty = the role chosen in the app's Settings.
  const options = (current: string, role: 'chat' | 'vision') => {
    const list = current && !models.includes(current) ? [current, ...models] : models;
    const fromSettings = roles?.[role];
    return [<option key="" value="">{fromSettings ? `Settings: ${fromSettings}` : '— none (set one in Settings) —'}</option>,
            ...list.map((m) => <option key={m} value={m}>{m}{models.includes(m) ? '' : ' (not installed)'}</option>)];
  };

  return (
    <section className="fma-main fma-scroll fma-pad fma-settings" data-help="familymap.settings">
      <label className="fma-row"><span>Name of the family page - its title, login and header</span>
        <input value={appName} maxLength={40} onChange={(e) => setAppName(e.target.value)}
               onBlur={() => { if (appName !== s.appName) save('appName', appName); }} />
      </label>
      <p className="fma-note">Empty goes back to Alf’s Atlas. "FamilyMap" stays the name of
        this admin section.</p>

      <p className="fp-empty">Empty uses the model chosen for that role in the app's Settings;
        a model chosen here is used by FamilyMap instead.</p>
      <label className="fma-row"><span>Vision model - describes each visit photo</span>
        <select value={s.visionModel} onChange={(e) => save('visionModel', e.target.value)}>
          {options(s.visionModel, 'vision')}
        </select>
      </label>
      <p className="fma-note">
        Photos are described automatically when uploaded, in the app's GPU queue (after
        anything already waiting). The description is for the day-ideas model, not shown to
        the family.
        {ps && ` Now: ${ps.done} described, ${ps.queued} queued, ${waiting} waiting`}
        {ps && ps.failed > 0 && ` (${ps.failed} failed)`}{ps && '.'}
      </p>
      <div>
        <button className="ghost-btn sm" disabled={!(s.visionModel || roles?.vision) || waiting === 0} onClick={describe}>
          Describe waiting photos{waiting ? ` (${waiting})` : ''}
        </button>
      </div>

      <label className="fma-row"><span>Chat model - answers the family's day ideas</span>
        <select value={s.chatModel} onChange={(e) => save('chatModel', e.target.value)}>
          {options(s.chatModel, 'chat')}
        </select>
      </label>
      <p className="fma-note">Spørg Alf on the family page.</p>

      <label className="fma-row"><span>Overpass address - where the OSM import asks</span>
        <input value={overpass} placeholder="Empty = the Overpass address in Settings"
               onChange={(e) => setOverpass(e.target.value)}
               onBlur={() => { if (overpass !== s.overpassUrl) save('overpassUrl', overpass); }} />
      </label>
      {note && <p className="fma-ok">{note}</p>}
      {error && <p className="fma-error">{error}</p>}
    </section>
  );
}
