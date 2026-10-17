import type {
  AuthStatus, AuthUser, ComfyTest, Diagnostics, HelpDto, Meta, OllamaTest, SettingsDto,
  SettingsPatch, UserDto,
} from './types';

/** The shell's API: accounts, settings, help. A failed call throws an Error
    carrying the backend's `detail`, so the page can show why. */
async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { const b = await res.json(); if (b?.detail) detail = String(b.detail); } catch { /* */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}
const send = (method: string, body?: unknown): RequestInit => ({
  method, headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  meta: () => fetch('/api/meta').then(json<Meta>),
  authStatus: () => fetch('/api/auth/status').then(json<AuthStatus>),
  login: (username: string, password: string) =>
    fetch('/api/auth/login', send('POST', { username, password })).then(json<{ user: AuthUser }>),
  setupAdmin: (username: string, password: string) =>
    fetch('/api/auth/setup', send('POST', { username, password })).then(json<{ user: AuthUser }>),
  logout: () => fetch('/api/auth/logout', { method: 'POST' }).then(json<{ ok: boolean }>),

  getHelp: () => fetch('/api/help').then(json<HelpDto>),
  listOllamaModels: () => fetch('/api/ollama/models').then(json<string[]>),
  roles: () => fetch('/api/roles').then(json<{ chat: string; vision: string; categorise: string }>),

  getSettings: () => fetch('/api/settings').then(json<SettingsDto>),
  saveSettings: (patch: SettingsPatch) => fetch('/api/settings', send('PUT', patch)).then(json<SettingsDto>),
  testOllama: (url: string) => fetch('/api/settings/test-ollama', send('POST', { url })).then(json<OllamaTest>),
  testComfy: (url: string) => fetch('/api/settings/test-comfy', send('POST', { url })).then(json<ComfyTest>),
  diagnostics: () => fetch('/api/diagnostics').then(json<Diagnostics>),
  clearRecent: () => fetch('/api/diagnostics/recent', { method: 'DELETE' }).then(json<{ ok: boolean }>),

  users: () => fetch('/api/users').then(json<UserDto[]>),
  createUser: (username: string, password: string, role: 'user' | 'family') =>
    fetch('/api/users', send('POST', { username, password, role })).then(json<UserDto>),
  setPassword: (id: number, password: string) =>
    fetch(`/api/users/${id}/password`, send('PATCH', { password })).then(json<{ ok: boolean }>),
  signOut: (id: number) => fetch(`/api/users/${id}/sign-out`, { method: 'POST' }).then(json<{ ok: boolean }>),
  deleteUser: (id: number) => fetch(`/api/users/${id}`, { method: 'DELETE' }).then(json<{ ok: boolean }>),
};
