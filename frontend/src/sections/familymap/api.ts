import type {
  FmCategories, FmImportState, FmPlace, FmReview, FmSettings, FmStats, FmUser,
} from './phone/types';

/** The FamilyMap admin section's API (2.43.0). Reads go through the same
    /api/fm endpoints the family's page uses; changes to places and the
    family accounts go through the admin-only /api/familymap ones. */
async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { const b = await res.json(); if (b?.detail) detail = String(b.detail); } catch { /* */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}
const send = (method: string, body: unknown) => ({
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
});

export const fmAdmin = {
  categories: () => fetch('/api/fm/categories').then(json<FmCategories>),
  stats: () => fetch('/api/familymap/stats').then(json<FmStats>),
  places: (q: string, category: string, reviewed: string) => {
    const p = new URLSearchParams();
    if (q.trim()) p.set('q', q.trim());
    if (category) p.set('category', category);
    if (reviewed) p.set('reviewed', reviewed);
    return fetch(`/api/fm/places?${p}`).then(json<FmPlace[]>);
  },
  place: (id: number) => fetch(`/api/fm/places/${id}`).then(json<FmPlace>),
  createPlace: (body: Partial<FmPlace>) =>
    fetch('/api/fm/places', send('POST', body)).then(json<FmPlace>),
  updatePlace: (id: number, body: Partial<FmPlace>) =>
    fetch(`/api/familymap/places/${id}`, send('PUT', body)).then(json<FmPlace>),
  deletePlace: (id: number) =>
    fetch(`/api/familymap/places/${id}`, { method: 'DELETE' }).then(json<{ ok: boolean }>),
  reviews: () => fetch('/api/familymap/reviews').then(json<FmReview[]>),
  deleteReview: (id: number) =>
    fetch(`/api/fm/reviews/${id}`, { method: 'DELETE' }).then(json<{ ok: boolean }>),
  deletePhoto: (id: number) =>
    fetch(`/api/fm/photos/${id}`, { method: 'DELETE' }).then(json<{ ok: boolean }>),
  users: () => fetch('/api/familymap/users').then(json<FmUser[]>),
  createUser: (username: string, password: string) =>
    fetch('/api/familymap/users', send('POST', { username, password })).then(json<FmUser>),
  // Password, sign-out and delete are the app's own account endpoints.
  setPassword: (id: number, password: string) =>
    fetch(`/api/users/${id}/password`, send('PATCH', { password })).then(json<{ ok: boolean }>),
  signOut: (id: number) =>
    fetch(`/api/users/${id}/sign-out`, { method: 'POST' }).then(json<{ ok: boolean }>),
  deleteUser: (id: number) =>
    fetch(`/api/users/${id}`, { method: 'DELETE' }).then(json<{ ok: boolean }>),

  // 2.44.0: FamilyMap's own settings, the OSM import, photo descriptions.
  settings: () => fetch('/api/familymap/settings').then(json<FmSettings>),
  setSetting: (key: keyof FmSettings, value: string) =>
    fetch('/api/familymap/settings', send('PUT', { [key]: value })).then(json<FmSettings>),
  models: () => fetch('/api/ollama/models').then(json<string[]>),
  roles: () => fetch('/api/roles').then(json<{ chat: string; vision: string; categorise: string }>),
  importState: () => fetch('/api/familymap/import').then(json<FmImportState>),
  startImport: (categories?: string[]) =>
    fetch('/api/familymap/import', send('POST', { categories: categories ?? null }))
      .then(json<FmImportState>),
  stopImport: () => fetch('/api/familymap/import/stop', { method: 'POST' }).then(json<FmImportState>),
  describeWaiting: () =>
    fetch('/api/familymap/describe', { method: 'POST' }).then(json<{ queued: number; nomodel: number }>),
};
