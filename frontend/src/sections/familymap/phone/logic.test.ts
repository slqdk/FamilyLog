import { describe, expect, it } from 'vitest';
import { computedScore, dateText, distanceText, emptyDraft, parseAnswer, toGeoJSON, parseRoute, reviewBody, routeHash, webRatingText } from './logic';
import type { FmCategory } from './types';

const cat: FmCategory = { label: 'Legeplads', icon: '', fields: [
  { key: 'equipment', label: 'Legeredskaber', kind: 'rating' },
  { key: 'shade', label: 'Skygge', kind: 'bool' },
  { key: 'ageRange', label: 'Alder', kind: 'text' },
] };

describe('routes', () => {
  it('round-trips every route', () => {
    for (const r of [{ name: 'list' }, { name: 'newPlace' }, { name: 'place', id: 7 },
                     { name: 'review', placeId: 7, reviewId: null },
                     { name: 'review', placeId: 7, reviewId: 12 },
                     { name: 'myReviews' }, { name: 'myPhotos' }, { name: 'wishlist' },
                     { name: 'ask' }, { name: 'map' }, { name: 'myPlaces' },
                     { name: 'editPlace', id: 12 },
                     { name: 'newPlace', lat: 55.24612, lng: 9.30601 }] as const) {
      expect(parseRoute(routeHash(r))).toEqual(r);
    }
  });
  it('falls back to the list on anything unknown', () => {
    expect(parseRoute('#/sted/abc')).toEqual({ name: 'list' });
    expect(parseRoute('')).toEqual({ name: 'list' });
    expect(parseRoute('#/noget')).toEqual({ name: 'list' });
  });
});

describe('texts', () => {
  it('writes the web rating the Danish way', () => {
    expect(webRatingText(4.3, 812)).toBe('4,3 på Google (812)');
    expect(webRatingText(4, null)).toBe('4,0 på Google');
    expect(webRatingText(null, 5)).toBeNull();
  });
  it('writes dates in Danish', () => {
    expect(dateText('2026-07-14')).toMatch(/14\. juli 2026/);
    expect(dateText(null)).toBe('');
  });
});

describe('distanceText', () => {
  it('rounds the way a person says it', () => {
    expect(distanceText(0.04)).toBe('100 m');
    expect(distanceText(0.83)).toBe('800 m');
    expect(distanceText(2.44)).toBe('2,4 km');
    expect(distanceText(38.4)).toBe('38 km');
    expect(distanceText(undefined)).toBeNull();
  });
});

describe('reviewBody', () => {
  it('requires the overall score', () => {
    expect(reviewBody(emptyDraft(), cat)).toBe('Giv stedet en samlet karakter.');
  });
  it('keeps only set fields of this category, trimmed', () => {
    const d = { ...emptyDraft(new Date(2026, 6, 14)), overall: 80, who: ' mor ',
                fields: { equipment: 90, shade: false, ageRange: '  ', food: 50 } };
    const body = reviewBody(d, cat);
    expect(body).toEqual({ overall: 80, visitedOn: '2026-07-14', who: 'mor',
                           fields: { equipment: 90, shade: false }, text: '', again: null });
  });
});

describe('parseAnswer', () => {
  it('turns [[id]] into place pieces and keeps paragraphs', () => {
    const got = parseAnswer('Prøv Legeland [[12]] - I gav den 88.\n\nEllers Søparken [[7]].', new Set([12, 7]));
    expect(got).toEqual([
      [{ kind: 'text', text: 'Prøv Legeland' }, { kind: 'place', id: 12 },
       { kind: 'text', text: ' - I gav den 88.' }],
      [{ kind: 'text', text: 'Ellers Søparken' }, { kind: 'place', id: 7 }, { kind: 'text', text: '.' }],
    ]);
  });
  it('drops markers for places not in the list, and half-streamed text is fine', () => {
    expect(parseAnswer('Opfundet [[99]] sted', new Set([1]))).toEqual([
      [{ kind: 'text', text: 'Opfundet' }, { kind: 'text', text: ' sted' }]]);
    expect(parseAnswer('Prøv Legeland [[1', new Set([1]))).toEqual([
      [{ kind: 'text', text: 'Prøv Legeland [[1' }]]);
  });
});

describe('map', () => {
  it('turns the compact rows into GeoJSON with lng first', () => {
    const g = toGeoJSON({ cats: ['restaurant', 'playground'],
                          points: [[7, 55.2, 9.3, 1, 3, 'Legeland'], [8, 54.8, 9.4, 0, 0, 'Kro']] });
    expect(g.features[0]).toEqual({ type: 'Feature', id: 7,
      geometry: { type: 'Point', coordinates: [9.3, 55.2] },
      properties: { id: 7, name: 'Legeland', cat: 'playground', reviewed: true, wished: true } });
    expect(g.features[1].properties).toMatchObject({ cat: 'restaurant', reviewed: false, wished: false });
  });
  it('a bad point in the new-place route falls back to no point', () => {
    expect(parseRoute('#/nyt-sted/abc/9')).toEqual({ name: 'newPlace' });
    expect(parseRoute('#/nyt-sted/95/9')).toEqual({ name: 'newPlace' });
  });
});

describe('computedScore (2.50.0)', () => {
  const food = { key: 'food', label: 'Mad', kind: 'rating' as const, computed: ['meat', 'salad', 'fries'] };
  const cat = { label: 'Restaurant', icon: '', fields: [food,
    { key: 'meat', label: 'Kød', kind: 'rating' as const, part_of: 'food' },
    { key: 'salad', label: 'Salat', kind: 'rating' as const, part_of: 'food' },
    { key: 'fries', label: 'Pommes', kind: 'rating' as const, part_of: 'food' }] };
  it('averages the dishes that have a score', () => {
    expect(computedScore(food, { meat: 80, salad: 61, fries: null })).toBe(71);
    expect(computedScore(food, {})).toBeNull();
  });
  it('leaves Mad to the server when dishes are scored, keeps an old one when not', () => {
    const d = { ...emptyDraft(new Date(2026, 9, 4)), overall: 70 };
    expect(reviewBody({ ...d, fields: { food: 10, meat: 80 } }, cat)).toMatchObject({ fields: { meat: 80 } });
    expect(reviewBody({ ...d, fields: { food: 64 } }, cat)).toMatchObject({ fields: { food: 64 } });
  });
});
