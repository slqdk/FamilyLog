import type {
  FmAsk,
  FmCategories, FmMyPhoto, FmPhoto, FmPlace, FmReview, FmReviewBody, FmUser,
} from './types';
import type { MapData } from './logic';

/** The family page's API (2.43.0). Errors carry the backend's Danish
    `detail`, which is shown to the person as it is. */
async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.status === 401 ? 'Du er ikke logget ind.'
      : `Serveren svarede ${res.status}.`;
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

const send = (method: string, body: unknown) => ({
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
});

export const fmApi = {
  status: () => fetch('/api/auth/status')
    .then(json<{ user: FmUser | null; needsSetup: boolean }>),
  login: (username: string, password: string) =>
    fetch('/api/auth/login', send('POST', { username, password })).then(json<{ user: FmUser }>),
  logout: () => fetch('/api/auth/logout', { method: 'POST' }).then(json<{ ok: boolean }>),

  brand: () => fetch('/api/fm/brand').then(json<{ name: string }>),
  ask: (question: string, pos: { lat: number; lng: number } | null, radiusKm: number | null = null) =>
    fetch('/api/fm/ask', send('POST', { question, ...(pos ?? {}), radiusKm })).then(json<FmAsk>),
  askState: () => fetch('/api/fm/ask').then(json<FmAsk>),
  // The browser keeps the ETag and asks "changed?" - an unchanged map is a 304.
  map: () => fetch('/api/fm/map').then(json<MapData>),
  // Address, and the OSM name/category when something is there. (2.49.0)
  reverse: (lat: number, lng: number) =>
    fetch(`/api/fm/reverse?lat=${lat}&lng=${lng}`)
      .then(json<{ address: string; name: string | null; category: string | null;
                   source: 'nominatim' | 'town' | null }>),
  categories: () => fetch('/api/fm/categories').then(json<FmCategories>),
  places: (q = '', category = '', near: { lat: number; lng: number } | null = null,
           wishedOnly = false) => {
    const p = new URLSearchParams();
    if (wishedOnly) p.set('wished', '1');
    if (q.trim()) p.set('q', q.trim());
    if (category) p.set('category', category);
    if (near) { p.set('lat', String(near.lat)); p.set('lng', String(near.lng)); p.set('limit', '200'); }
    return fetch(`/api/fm/places?${p}`).then(json<FmPlace[]>);
  },
  place: (id: number) => fetch(`/api/fm/places/${id}`).then(json<FmPlace>),
  createPlace: (body: Partial<FmPlace>) =>
    fetch('/api/fm/places', send('POST', body)).then(json<FmPlace>),

  createReview: (placeId: number, body: FmReviewBody) =>
    fetch(`/api/fm/places/${placeId}/reviews`, send('POST', body)).then(json<FmReview>),
  updateReview: (id: number, body: FmReviewBody) =>
    fetch(`/api/fm/reviews/${id}`, send('PUT', body)).then(json<FmReview>),
  deleteReview: (id: number) =>
    fetch(`/api/fm/reviews/${id}`, { method: 'DELETE' }).then(json<{ ok: boolean }>),

  addPhotos: (reviewId: number, files: File[]) => {
    const fd = new FormData();
    for (const f of files) fd.append('files', f, f.name);
    return fetch(`/api/fm/reviews/${reviewId}/photos`, { method: 'POST', body: fd })
      .then(json<FmPhoto[]>);
  },
  setWished: (placeId: number, wished: boolean) =>
    fetch(`/api/fm/wishlist/${placeId}`, { method: wished ? 'PUT' : 'DELETE' }).then(json<FmPlace>),
  myReviews: () => fetch('/api/fm/me/reviews').then(json<FmReview[]>),
  myPhotos: () => fetch('/api/fm/me/photos').then(json<FmMyPhoto[]>),
  // 2.49.5: the places I created, and correcting or deleting one.
  myPlaces: () => fetch('/api/fm/me/places').then(json<FmPlace[]>),
  updatePlace: (id: number, body: Partial<FmPlace>) =>
    fetch(`/api/fm/places/${id}`, send('PUT', body)).then(json<FmPlace>),
  deletePlace: (id: number) =>
    fetch(`/api/fm/places/${id}`, { method: 'DELETE' }).then(json<{ ok: boolean }>),
  deletePhoto: (id: number) =>
    fetch(`/api/fm/photos/${id}`, { method: 'DELETE' }).then(json<{ ok: boolean }>),
};
