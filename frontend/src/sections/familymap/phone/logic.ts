import type { FmCategory, FmField, FmFieldValue, FmReview, FmReviewBody } from './types';

/** The family page's routes live in the hash, so the phone's back button
    walks back through them and a reload keeps the page you were on. */
export type FmRoute =
  | { name: 'list' }
  | { name: 'place'; id: number }
  | { name: 'review'; placeId: number; reviewId: number | null }
  | { name: 'newPlace'; lat?: number; lng?: number }
  // The map "Tilføj et sted" opens (2.47.0).
  | { name: 'map' }
  // The burger menu's pages (2.45.0).
  | { name: 'myReviews' }
  | { name: 'myPhotos' }
  | { name: 'wishlist' }
  // The family's own places, and correcting one (2.49.5).
  | { name: 'myPlaces' }
  | { name: 'editPlace'; id: number }
  // Spørg Alf (2.46.0).
  | { name: 'ask' };

const MENU_ROUTES = { 'mine-steder': 'myPlaces', 'mine-anmeldelser': 'myReviews', 'mine-billeder': 'myPhotos',
                      'oenskeliste': 'wishlist' } as const;

export function parseRoute(hash: string): FmRoute {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  const num = (s: string | undefined) => (s && /^\d+$/.test(s) ? Number(s) : null);
  if (parts[0] === 'nyt-sted') {
    // A tap on the map passes its point along: #/nyt-sted/55.24612/9.30601
    const lat = Number(parts[1]), lng = Number(parts[2]);
    if (parts.length === 3 && Number.isFinite(lat) && Number.isFinite(lng)
        && Math.abs(lat) <= 90 && Math.abs(lng) <= 180) return { name: 'newPlace', lat, lng };
    return { name: 'newPlace' };
  }
  if (parts[0] === 'kort') return { name: 'map' };
  if (parts[0] === 'spoerg-alf') return { name: 'ask' };
  if (parts[0] in MENU_ROUTES) return { name: MENU_ROUTES[parts[0] as keyof typeof MENU_ROUTES] };
  if (parts[0] === 'sted') {
    const id = num(parts[1]);
    if (id == null) return { name: 'list' };
    if (parts[2] === 'anmeld') return { name: 'review', placeId: id, reviewId: num(parts[3]) };
    if (parts[2] === 'ret') return { name: 'editPlace', id };
    return { name: 'place', id };
  }
  return { name: 'list' };
}

export function routeHash(r: FmRoute): string {
  switch (r.name) {
    case 'list': return '#/';
    case 'newPlace': return r.lat != null && r.lng != null
      ? `#/nyt-sted/${r.lat.toFixed(5)}/${r.lng.toFixed(5)}` : '#/nyt-sted';
    case 'map': return '#/kort';
    case 'place': return `#/sted/${r.id}`;
    case 'review': return `#/sted/${r.placeId}/anmeld${r.reviewId ? `/${r.reviewId}` : ''}`;
    case 'myReviews': return '#/mine-anmeldelser';
    case 'myPhotos': return '#/mine-billeder';
    case 'wishlist': return '#/oenskeliste';
    case 'myPlaces': return '#/mine-steder';
    case 'editPlace': return `#/sted/${r.id}/ret`;
    case 'ask': return '#/spoerg-alf';
  }
}

/** "4,3 på Google (812)" - Danish decimal comma, count only when known. */
export function webRatingText(rating: number | null, count: number | null,
                              source = 'Google'): string | null {
  if (rating == null) return null;
  const r = rating.toLocaleString('da-DK', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return `${r} på ${source}${count != null ? ` (${count.toLocaleString('da-DK')})` : ''}`;
}

/** "800 m", "2,4 km", "38 km" - Danish decimal comma. */
export function distanceText(km: number | undefined | null): string | null {
  if (km == null) return null;
  if (km < 1) return `${Math.max(100, Math.round(km * 10) * 100)} m`;
  if (km < 10) return `${km.toLocaleString('da-DK', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} km`;
  return `${Math.round(km)} km`;
}

export function todayIso(now = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`;
}

/** "14. juli 2026" for a stored ISO date. */
export function dateText(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('da-DK', { day: 'numeric', month: 'long', year: 'numeric' });
}

export interface ReviewDraft {
  overall: number | null;
  visitedOn: string;
  who: string;
  fields: Record<string, FmFieldValue | null>;
  text: string;
  again: boolean | null;
}

export function emptyDraft(now = new Date()): ReviewDraft {
  return { overall: null, visitedOn: todayIso(now), who: '', fields: {}, text: '', again: null };
}

export function draftFrom(r: FmReview): ReviewDraft {
  return { overall: r.overall, visitedOn: r.visitedOn ?? '', who: r.who,
           fields: { ...r.fields }, text: r.text, again: r.again };
}

/** The body the server takes: only this category's fields, unset ones left
    out, text trimmed. Returns an error in Danish instead when the one
    required score is missing. */
/** A computed score ("Mad") as the page shows it while you fill in its
    parts: the rounded average of the parts that have a score, or null.
    The server computes the same when the review is saved. (2.50.0) */
export function computedScore(field: FmField, values: Record<string, FmFieldValue | null>): number | null {
  const parts = (field.computed ?? []).map((k) => values[k])
    .filter((v): v is number => typeof v === 'number');
  return parts.length ? Math.round(parts.reduce((a, b) => a + b, 0) / parts.length) : null;
}

export function reviewBody(d: ReviewDraft, cat: FmCategory): FmReviewBody | string {
  if (d.overall == null) return 'Giv stedet en samlet karakter.';
  const fields: Record<string, FmFieldValue> = {};
  for (const f of cat.fields) {
    // A computed score is the server's to work out from its parts - sent
    // only when no part has a score (a review from before 2.50.0).
    if (f.computed && computedScore(f, d.fields) != null) continue;
    const v = d.fields[f.key];
    if (v == null || v === '') continue;
    fields[f.key] = typeof v === 'string' ? v.trim() : v;
    if (fields[f.key] === '') delete fields[f.key];
  }
  return { overall: d.overall, visitedOn: d.visitedOn, who: d.who.trim(),
           fields, text: d.text.trim(), again: d.again };
}


/** Alf's answer in pieces: text, and the places it names as [[id]] -
    which the page turns into links. A marker for a place that is not in
    the answer's list stays out (the model is told to use only those).
    Paragraphs split on blank lines. (2.46.0) */
export type AnswerPiece = { kind: 'text'; text: string } | { kind: 'place'; id: number };

export function parseAnswer(text: string, known: Set<number>): AnswerPiece[][] {
  return text.split(/\n\s*\n/).map((para) => {
    const out: AnswerPiece[] = [];
    let last = 0;
    for (const m of para.matchAll(/\s*\[\[(\d+)\]\]/g)) {
      if (m.index! > last) out.push({ kind: 'text', text: para.slice(last, m.index) });
      const id = Number(m[1]);
      if (known.has(id)) out.push({ kind: 'place', id });
      last = m.index! + m[0].length;
    }
    if (last < para.length) out.push({ kind: 'text', text: para.slice(last) });
    return out.filter((p) => p.kind === 'place' || p.text.trim() !== '');
  }).filter((p) => p.length > 0);
}


/** The map endpoint's compact rows -> GeoJSON points for MapLibre. (2.47.0) */
export interface MapData { cats: string[]; points: [number, number, number, number, number, string][] }

export function toGeoJSON(d: MapData) {
  return {
    type: 'FeatureCollection' as const,
    features: d.points.map(([id, lat, lng, c, flags, name]) => ({
      type: 'Feature' as const,
      id,
      geometry: { type: 'Point' as const, coordinates: [lng, lat] },
      properties: { id, name, cat: d.cats[c] ?? 'nature',
                    reviewed: (flags & 1) === 1, wished: (flags & 2) === 2 },
    })),
  };
}
