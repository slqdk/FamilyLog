/** Pure helpers for the front page (tested in logic.test.ts). */

export type HomeRoute =
  | { name: 'home' }
  | { name: 'dagbog'; day: string | null }
  | { name: 'family'; week: string | null };

/** #/ · #/dagbog · #/dagbog/2026-10-17 · #/dagbog/familien[/2026-10-12] */
export function parseRoute(hash: string): HomeRoute {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  const isDay = (s: string | undefined) => !!s && /^\d{4}-\d{2}-\d{2}$/.test(s);
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
