import { useCallback, useEffect, useState } from 'react';
import { api } from './core/api';
import type { AuthUser } from './core/types';
import { HELP_EVENT, installAltClickHelp, openHelp, type HelpRequest } from './core/help';
import { HelpPanel } from './core/HelpPanel';
import { LoginScreen } from './core/LoginScreen';
import { SettingsPage } from './core/SettingsPage';
import { sectionsFor } from './sections/registry';

/** The shell: sign-in, the section navigation with each section's pages,
    Settings (admin), help and the account menu. What a section shows is
    the section's own business (sections/<id>/). */

const VIEW_KEY = 'app.view';
interface View { section: string; tabs: Record<string, string> }

function loadView(): View {
  try {
    const v = JSON.parse(localStorage.getItem(VIEW_KEY) || '{}');
    return { section: typeof v.section === 'string' ? v.section : '', tabs: v.tabs && typeof v.tabs === 'object' ? v.tabs : {} };
  } catch { return { section: '', tabs: {} }; }
}

function saveView(v: View) {
  try { localStorage.setItem(VIEW_KEY, JSON.stringify(v)); } catch { /* private mode */ }
}

export function App() {
  const [appName, setAppName] = useState('FamilyLog');
  const [version, setVersion] = useState('');
  const [me, setMe] = useState<AuthUser | null | false>(null);   // null = loading, false = signed out
  const [needsSetup, setNeedsSetup] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [view, setView] = useState<View>(loadView);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [help, setHelp] = useState<(HelpRequest & { key: number }) | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  const checkAuth = useCallback(() => {
    setLoadError(null);
    api.authStatus().then((s) => { setNeedsSetup(s.needsSetup); setMe(s.user ?? false); })
      .catch((e) => setLoadError((e as Error).message));
  }, []);

  useEffect(() => {
    api.meta().then((m) => { setAppName(m.name); setVersion(m.version); document.title = m.name; }).catch(() => {});
    checkAuth();
  }, [checkAuth]);

  useEffect(() => installAltClickHelp(), []);
  useEffect(() => {
    const onHelp = (e: Event) => {
      const d = (e as CustomEvent<HelpRequest>).detail;
      setHelp((h) => ({ ...d, key: (h?.key ?? 0) + 1 }));
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setHelp(null); setMenuOpen(false); } };
    window.addEventListener(HELP_EVENT, onHelp);
    window.addEventListener('keydown', onKey);
    return () => { window.removeEventListener(HELP_EVENT, onHelp); window.removeEventListener('keydown', onKey); };
  }, []);

  useEffect(() => saveView(view), [view]);

  if (loadError) {
    return (
      <div className="login-wrap"><div className="login-card">
        <h2>Cannot reach the server</h2>
        <p className="login-lead">{loadError}</p>
        <button className="primary-btn" onClick={checkAuth}>Try again</button>
      </div></div>
    );
  }
  if (me === null) return <div className="login-wrap"><div className="login-card">Loading…</div></div>;
  if (me === false) {
    return <LoginScreen appName={appName} needsSetup={needsSetup} onSignedIn={(u) => setMe(u)} />;
  }
  // A family account has only the family page; every other endpoint refuses it.
  if (me.role === 'family') {
    window.location.replace('/fm/');
    return <div className="login-wrap"><div className="login-card">Opening the family page…</div></div>;
  }

  const sections = sectionsFor(me.role);
  const current = sections.find((s) => s.id === view.section) ?? sections[0];
  const tab = view.tabs[current.id] ?? current.tabs[0][0];
  const go = (section: string, t?: string) => {
    setSettingsOpen(false);
    setMenuOpen(false);
    setView((v) => ({ section, tabs: t ? { ...v.tabs, [section]: t } : v.tabs }));
  };

  async function signOut() {
    await api.logout().catch(() => {});
    setMe(false);
  }

  return (
    <div className={`shell${help ? ' with-help' : ''}`}>
      <header className="topbar">
        <span className="brand" title={version ? `${appName} ${version}` : appName}>{appName}</span>
        <nav className="nav" role="tablist" data-help="app.sections">
          {sections.map((s) => (
            <button key={s.id} role="tab" aria-selected={!settingsOpen && s.id === current.id}
                    className={`nav-btn${!settingsOpen && s.id === current.id ? ' active' : ''}`}
                    data-help={s.helpId} onClick={() => go(s.id)}>{s.title}</button>
          ))}
        </nav>
        <span className="appbar-spacer" />
        <a className="ghost-btn sm" href="/fm/" data-help="app.familyPage" title="The family's phone page">
          <span className="wide-only">Family page</span><span className="narrow-only">/fm</span> ↗</a>
        <button className="ghost-btn sm icon" data-help="app.help" title="Help (Alt + click any control)"
                onClick={() => openHelp(null)}>?</button>
        {me.role === 'admin' && (
          <button className={`ghost-btn sm${settingsOpen ? ' on' : ''}`} data-help="app.settings"
                  onClick={() => { setSettingsOpen(!settingsOpen); setMenuOpen(false); }}>Settings</button>
        )}
        <span className="account" data-help="app.account">
          <button className="ghost-btn sm" onClick={() => setMenuOpen(!menuOpen)} aria-expanded={menuOpen}>
            {me.username} ▾
          </button>
          {menuOpen && (
            <div className="account-menu" role="menu">
              <div className="account-who">{me.username} · {me.role}</div>
              <PasswordForm uid={me.id} onDone={() => setMenuOpen(false)} />
              <button className="ghost-btn sm" onClick={() => void signOut()}>Sign out</button>
            </div>
          )}
        </span>
      </header>
      {!settingsOpen && current.tabs.length > 1 && (
        <nav className="subnav" role="tablist">
          {current.tabs.map(([t, label]) => (
            <button key={t} role="tab" aria-selected={t === tab}
                    className={`subnav-btn${t === tab ? ' active' : ''}`} onClick={() => go(current.id, t)}>{label}</button>
          ))}
        </nav>
      )}
      <main className="main">
        {settingsOpen && me.role === 'admin'
          ? <SettingsPage me={me} />
          : current.render(tab, (t) => go(current.id, t))}
      </main>
      {help && <HelpPanel requestedId={help.id} requestedLabel={help.label} requestKey={help.key}
                          onClose={() => setHelp(null)} />}
    </div>
  );
}

function PasswordForm({ uid, onDone }: { uid: number; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [pw, setPw] = useState('');
  const [error, setError] = useState<string | null>(null);
  if (!open) return <button className="ghost-btn sm" onClick={() => setOpen(true)}>Change password</button>;
  return (
    <div className="account-pw">
      <input type="password" placeholder="New password (10+)" value={pw} autoFocus
             onChange={(e) => setPw(e.target.value)} />
      <button className="ghost-btn sm" disabled={pw.length < 10} onClick={async () => {
        try { await api.setPassword(uid, pw); setOpen(false); setPw(''); onDone(); }
        catch (e) { setError((e as Error).message); }
      }}>Set</button>
      {error && <span className="fma-error">{error}</span>}
    </div>
  );
}
