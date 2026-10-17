import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api } from './api';
import type {
  ComfyTest, Diagnostics, OllamaTest, SettingsDto, SettingsPatch, UserDto,
} from './types';

/** The app's global settings (admin only): the Ollama connection and the
    model per role, the GPU, web search, maps, time zone, the accounts and
    diagnostics. One Save for the settings; Test buttons act at once on the
    address typed in the form, saved or not. A value pinned by the
    container's environment is shown locked, with the variable named. */
export function SettingsPage({ me }: { me: { id: number } }) {
  const [saved, setSaved] = useState<SettingsDto | null>(null);
  const [draft, setDraft] = useState<SettingsPatch>({});
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getSettings().then(setSaved).catch((e) => setError((e as Error).message));
  }, []);

  const value = <K extends keyof SettingsPatch>(k: K): SettingsPatch[K] =>
    (k in draft ? draft[k] : (saved as unknown as SettingsPatch | null)?.[k]) as SettingsPatch[K];
  const set = <K extends keyof SettingsPatch>(k: K, v: SettingsPatch[K]) => {
    setNote(null);
    setDraft((d) => {
      const next = { ...d, [k]: v };
      // The key: typed-then-erased is "no change"; only null (Remove) clears it.
      if (k === 'searchApiKey' ? v === '' : saved && (saved as unknown as SettingsPatch)[k] === v) delete next[k];
      return next;
    });
  };
  const dirty = Object.keys(draft).length > 0;
  const pinned = (k: string) => saved?.envPinned[k];

  async function save() {
    setBusy(true); setError(null); setNote(null);
    try {
      setSaved(await api.saveSettings(draft));
      setDraft({});
      setNote('Saved.');
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  if (!saved) return <div className="settings-page"><p className="empty">{error ?? 'Loading…'}</p></div>;

  return (
    <div className="settings-page">
      <div className="settings-inner">
        <header className="settings-head" data-help="app.settings">
          <h1>Settings</h1>
          <span className="appbar-spacer" />
          {note && <span className="fma-ok">{note}</span>}
          {error && <span className="fma-error">{error}</span>}
          <button className="ghost-btn" disabled={!dirty || busy} onClick={() => { setDraft({}); setNote(null); }}>Undo</button>
          <button className="primary-btn" disabled={!dirty || busy} onClick={() => void save()}>
            {busy ? 'Saving…' : dirty ? `Save (${Object.keys(draft).length})` : 'Saved'}
          </button>
        </header>

        <OllamaGroup value={value} set={set} pinned={pinned} />
        <GpuGroup value={value} set={set} pinned={pinned} />
        <SearchGroup value={value} set={set} pinned={pinned} keySet={saved.searchApiKeySet} />
        <Group title="Maps" help="settings.maps">
          <Text label="Nominatim (address lookup)" k="nominatimUrl" value={value} set={set} pinned={pinned}
                hint="Server for turning a tapped point into an address on the family page. /reverse is added." />
          <Text label="Overpass (OSM import)" k="overpassUrl" value={value} set={set} pinned={pinned}
                hint="Where FamilyMap's OSM import asks. FamilyMap → Settings can override it." />
        </Group>
        <Group title="General" help="settings.general">
          <Text label="Time zone" k="timezone" value={value} set={set} pinned={pinned}
                hint="IANA name, e.g. Europe/Copenhagen. Used for dates such as “this year” in Økonomi." />
        </Group>
        <AccountsGroup meId={me.id} />
        <DiagnosticsGroup />
      </div>
    </div>
  );
}

// ---- building blocks ----------------------------------------------------------------

type Value = <K extends keyof SettingsPatch>(k: K) => SettingsPatch[K];
type Setter = <K extends keyof SettingsPatch>(k: K, v: SettingsPatch[K]) => void;
type Pinned = (k: string) => string | undefined;

function Group({ title, help, children, aside }: { title: string; help: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="settings-group" data-help={help}>
      <div className="settings-group-head"><h2>{title}</h2>{aside}</div>
      {children}
    </section>
  );
}

function Row({ label, hint, children, lock }: { label: string; hint?: ReactNode; children: ReactNode; lock?: string }) {
  return (
    <label className="settings-row">
      <span className="settings-label">{label}</span>
      <span className="settings-control">
        {children}
        {lock && <small className="settings-lock">Set by <code>{lock}</code> in the container's environment - change it there.</small>}
        {hint && !lock && <small>{hint}</small>}
      </span>
    </label>
  );
}

function Text({ label, k, value, set, pinned, hint, placeholder }: {
  label: string; k: 'ollamaUrl' | 'comfyUrl' | 'searxngUrl' | 'nominatimUrl' | 'overpassUrl' | 'timezone'
    | 'ollamaKeepAlive' | 'searchBlockedRanges';
  value: Value; set: Setter; pinned: Pinned; hint?: ReactNode; placeholder?: string;
}) {
  const lock = pinned(k);
  return (
    <Row label={label} hint={hint} lock={lock}>
      <input value={String(value(k) ?? '')} disabled={!!lock} placeholder={placeholder}
             onChange={(e) => set(k, e.target.value)} />
    </Row>
  );
}

function modelOptions(models: string[], current: string, empty: string) {
  const list = current && !models.includes(current) ? [current, ...models] : models;
  return [<option key="" value="">{empty}</option>,
          ...list.map((m) => <option key={m} value={m}>{m}{models.includes(m) ? '' : ' (not on the server)'}</option>)];
}

// ---- Ollama ---------------------------------------------------------------------------

function OllamaGroup({ value, set, pinned }: { value: Value; set: Setter; pinned: Pinned }) {
  const [test, setTest] = useState<OllamaTest | null>(null);
  const [testing, setTesting] = useState(false);
  const [installed, setInstalled] = useState<string[]>([]);
  useEffect(() => { api.listOllamaModels().then(setInstalled).catch(() => setInstalled([])); }, []);
  const names = useMemo(() => test?.ok ? test.models.map((m) => m.name) : installed, [test, installed]);

  async function runTest() {
    setTesting(true);
    try { setTest(await api.testOllama(String(value('ollamaUrl') ?? ''))); }
    catch (e) { setTest({ ok: false, url: '', models: [], error: (e as Error).message }); }
    finally { setTesting(false); }
  }

  return (
    <Group title="Ollama" help="settings.ollama">
      <Text label="Ollama address" k="ollamaUrl" value={value} set={set} pinned={pinned}
            hint="The GPU VM's Ollama, e.g. http://30.11.0.104:11434." />
      <div className="settings-row">
        <span className="settings-label" />
        <span className="settings-control">
          <span className="settings-inline" data-help="settings.ollamaTest">
            <button className="ghost-btn" disabled={testing} aria-label="Test Ollama" onClick={() => void runTest()}>
              {testing ? 'Testing…' : 'Test'}
            </button>
            {test && (test.ok
              ? <span className="fma-ok">Connected - {test.models.length} model{test.models.length === 1 ? '' : 's'} at {test.url}</span>
              : <span className="fma-error">{test.error}</span>)}
          </span>
          {test?.ok && test.models.length > 0 && (
            <table className="settings-models">
              <thead><tr><th>Model</th><th>Size</th><th>Parameters</th><th>Quantisation</th></tr></thead>
              <tbody>
                {test.models.map((m) => (
                  <tr key={m.name}><td>{m.name}</td><td>{m.size ? `${(m.size / 1e9).toFixed(1)} GB` : ''}</td>
                    <td>{m.parameters ?? ''}</td><td>{m.quantization ?? ''}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </span>
      </div>
      <div data-help="settings.models">
        <Row label="Chat / answers" hint="Økonomi questions and Spørg Alf on the family page.">
          <select value={String(value('modelChat') ?? '')} onChange={(e) => set('modelChat', e.target.value)}>
            {modelOptions(names, String(value('modelChat') ?? ''), '— none —')}
          </select>
        </Row>
        <Row label="Vision" hint="Describes FamilyMap photos. Must be a vision model; never falls back to the chat model.">
          <select value={String(value('modelVision') ?? '')} onChange={(e) => set('modelVision', e.target.value)}>
            {modelOptions(names, String(value('modelVision') ?? ''), '— none (photos wait) —')}
          </select>
        </Row>
        <Row label="Categorise" hint="Sorts unknown merchants in Økonomi. Empty uses the chat model.">
          <select value={String(value('modelCategorise') ?? '')} onChange={(e) => set('modelCategorise', e.target.value)}>
            {modelOptions(names, String(value('modelCategorise') ?? ''), 'Same as the chat model')}
          </select>
        </Row>
        {names.length === 0 && <p className="settings-note">No models listed - press Test to read them from the address above.</p>}
      </div>
      <details className="settings-more">
        <summary>More</summary>
        <Text label="Keep loaded" k="ollamaKeepAlive" value={value} set={set} pinned={pinned}
              placeholder="Ollama's default (5m)"
              hint="How long Ollama keeps a model after a call: 5m, 30m, -1 (until unloaded). The GPU is shared, so short is kind." />
        <Row label="Context window, max" hint="Tokens asked for at most; smaller if the model's own length is smaller.">
          <input type="number" min={2048} max={262144} step={1024} value={Number(value('contextMax') ?? 16384)}
                 onChange={(e) => set('contextMax', Number(e.target.value))} />
        </Row>
      </details>
    </Group>
  );
}

// ---- GPU ------------------------------------------------------------------------------

function GpuGroup({ value, set, pinned }: { value: Value; set: Setter; pinned: Pinned }) {
  const [test, setTest] = useState<ComfyTest | null>(null);
  const url = String(value('comfyUrl') ?? '');
  return (
    <Group title="GPU" help="settings.gpu">
      <p className="settings-note">
        Ollama shares one GPU with ComfyUI (and SLQ). This app runs one model job at a time in
        its own queue.
      </p>
      <Text label="ComfyUI address" k="comfyUrl" value={value} set={set} pinned={pinned}
            placeholder="Empty = not used"
            hint="Only used to ask ComfyUI to free its VRAM before a model job." />
      <div className="settings-row">
        <span className="settings-label" />
        <span className="settings-control settings-inline">
          <button className="ghost-btn" disabled={!url} aria-label="Test ComfyUI"
                  onClick={async () => setTest(await api.testComfy(url))}>Test</button>
          {test && <span className={test.ok ? 'fma-ok' : 'fma-error'}>{test.message}</span>}
        </span>
      </div>
      <Row label="Free ComfyUI VRAM first" hint={url ? 'Before each model job (best effort; a few seconds at most).'
        : 'Has no effect until a ComfyUI address is set.'}>
        <input type="checkbox" className="checkbox" checked={Boolean(value('comfyFreeFirst'))}
               onChange={(e) => set('comfyFreeFirst', e.target.checked)} />
      </Row>
      <Row label="Queue" hint="A shared GPU queue with SLQ comes when SLQ's GPU-job API exists.">
        <span className="settings-static">Local - this app's own queue</span>
      </Row>
    </Group>
  );
}

// ---- web search ---------------------------------------------------------------------------

function SearchGroup({ value, set, pinned, keySet }: { value: Value; set: Setter; pinned: Pinned; keySet: boolean }) {
  const provider = String(value('searchProvider') ?? 'duckduckgo');
  const key = value('searchApiKey');
  return (
    <Group title="Web search" help="settings.search">
      <p className="settings-note">Spørg Alf searches the web when the family's own places are too few.</p>
      <Row label="Provider">
        <select value={provider} onChange={(e) => set('searchProvider', e.target.value as SettingsDto['searchProvider'])}>
          <option value="duckduckgo">DuckDuckGo (no key)</option>
          <option value="searxng">SearXNG (your own)</option>
          <option value="brave">Brave Search API (key)</option>
        </select>
      </Row>
      {provider === 'searxng' && (
        <Text label="SearXNG address" k="searxngUrl" value={value} set={set} pinned={pinned} placeholder="http://…" />
      )}
      {provider === 'brave' && (
        <Row label="Brave API key" hint={key === null ? 'Will be removed on Save.' : keySet ? 'A key is saved. Type a new one to replace it.' : 'No key saved.'}>
          <span className="settings-inline">
            <input type="password" autoComplete="off" value={typeof key === 'string' ? key : ''}
                   placeholder={keySet ? '•••••••• (saved)' : ''} onChange={(e) => set('searchApiKey', e.target.value)} />
            {keySet && <button className="ghost-btn sm" onClick={() => set('searchApiKey', null)}>Remove</button>}
          </span>
        </Row>
      )}
      <details className="settings-more">
        <summary>More</summary>
        <Row label="Results asked for">
          <input type="number" min={0} max={10} value={Number(value('searchResults') ?? 4)}
                 onChange={(e) => set('searchResults', Number(e.target.value))} />
        </Row>
        <Row label="Pages read">
          <input type="number" min={0} max={10} value={Number(value('searchFetch') ?? 3)}
                 onChange={(e) => set('searchFetch', Number(e.target.value))} />
        </Row>
        <Text label="Never fetch these ranges" k="searchBlockedRanges" value={value} set={set} pinned={pinned}
              placeholder="e.g. 30.11.0.0/24"
              hint="Comma-separated CIDRs. Private and loopback addresses, Ollama and ComfyUI are always blocked." />
      </details>
    </Group>
  );
}

// ---- accounts ----------------------------------------------------------------------------

function AccountsGroup({ meId }: { meId: number }) {
  const [users, setUsers] = useState<UserDto[]>([]);
  const [economy, setEconomy] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<'user' | 'family'>('user');
  const [resetFor, setResetFor] = useState<number | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const load = useCallback(() => {
    api.users().then(setUsers).catch((e) => setError((e as Error).message));
    api.economyAccess().then((v) => setEconomy(new Set(v))).catch((e) => setError((e as Error).message));
  }, []);
  useEffect(load, [load]);

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setError(null); setNote(null);
    try { await fn(); setNote(done); load(); return true; }
    catch (e) { setError((e as Error).message); return false; }
  };

  return (
    <Group title="Accounts" help="settings.accounts">
      <p className="settings-note">Family accounts use the front page (/) and Alf's Atlas only and do not count
        towards the account limit. Everyone with Økonomi has their own data; a family account gets it when you turn it on here.
        Accounts set to female get Cyklus; what she shares, she decides herself.</p>
      <ul className="user-list">
        {users.map((u) => (
          <li key={u.id}>
            <span className={`user-dot${u.online ? ' on' : ''}`} title={u.online ? 'Signed in' : 'Not signed in'} />
            <span className="user-name">{u.username}</span>
            <span className="user-role">{u.role}{u.id === meId ? ' (you)' : ''}</span>
            <select className="user-pick" aria-label={`Gender of ${u.username}`} value={u.gender ?? ''}
                    title="Accounts set to female get Cyklus on the front page"
                    onChange={(e) => void run(() => api.setGender(u.id, e.target.value), `${u.username} updated.`)}>
              <option value="">gender: not set</option>
              <option value="female">female</option>
              <option value="male">male</option>
            </select>
            {u.role === 'family' && (
              <select className="user-pick" aria-label={`Økonomi for ${u.username}`} value={economy.has(u.id) ? 'own' : ''}
                      title="Their own Økonomi on the front page - their own bank data"
                      onChange={(e) => void run(() => api.setEconomyAccess(u.id, e.target.value === 'own'),
                        e.target.value ? `${u.username} now has their own Økonomi.` : `${u.username} no longer has Økonomi.`)}>
                <option value="">Økonomi: no</option>
                <option value="own">Økonomi: own data</option>
              </select>
            )}
            {resetFor === u.id ? (
              <>
                <input type="password" className="fma-inline" placeholder="New password (10+)"
                       value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
                <button className="ghost-btn sm" disabled={newPassword.length < 10}
                        onClick={() => run(() => api.setPassword(u.id, newPassword), `${u.username}'s password changed.`)
                          .then((ok) => { if (ok) { setResetFor(null); setNewPassword(''); } })}>Set</button>
                <button className="ghost-btn sm" onClick={() => setResetFor(null)}>Cancel</button>
              </>
            ) : (
              <>
                <button className="ghost-btn sm" onClick={() => { setResetFor(u.id); setNewPassword(''); }}>Password</button>
                {u.id !== meId && <button className="ghost-btn sm" disabled={!u.online}
                  onClick={() => run(() => api.signOut(u.id), `${u.username} signed out everywhere.`)}>Sign out</button>}
                {u.id !== meId && <button className="ghost-btn sm danger"
                  onClick={() => { if (confirm(`Delete ${u.username}? Their Økonomi data stays in the database but nobody can open it.`))
                    void run(() => api.deleteUser(u.id), `${u.username} deleted.`); }}>Delete</button>}
              </>
            )}
          </li>
        ))}
      </ul>
      <div className="settings-inline settings-add">
        <input placeholder="Username" value={name} onChange={(e) => setName(e.target.value)} />
        <input type="password" placeholder="Password (10+)" value={password} onChange={(e) => setPassword(e.target.value)} />
        <select value={role} onChange={(e) => setRole(e.target.value as 'user' | 'family')}>
          <option value="user">user</option>
          <option value="family">family</option>
        </select>
        <button className="ghost-btn" disabled={!name.trim() || password.length < 10}
                onClick={() => run(() => api.createUser(name.trim(), password, role), `${name.trim()} added.`)
                  .then((ok) => { if (ok) { setName(''); setPassword(''); } })}>Add</button>
      </div>
      {note && <p className="fma-ok">{note}</p>}
      {error && <p className="fma-error">{error}</p>}
    </Group>
  );
}

// ---- diagnostics --------------------------------------------------------------------------

function DiagnosticsGroup() {
  const [d, setD] = useState<Diagnostics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => { api.diagnostics().then(setD).catch((e) => setError((e as Error).message)); }, []);
  useEffect(load, [load]);
  return (
    <Group title="Diagnostics" help="settings.diagnostics"
           aside={<span className="settings-inline"><button className="ghost-btn sm" onClick={load}>Refresh</button>
             <button className="ghost-btn sm" onClick={async () => { await api.clearRecent(); load(); }}>Clear errors</button></span>}>
      {error && <p className="fma-error">{error}</p>}
      {d && (
        <>
          <p className="settings-note">
            Version {d.version} · queue: {d.queue.running ? `running ${d.queue.running.kind}` : 'idle'}
            {d.queue.pending.length ? `, ${d.queue.pending.length} waiting` : ''}
          </p>
          {d.recent.length === 0 ? <p className="settings-note">No errors since the last start.</p> : (
            <ul className="diag-list">
              {d.recent.map((e, i) => (
                <li key={i}><details><summary><span className="diag-time">{e.time.slice(0, 19).replace('T', ' ')}</span> {e.message}</summary>
                  {e.traceback && <pre>{e.traceback}</pre>}</details></li>
              ))}
            </ul>
          )}
        </>
      )}
    </Group>
  );
}
