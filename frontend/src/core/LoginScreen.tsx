import { useState } from 'react';
import { api } from './api';
import type { AuthUser } from './types';

/**
 * Shown whenever nobody is signed in. Doubles as the first-run screen: with
 * no accounts yet it creates the administrator, so no default password is
 * ever shipped. (From SLQ's LoginScreen.)
 */
export function LoginScreen({ appName, needsSetup, onSignedIn }: {
  appName: string;
  needsSetup: boolean;
  onSignedIn: (user: AuthUser) => void;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setError(null);
    if (!username.trim() || !password) { setError('Enter a username and password.'); return; }
    if (needsSetup && password !== confirm) { setError('The two passwords do not match.'); return; }
    setBusy(true);
    try {
      const { user } = needsSetup
        ? await api.setupAdmin(username.trim(), password)
        : await api.login(username.trim(), password);
      onSignedIn(user);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Sign-in failed.');
    } finally {
      setBusy(false);
    }
  }

  const insecure = location.protocol === 'http:'
    && !['localhost', '127.0.0.1'].includes(location.hostname);
  const enter = (e: React.KeyboardEvent) => { if (e.key === 'Enter') void submit(); };

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <h1 className="login-title">{appName}</h1>
        <p className="login-lead">
          {needsSetup
            ? 'First run - create the administrator account. Only this account can change the settings and add other accounts.'
            : 'Sign in to continue.'}
        </p>
        {insecure && (
          <p className="login-warn">
            This page is not using HTTPS, so your password is sent unencrypted. Use the
            address behind the proxy (https://) instead.
          </p>
        )}
        <label className="field">
          <span>Username</span>
          <input autoFocus value={username} autoComplete="username" name="username"
                 onChange={(e) => setUsername(e.target.value)} onKeyDown={enter} />
        </label>
        <label className="field">
          <span>Password</span>
          <input type="password" value={password} name="password"
                 autoComplete={needsSetup ? 'new-password' : 'current-password'}
                 onChange={(e) => setPassword(e.target.value)} onKeyDown={enter} />
          {needsSetup && <small>At least 10 characters. A short phrase works well.</small>}
        </label>
        {needsSetup && (
          <label className="field">
            <span>Confirm password</span>
            <input type="password" value={confirm} autoComplete="new-password" name="confirm"
                   onChange={(e) => setConfirm(e.target.value)} onKeyDown={enter} />
          </label>
        )}
        {error && <p className="login-error" role="alert">{error}</p>}
        <button type="submit" className="primary-btn login-btn" disabled={busy}>
          {busy ? 'Working…' : needsSetup ? 'Create administrator' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
