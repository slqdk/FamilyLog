import type { FmUser } from '../sections/familymap/phone/types';

/** The front page's API (FamilyLog 0.2.0). Errors carry the backend's
    Danish `detail`, shown to the person as it is. */
async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.status === 401 ? 'Du er ikke logget ind.' : `Serveren svarede ${res.status}.`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch { /* not JSON */ }
    const err = new Error(detail) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return res.json() as Promise<T>;
}
const send = (method: string, body?: unknown): RequestInit => ({
  method, headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export interface PlaceCard {
  id: number; name: string; category: string; address: string | null;
  familyScore: number | null; reviewCount: number; coverPhotoId: number | null;
  distanceKm: number | null; source: string; wished: boolean; latestText: string | null;
}
export interface ChatMessage {
  id: number; role: 'user' | 'assistant'; content: string; places: PlaceCard[];
  createdAt: string; meta: { route?: string; searched?: string | null; where?: string | null; stopped?: boolean };
}
export interface ChatJob {
  state: 'queued' | 'working' | 'done' | 'failed' | 'stopped';
  step: string; phase: string; text: string; places: PlaceCard[]; error: string | null;
  route: 'places' | 'chat' | null; searched: string | null; where: string | null; ahead?: number;
}
export interface ChatState { messages: ChatMessage[]; job: ChatJob | null; model: boolean }

export type FieldKind = 'scale' | 'count' | 'tags' | 'foods' | 'private';
export interface DagbogField {
  key: string; kind: FieldKind; label: string; hint?: string;
  low?: string; high?: string; faces?: string[]; unit?: string; max?: number;
}
export interface DagbogConfig { fields: DagbogField[]; tags: string[]; foods: string[]; today: string; maxDaysBack: number }
export interface DagbogEntry {
  userId: number; day: string;
  mood: number | null; mental: number | null; alcohol: number | null;
  foods: string[]; tags: string[]; updatedAt: string;
  /** only on the author's own entry */
  highlight?: string; hasPhoto?: boolean;
}
export interface DagbogFamily {
  from: string; to: string;
  members: { id: number; username: string; fields: string[] }[];
  entries: DagbogEntry[];
}

export const homeApi = {
  status: () => fetch('/api/auth/status').then(json<{ user: FmUser | null; needsSetup: boolean }>),
  login: (username: string, password: string) =>
    fetch('/api/auth/login', send('POST', { username, password })).then(json<{ user: FmUser }>),
  logout: () => fetch('/api/auth/logout', { method: 'POST' }).then(json<{ ok: boolean }>),
  meta: () => fetch('/api/meta').then(json<{ name: string; version: string }>),
  atlasName: () => fetch('/api/fm/brand').then(json<{ name: string }>),

  chat: () => fetch('/api/chat/state').then(json<ChatState>),
  chatSend: (message: string, pos: { lat: number; lng: number } | null) =>
    fetch('/api/chat/send', send('POST', { message, ...(pos ?? {}) })).then(json<ChatState>),
  chatStop: () => fetch('/api/chat/stop', { method: 'POST' }).then(json<ChatState>),
  chatNew: () => fetch('/api/chat/new', { method: 'POST' }).then(json<ChatState>),

  dagbogConfig: () => fetch('/api/dagbog/config').then(json<DagbogConfig>),
  entry: (day: string) => fetch(`/api/dagbog/entry?day=${day}`).then(json<{ entry: DagbogEntry | null }>),
  saveEntry: (body: Partial<DagbogEntry> & { day: string }) =>
    fetch('/api/dagbog/entry', send('PUT', body)).then(json<{ entry: DagbogEntry }>),
  deleteEntry: (day: string) => fetch(`/api/dagbog/entry?day=${day}`, { method: 'DELETE' }).then(json<{ ok: boolean }>),
  family: (frm: string, to: string) => fetch(`/api/dagbog/family?frm=${frm}&to=${to}`).then(json<DagbogFamily>),
  mine: (frm: string, to: string) => fetch(`/api/dagbog/mine?frm=${frm}&to=${to}`).then(json<{ days: string[] }>),
  uploadPhoto: (day: string, file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return fetch(`/api/dagbog/photo?day=${day}`, { method: 'POST', body: fd }).then(json<{ entry: DagbogEntry }>);
  },
  deletePhoto: (day: string) => fetch(`/api/dagbog/photo?day=${day}`, { method: 'DELETE' })
    .then(json<{ entry: DagbogEntry }>),
  photoUrl: (day: string, v: string) => `/api/dagbog/photo?day=${day}&v=${encodeURIComponent(v)}`,
};
