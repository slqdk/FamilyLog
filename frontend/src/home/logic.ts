/** Pure helpers for the front page (tested in logic.test.ts). */

export type HomeRoute =
  | { name: 'home' }
  | { name: 'dagbog'; day: string | null }
  | { name: 'family'; week: string | null }
  | { name: 'okonomi'; month: string | null }
  | { name: 'cyklus' }
  | { name: 'cyklusDay'; day: string }
  | { name: 'cyklusCal'; month: string | null }
  | { name: 'cyklusShare' };

/** #/ · #/dagbog · #/dagbog/2026-10-17 · #/dagbog/familien[/2026-10-12]
    · #/okonomi[/2026-10] · #/cyklus · #/cyklus/dag/2026-10-17
    · #/cyklus/kalender[/2026-10] · #/cyklus/deling */
export function parseRoute(hash: string): HomeRoute {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  const isDay = (s: string | undefined) => !!s && /^\d{4}-\d{2}-\d{2}$/.test(s);
  const isMonth = (s: string | undefined) => !!s && /^\d{4}-(0[1-9]|1[0-2])$/.test(s);
  if (parts[0] === 'okonomi') return { name: 'okonomi', month: isMonth(parts[1]) ? parts[1] : null };
  if (parts[0] === 'cyklus') {
    if (parts[1] === 'dag' && isDay(parts[2])) return { name: 'cyklusDay', day: parts[2] };
    if (parts[1] === 'kalender') return { name: 'cyklusCal', month: isMonth(parts[2]) ? parts[2] : null };
    if (parts[1] === 'deling') return { name: 'cyklusShare' };
    return { name: 'cyklus' };
  }
  if (parts[0] === 'dagbog') {
    if (parts[1] === 'familien') return { name: 'family', week: isDay(parts[2]) ? parts[2] : null };
    return { name: 'dagbog', day: isDay(parts[1]) ? parts[1] : null };
  }
  return { name: 'home' };
}

export function routeHash(r: HomeRoute): string {
  switch (r.name) {
    case 'home': return '#/';
    case 'dagbog': return r.day ? `#/dagbog/${r.day}` : '#/dagbog';
    case 'family': return r.week ? `#/dagbog/familien/${r.week}` : '#/dagbog/familien';
    case 'okonomi': return r.month ? `#/okonomi/${r.month}` : '#/okonomi';
    case 'cyklus': return '#/cyklus';
    case 'cyklusDay': return `#/cyklus/dag/${r.day}`;
    case 'cyklusCal': return r.month ? `#/cyklus/kalender/${r.month}` : '#/cyklus/kalender';
    case 'cyklusShare': return '#/cyklus/deling';
  }
}

/** "2026-10-17" + n days, in local time (no time zone surprises at midnight). */
export function addDays(day: string, n: number): string {
  const [y, m, d] = day.split('-').map(Number);
  const t = new Date(y, m - 1, d + n);
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`;
}

export function todayLocal(now = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

/** Monday of the week the day is in. */
export function weekStart(day: string): string {
  const [y, m, d] = day.split('-').map(Number);
  const wd = (new Date(y, m - 1, d).getDay() + 6) % 7;      // Monday = 0
  return addDays(day, -wd);
}

const DAYS = ['søndag', 'mandag', 'tirsdag', 'onsdag', 'torsdag', 'fredag', 'lørdag'];
const SHORT = ['sø', 'ma', 'ti', 'on', 'to', 'fr', 'lø'];
const MONTHS = ['jan', 'feb', 'mar', 'apr', 'maj', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'dec'];

function parts(day: string) {
  const [y, m, d] = day.split('-').map(Number);
  return { wd: new Date(y, m - 1, d).getDay(), d, m };
}

/** "I dag" / "I går" / "torsdag 15. okt" */
export function dayTitle(day: string, today: string): string {
  if (day === today) return 'I dag';
  if (day === addDays(today, -1)) return 'I går';
  const p = parts(day);
  const name = DAYS[p.wd];
  return `${name[0].toUpperCase()}${name.slice(1)} ${p.d}. ${MONTHS[p.m - 1]}`;
}

/** "ma 12" for a column head */
export function shortDay(day: string): string {
  const p = parts(day);
  return `${SHORT[p.wd]} ${p.d}`;
}

export function hello(now = new Date()): string {
  const h = now.getHours();
  return h < 5 ? 'Godnat' : h < 10 ? 'Godmorgen' : h < 18 ? 'Hej' : 'Godaften';
}

/** The mean of the given values, ignoring empty ones; null when none. */
export function mean(values: (number | null | undefined)[]): number | null {
  const v = values.filter((x): x is number => typeof x === 'number');
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

export const FACES = ['😞', '🙁', '😐', '🙂', '😄'];

export function face(mood: number | null | undefined): string {
  return mood ? FACES[Math.min(5, Math.max(1, Math.round(mood))) - 1] : '·';
}

const MONTH_NAMES = ['januar', 'februar', 'marts', 'april', 'maj', 'juni', 'juli', 'august',
  'september', 'oktober', 'november', 'december'];

/** "2026-10" -> "Oktober 2026" */
export function monthTitle(month: string): string {
  const name = MONTH_NAMES[Number(month.slice(5, 7)) - 1];
  return `${name[0].toUpperCase()}${name.slice(1)} ${month.slice(0, 4)}`;
}

/** "2026-10" + n months */
export function addMonths(month: string, n: number): string {
  const k = Number(month.slice(0, 4)) * 12 + Number(month.slice(5, 7)) - 1 + n;
  return `${Math.floor(k / 12)}-${String((k % 12) + 1).padStart(2, '0')}`;
}

/** "17. okt" */
export function shortDate(day: string): string {
  const p = parts(day);
  return `${p.d}. ${MONTHS[p.m - 1]}`;
}

/** Whole days from a to b (b - a), in local dates. */
export function daysBetween(a: string, b: string): number {
  const [y1, m1, d1] = a.split('-').map(Number);
  const [y2, m2, d2] = b.split('-').map(Number);
  return Math.round((Date.UTC(y2, m2 - 1, d2) - Date.UTC(y1, m1 - 1, d1)) / 86400000);
}

const KR = new Intl.NumberFormat('da-DK', { maximumFractionDigits: 0 });
const KR2 = new Intl.NumberFormat('da-DK', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** 12345.6 -> "12.346 kr" (whole kroner); exact=true keeps øre. */
export function kr(x: number, exact = false): string {
  return `${(exact ? KR2 : KR).format(x)} kr`;
}

/** Days of a month, Monday-first grid with nulls before the 1st. */
export function monthGrid(month: string): (string | null)[] {
  const first = `${month}-01`;
  const lead = (parts(first).wd + 6) % 7;
  const n = new Date(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 0).getDate();
  const out: (string | null)[] = Array.from({ length: lead }, () => null);
  for (let i = 0; i < n; i++) out.push(addDays(first, i));
  return out;
}

export function weekdayLetter(day: string): string {
  return ['S', 'M', 'T', 'O', 'T', 'F', 'L'][parts(day).wd];
}

export function dayOfMonth(day: string): number {
  return parts(day).d;
}
