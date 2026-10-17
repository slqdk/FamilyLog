import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Wordmark } from '../sections/familymap/phone/art';
import type { FmUser } from '../sections/familymap/phone/types';
import { homeApi, type CyState, type OkState } from './api';
import { Chat } from './Chat';
import { CyklusCalendar, CyklusDayPage, CyklusPage, CyklusShare, cyklusTileLine } from './Cyklus';
import { DagbogPage, FamilyWeek } from './Dagbog';
import { OkonomiPage } from './Okonomi';
import { parseRoute, routeHash, todayLocal, type HomeRoute } from './logic';

/** The front page (FamilyLog 0.2.0): for everyone in the family, on the
    phone first. Alf to talk to, and the way into Alf's Atlas, the Dagbog
    and - for the grown-ups' accounts - Økonomi. Same look as Alf's Atlas. */

export function go(r: HomeRoute) { window.location.hash = routeHash(r); }

function useRoute(): HomeRoute {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const on = () => { setRoute(parseRoute(window.location.hash)); window.scrollTo(0, 0); };
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return route;
}

export function HomeApp() {
  const [me, setMe] = useState<FmUser | null | false>(null);
  const [name, setName] = useState('FamilyLog');
  const [atlas, setAtlas] = useState('Alf’s Atlas');
  const route = useRoute();

  useEffect(() => {
    homeApi.meta().then((m) => { setName(m.name); document.title = m.name; }).catch(() => {});
    homeApi.atlasName().then((b) => setAtlas(b.name)).catch(() => {});
    homeApi.status().then((s) => {
      // First run: the administrator is made in the admin app.
      if (s.needsSetup) { window.location.replace('/app/'); return; }
      setMe(s.user ?? false);
    }).catch(() => setMe(false));
  }, []);

  if (me === null) return <div className="fm-wait">Et øjeblik…</div>;
  if (me === false) return <Login name={name} onIn={setMe} />;
  const signOut = async () => { await homeApi.logout().catch(() => {}); setMe(false); };

  if (route.name === 'dagbog') return <DagbogPage day={route.day ?? todayLocal()} />;
  if (route.name === 'family') return <FamilyWeek me={me} week={route.week} />;
  if (route.name === 'okonomi') return <OkonomiPage month={route.month} />;
  if (route.name === 'cyklus') return <CyklusPage />;
  if (route.name === 'cyklusDay') return <CyklusDayPage day={route.day} />;
  if (route.name === 'cyklusCal') return <CyklusCalendar month={route.month} />;
  if (route.name === 'cyklusShare') return <CyklusShare />;
  return <Home me={me} name={name} atlas={atlas} onSignOut={signOut} />;
}

function Login({ name, onIn }: { name: string; onIn: (u: FmUser) => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try { onIn((await homeApi.login(username, password)).user); }
    catch (err) {
      setError(err instanceof Error && err.message !== 'Wrong username or password.'
        ? err.message : 'Forkert brugernavn eller adgangskode.');
    } finally { setBusy(false); }
  }
  return (
    <main className="fm-login">
      <Wordmark name={name} />
      <p className="fm-tagline">Familiens egen side - Alf, steder og dagbog.</p>
      <form onSubmit={submit} className="fm-stack fm-sheet">
        <label className="fm-field"><span className="fm-label">Brugernavn</span>
          <input name="username" value={username} autoComplete="username" autoCapitalize="none"
                 onChange={(e) => setUsername(e.target.value)} /></label>
        <label className="fm-field"><span className="fm-label">Adgangskode</span>
          <input name="password" type="password" value={password} autoComplete="current-password"
                 onChange={(e) => setPassword(e.target.value)} /></label>
        {error && <p className="fm-error">{error}</p>}
        <button className="fm-primary" disabled={busy || !username || !password}>
          {busy ? 'Logger ind…' : 'Log ind'}
        </button>
      </form>
    </main>
  );
}

function Home({ me, name, atlas, onSignOut }: {
  me: FmUser; name: string; atlas: string; onSignOut: () => void;
}) {
  const [menu, setMenu] = useState(false);
  const [newChat, setNewChat] = useState(0);
  return (
    <div className="fm-page hm-page">
      <header className="fm-top hm-top">
        <div className="fm-top-row">
          <Wordmark name={name} className="hm-wordmark" />
          <button className="fm-burger" onClick={() => setMenu(true)} aria-expanded={menu} aria-label="Menu">
            <span /><span /><span />
          </button>
        </div>
        {menu && <Menu me={me} onClose={() => setMenu(false)} onSignOut={onSignOut}
                       onNewChat={() => setNewChat((n) => n + 1)} />}
        <Shortcuts me={me} atlas={atlas} />
      </header>
      <Chat me={me} resetKey={newChat} />
    </div>
  );
}

/** The way into the rest. Økonomi (0.3.0) for the grown-ups' accounts and
    the family accounts the administrator gave access; Cyklus for accounts
    set to female, and for anyone a woman shares hers with. */
export function Shortcuts({ me: _me, atlas }: { me: FmUser; atlas: string }) {
  const [filled, setFilled] = useState<boolean | null>(null);
  const [ok, setOk] = useState<OkState | null>(null);
  const [cy, setCy] = useState<CyState | null>(null);
  useEffect(() => {
    const t = todayLocal();
    homeApi.mine(t, t).then((r) => setFilled(r.days.includes(t))).catch(() => setFilled(null));
    homeApi.okState().then(setOk).catch(() => setOk(null));
    homeApi.cyState().then(setCy).catch(() => setCy(null));
  }, []);
  const cyLine = cy && (cy.enabled || cy.shared.length > 0) ? cyklusTileLine(cy) : null;
  return (
    <nav className="hm-tiles" aria-label="Genveje">
      <a className="hm-tile" href="/fm/">
        <span className="hm-tile-icon" aria-hidden>🗺️</span>
        <span className="hm-tile-name">{atlas}</span>
        <span className="hm-tile-sub">Steder og anmeldelser</span>
      </a>
      <a className="hm-tile" href={routeHash({ name: 'dagbog', day: null })}>
        <span className="hm-tile-icon" aria-hidden>📔</span>
        <span className="hm-tile-name">Dagbog</span>
        <span className={`hm-tile-sub${filled === false ? ' hm-todo' : ''}`}>
          {filled ? 'I dag ✓' : filled === false ? 'Hvordan var i dag?' : 'Din dag'}
        </span>
      </a>
      {ok?.access && (
        <a className="hm-tile" href={routeHash({ name: 'okonomi', month: null })}>
          <span className="hm-tile-icon" aria-hidden>💰</span>
          <span className="hm-tile-name">Økonomi</span>
          <span className="hm-tile-sub">{ok.own ? 'Konti og forbrug' : `${ok.owner}s forbrug`}</span>
        </a>
      )}
      {cyLine !== null && (
        <a className="hm-tile hm-tile-cy" href={routeHash({ name: 'cyklus' })}>
          <span className="hm-tile-icon" aria-hidden>🌸</span>
          <span className="hm-tile-name">Cyklus</span>
          <span className="hm-tile-sub">{cyLine}</span>
        </a>
      )}
    </nav>
  );
}

function Menu({ me, onClose, onSignOut, onNewChat }: {
  me: FmUser; onClose: () => void; onSignOut: () => void; onNewChat: () => void;
}) {
  return createPortal(
    <div className="fm-scrim" role="dialog" aria-modal="true" aria-label="Menu" onClick={onClose}>
      <nav className="fm-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="fm-drawer-head">
          <span className="fm-drawer-who">{me.username}</span>
          <button className="fm-x" onClick={onClose} aria-label="Luk menuen">×</button>
        </div>
        <button className="fm-drawer-item" onClick={() => { onClose(); onNewChat(); }}>Ny samtale med Alf</button>
        <a className="fm-drawer-item" href={routeHash({ name: 'dagbog', day: null })} onClick={onClose}>Min dagbog</a>
        <a className="fm-drawer-item" href={routeHash({ name: 'family', week: null })} onClick={onClose}>Familiens uge</a>
        <a className="fm-drawer-item" href="/fm/">Alf’s Atlas</a>
        {me.gender === 'female' && <a className="fm-drawer-item" href={routeHash({ name: 'cyklus' })} onClick={onClose}>Cyklus</a>}
        {me.role !== 'family' && <a className="fm-drawer-item" href="/app/">Admin-appen</a>}
        {me.role === 'admin' && <a className="fm-drawer-item" href="/app/#settings">Indstillinger</a>}
        <button className="fm-drawer-item fm-drawer-out" onClick={() => { onClose(); onSignOut(); }}>Log ud</button>
      </nav>
    </div>,
    document.body,
  );
}
