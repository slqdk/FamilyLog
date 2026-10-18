import type { FmUser } from '../sections/familymap/phone/types';

/** The front page's API (FamilyLog 0.2.0; Økonomi and Cyklus 0.3.0). Errors carry the backend's
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

export type FieldKind = 'scale' | 'count' | 'slider' | 'tags' | 'foods' | 'sick' | 'private';
export interface DagbogField {
  key: string; kind: FieldKind; label: string; hint?: string;
  low?: string; high?: string; faces?: string[]; unit?: string; max?: number;
  min?: number; step?: number; format?: 'hours'; options?: string[];
}
export interface DagbogConfig { fields: DagbogField[]; tags: string[]; foods: string[]; today: string; maxDaysBack: number }
export interface DagbogEntry {
  userId: number; day: string;
  mood: number | null; mental: number | null; alcohol: number | null;
  exercise?: number | null; soda?: number | null; sick?: string[]; sickNote?: string;
  foods: string[]; tags: string[]; updatedAt: string;
  /** the author's own entry, or a day its author shares with the family (0.3.9) */
  highlight?: string; hasPhoto?: boolean;
  /** only on the author's own entry: the text and photo are shared with the family */
  shared?: boolean;
}
export interface DagbogPerson {
  person: { id: number; username: string }; own: boolean; fields: string[];
  entries: DagbogEntry[]; more: boolean; firstDay: string | null; total: number;
}
export interface DagbogCount { name: string; days: number }
export interface DagbogStats {
  person: { id: number; username: string }; from: string | null; to: string | null; days: number; fields: string[];
  span?: number; coverage?: number; mood?: number | null; mental?: number | null;
  exerciseHoursPerWeek?: number; alcoholPerWeek?: number; sodaPerWeek?: number; sickDays?: number; bestStreak?: number;
  months?: { month: string; days: number; mood: number | null; mental: number | null; exerciseHours: number; alcohol: number }[];
  weekdays?: (number | null)[];
  topTags?: DagbogCount[]; topFoods?: DagbogCount[]; topSick?: DagbogCount[];
  links?: { label: string; kind: string; with: number; without: number; diff: number; days: number }[];
}
export interface DagbogFamily {
  from: string; to: string;
  members: { id: number; username: string; fields: string[] }[];
  entries: DagbogEntry[];
}

// ---- Økonomi on the phone (0.3.0) ----
export interface OkTx { date: string; merchant: string; text: string; amount: number; category: string;
  categoryName: string; merchantKey: string }
export interface OkAsk {
  question: string; state: 'queued' | 'working' | 'done' | 'failed' | 'stopped'; step: string; text: string;
  error: string | null; counted: string | null; count: number | null; total: number | null; rows: OkTx[];
  ahead?: number | null;
}
export type OkState = { access: false } | {
  access: true; own: boolean; owner: string; count: number; firstDate: string | null; lastDate: string | null;
  uncategorised: number; months: string[]; accounts: string[]; model: boolean; ask: OkAsk | null;
};
export interface OkData {
  imports: { id: number; account: string; filename: string; importedAt: string; added: number; firstDate: string | null; lastDate: string | null }[];
  accounts: { account: string; n: number; first: string; last: string }[];
  count: number; left: number; model: boolean;
  uncategorised: { key: string; name: string; sample: string; count: number; total: number }[];
  categorise: { state: string; left: number; placed?: number; error?: string | null; ahead?: number | null };
  categories: { key: string; name: string; group?: string }[];
}
export interface OkOverview {
  from: string | null; to: string | null; account: string | null; isMonth: boolean;
  count: number; spent: number; income: number; otherIn: number; transfersOut: number;
  perMonth: number; months: number;
  baselinePerMonth: number | null; baselineMonths: number | null;
  days: { date: string; spent: number }[] | null;
  categories: { key: string; name: string; spent: number; count: number; usual: number | null }[];
  topMerchants: { key: string; name: string; spent: number; count: number; category: string; categoryName: string }[];
  recurring: { key: string; name: string; typical: number; yearly: number; category: string; categoryName: string }[];
}
export type OkMonth = OkOverview & { month: string };
export interface OkTxQuery {
  frm?: string; to?: string; account?: string; category?: string; merchant?: string; q?: string;
  direction?: '' | 'in' | 'out'; order?: 'newest' | 'oldest' | 'largest' | 'smallest' | 'income'; offset?: number;
}
export interface OkMerchant {
  key: string; name: string; category: string; categoryName: string; source: string; sample: string;
  count: number; total: number; last: string | null;
}
export interface OkTrend {
  months: { month: string; spent: number; income: number; byCategory: Record<string, number> }[];
  categories: { key: string; name: string; spent: number }[];
}

// ---- Cyklus (0.3.0) ----
export type DayKind = '' | 'period' | 'predicted' | 'possible' | 'fertile' | 'ovulation' | 'pms';
export type Phase = 'menstruation' | 'follicular' | 'fertile' | 'ovulation' | 'luteal' | 'pms' | 'mid';
export interface CyStatus {
  empty: boolean; today: string; stale?: boolean;
  averages: { cycle: number; cycleSource: string; period: number; cyclesMeasured: number;
    spread: number | null; regular: boolean | null; history: number[] };
  lastStart?: string; lastOpen?: boolean; cycleDay?: number; phase?: Phase; phaseLabel?: string;
  phaseText?: string; inPeriod?: boolean; periodDay?: number | null; nextStart?: string;
  daysUntilNext?: number; late?: number; ovulation?: string; fertileFrom?: string; fertileTo?: string;
  fertileToday?: boolean; daysUntilFertile?: number; askEnded?: boolean;
}
export interface CyDay { day: string; flow: string; symptoms: string[]; moods: string[]; note: string }
export interface CyPattern { label: string; days: number; top: { name: string; count: number }[];
  mood: number | null; mental: number | null }
export interface CyPeriod { id: number; start: string; end: string | null; periodDays: number | null;
  cycleLength: number | null }
export interface CySettings { cycleLength: number | null; periodLength: number | null;
  shareFertile: boolean; shareDetails: boolean; viewers: number[] }
export interface CyOwn {
  status: CyStatus; forecast: { day: string; kind: DayKind }[]; patterns: Partial<Record<Phase, CyPattern>>;
  periods: CyPeriod[]; settings: CySettings; today: CyDay;
}
export interface CyShared {
  id: number; name: string; today: string; empty: boolean; stale?: boolean; shareFertile: boolean; shareDetails: boolean;
  cycleDay?: number; phase?: Phase; phaseLabel?: string; phaseText?: string; inPeriod?: boolean;
  periodDay?: number | null; nextStart?: string; daysUntilNext?: number; late?: number;
  fertileFrom?: string; fertileTo?: string; ovulation?: string; fertileToday?: boolean;
  week?: { day: string; kind: DayKind }[];
  todayLog?: { flow: string; symptoms: string[]; moods: string[] }; pattern?: CyPattern | null;
  forecast?: CyForecast;
}
export interface CyForecast {
  items: { key: string; label: string; value: number; source: 'typisk' | 'dig' | 'dagbog' }[];
  expect: string[]; expectSource: 'typisk' | 'dig'; behaviour: string;
}
export interface CyDayInfo {
  day: string; past: boolean; isToday: boolean; kind: DayKind; cycleDay: number | null; phase: Phase | null;
  title: string; sub?: string; phaseLabel?: string; text: string; chance?: 'lav' | 'middel' | 'høj' | null;
  chanceLabel?: string; nextPeriodIn?: number | null; forecast?: CyForecast; log: CyDay | null;
}
/** A day as she shares it: no log, no note; chance only with the fertile days. */
export type CySharedDay = Omit<CyDayInfo, 'past' | 'log'>;
export interface CyCalDay { day: string; kind: DayKind; cycleDay: number | null; flow: string; logged: boolean }
export interface CyOptions { flows: { key: string; label: string }[]; symptoms: string[]; moods: string[];
  disclaimer: string; phases: Record<string, string> }
export interface CyState { enabled: boolean; shared: CyShared[]; options: CyOptions; own?: CyOwn }

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
  person: (user: number, before: string | null, limit = 20) =>
    fetch(`/api/dagbog/person?user=${user}&limit=${limit}${before ? `&before=${before}` : ''}`).then(json<DagbogPerson>),
  personMonth: (user: number, month: string) =>
    fetch(`/api/dagbog/person/month?user=${user}&month=${month}`)
      .then(json<{ month: string; days: Record<string, number | null> }>),
  dagbogStats: (user: number, frm: string) =>
    fetch(`/api/dagbog/stats?user=${user}${frm ? `&frm=${frm}` : ''}`).then(json<DagbogStats>),
  mine: (frm: string, to: string) => fetch(`/api/dagbog/mine?frm=${frm}&to=${to}`).then(json<{ days: string[] }>),
  uploadPhoto: (day: string, file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return fetch(`/api/dagbog/photo?day=${day}`, { method: 'POST', body: fd }).then(json<{ entry: DagbogEntry }>);
  },
  deletePhoto: (day: string) => fetch(`/api/dagbog/photo?day=${day}`, { method: 'DELETE' })
    .then(json<{ entry: DagbogEntry }>),
  okState: () => fetch('/api/okonomi/state').then(json<OkState>),
  okMonth: (month: string) => fetch(`/api/okonomi/month?month=${month}`).then(json<OkMonth>),
  okOverview: (frm: string, to: string, account: string) =>
    fetch(`/api/okonomi/overview?${new URLSearchParams({ frm, to, account })}`).then(json<OkOverview>),
  okTx: (query: OkTxQuery) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== '' && v !== null) q.set(k, String(v));
    if (query.category === '') q.set('category', '');
    return fetch(`/api/okonomi/transactions?${q}`).then(json<{ total: number; sum: number; rows: OkTx[] }>);
  },
  okMerchants: (search: string, category: string) =>
    fetch(`/api/okonomi/merchants?${new URLSearchParams({ q: search, category })}`)
      .then(json<{ merchants: OkMerchant[]; categories: { key: string; name: string; group?: string }[] }>),
  okSetMerchant: (key: string, change: { category?: string; name?: string }) =>
    fetch('/api/okonomi/merchant', send('PUT', { key, ...change })).then(json<{ ok: boolean }>),
  okTrend: (months: number, account: string) =>
    fetch(`/api/okonomi/trend?${new URLSearchParams({ months: String(months), account })}`).then(json<OkTrend>),
  okData: () => fetch('/api/okonomi/data').then(json<OkData>),
  okImport: (file: File, account: string) => {
    const fd = new FormData();
    fd.append('file', file);
    return fetch(`/api/okonomi/import?account=${encodeURIComponent(account)}`, { method: 'POST', body: fd })
      .then(json<{ added: number; alreadyThere: number; rowsInFile: number; uncategorised: number; skipped: number }>);
  },
  okDeleteImport: (id: number) => fetch(`/api/okonomi/imports/${id}`, { method: 'DELETE' }).then(json<{ removed: number }>),
  okSetCategory: (key: string, category: string) =>
    fetch('/api/okonomi/merchant', send('PUT', { key, category })).then(json<{ ok: boolean }>),
  okCategorise: () => fetch('/api/okonomi/categorise', { method: 'POST' }).then(json<OkData>),
  okAsk: (question: string) => fetch('/api/okonomi/ask', send('POST', { question })).then(json<{ ask: OkAsk | null }>),
  okAskState: () => fetch('/api/okonomi/ask').then(json<{ ask: OkAsk | null }>),
  okAskStop: () => fetch('/api/okonomi/ask/stop', { method: 'POST' }).then(json<{ ask: OkAsk | null }>),

  cyState: () => fetch('/api/cyklus/state').then(json<CyState>),
  cyCalendar: (frm: string, to: string) =>
    fetch(`/api/cyklus/calendar?frm=${frm}&to=${to}`).then(json<{ days: CyCalDay[] }>),
  cySharedCalendar: (owner: number, frm: string, to: string) =>
    fetch(`/api/cyklus/shared/calendar?owner=${owner}&frm=${frm}&to=${to}`).then(json<{ days: { day: string; kind: DayKind }[] }>),
  cySharedDay: (owner: number, day: string) =>
    fetch(`/api/cyklus/shared/day?owner=${owner}&day=${day}`).then(json<CySharedDay>),
  cyDayInfo: (day: string) => fetch(`/api/cyklus/dayinfo?day=${day}`).then(json<CyDayInfo>),
  cyToggle: (day: string) => fetch('/api/cyklus/period/toggle', send('POST', { day })).then(json<CyOwn>),
  cyDay: (day: string) => fetch(`/api/cyklus/day?day=${day}`).then(json<{ day: CyDay }>),
  cySaveDay: (d: Omit<CyDay, 'note'> & { note?: string }) => fetch('/api/cyklus/day', send('PUT', d)).then(json<CyOwn>),
  cyStart: (day: string) => fetch('/api/cyklus/period/start', send('POST', { day })).then(json<CyOwn>),
  cyEnd: (day: string) => fetch('/api/cyklus/period/end', send('POST', { day })).then(json<CyOwn>),
  cyEditPeriod: (id: number, start: string, end: string | null) =>
    fetch(`/api/cyklus/period/${id}`, send('PUT', { start, end })).then(json<CyOwn>),
  cyDeletePeriod: (id: number) => fetch(`/api/cyklus/period/${id}`, { method: 'DELETE' }).then(json<CyOwn>),
  cySettings: () => fetch('/api/cyklus/settings').then(json<{ settings: CySettings; candidates: { id: number; username: string; gender: string }[] }>),
  cySaveSettings: (s: Partial<CySettings>) => fetch('/api/cyklus/settings', send('PUT', s))
    .then(json<{ settings: CySettings; candidates: { id: number; username: string; gender: string }[] }>),

  photoUrl: (day: string, v: string, user?: number) =>
    `/api/dagbog/photo?day=${day}${user ? `&user=${user}` : ''}&v=${encodeURIComponent(v)}`,
};
