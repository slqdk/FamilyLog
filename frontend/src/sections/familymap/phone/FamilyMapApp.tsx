import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react';

// The map is most of a megabyte; it loads when "Tilføj et sted" opens it. (2.47.0)
const MapView = lazy(() => import('./MapView'));
import { createPortal } from 'react-dom';
import { fmApi } from './api';
import {
  dateText, distanceText, draftFrom, emptyDraft, parseRoute, reviewBody, routeHash, webRatingText,
  type FmRoute, type ReviewDraft,
  parseAnswer,
  computedScore,
} from './logic';
import { Wordmark, categoryArt } from './art';
import { FieldInput, Score, ScoreInput, YesNo, fieldText } from './parts';
import { type FmAsk,
  photoUrl, type FmCategories, type FmMyPhoto, type FmPlace, type FmReview, type FmUser,
} from './types';
import { AlfAnimation, asPhase } from './anim';

function go(r: FmRoute) { window.location.hash = routeHash(r); }

/** Steps taken inside the page since it loaded. Back walks the phone's own
    history while there is some of ours to walk; on a page opened straight
    from a link it replaces instead, so back never leaves the app. */
let steps = 0;
let replacing = false;
function replaceWith(r: FmRoute) {
  replacing = true;            // a replace adds no history entry to walk back
  window.location.replace(routeHash(r));
}
function goBack(fallback: FmRoute) {
  if (steps > 0) { steps -= 2; window.history.back(); }
  else replaceWith(fallback);
}

function useRoute(): FmRoute {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const on = () => {
      if (replacing) replacing = false; else steps += 1;
      setRoute(parseRoute(window.location.hash));
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return route;
}

export function FamilyMapApp() {
  const [me, setMe] = useState<FmUser | null | false>(null);
  const [cats, setCats] = useState<FmCategories | null>(null);
  // The page's name is a setting in the admin (2.44.1); the login screen
  // needs it too, so it comes from a public endpoint.
  const [brand, setBrand] = useState(document.title);
  const route = useRoute();

  useEffect(() => {
    fmApi.brand().then((b) => { setBrand(b.name); document.title = b.name; }).catch(() => {});
  }, []);

  useEffect(() => {
    fmApi.status().then((s) => setMe(s.user ?? false)).catch(() => setMe(false));
  }, []);
  useEffect(() => {
    if (me) fmApi.categories().then(setCats).catch(() => setMe(false));
  }, [me]);

  if (me === null) return <div className="fm-wait">Et øjeblik…</div>;
  if (me === false) return <Login onIn={setMe} brand={brand} />;
  if (!cats) return <div className="fm-wait">Henter kategorier…</div>;

  const signOut = async () => { await fmApi.logout().catch(() => {}); setMe(false); };
  switch (route.name) {
    case 'place': return <PlaceView id={route.id} cats={cats} me={me} />;
    case 'review': return <ReviewEditor placeId={route.placeId} reviewId={route.reviewId} cats={cats} />;
    case 'newPlace': return <NewPlace cats={cats} at={route.lat != null && route.lng != null
      ? { lat: route.lat, lng: route.lng } : null} />;
    case 'map': return (
      <Frame title="Vælg et sted" back={{ name: 'list' }}>
        <Suspense fallback={<p className="fm-note">Henter kortet…</p>}>
          <MapView cats={cats} onOpen={(id) => go({ name: 'place', id })}
                   onCreate={(lat, lng) => go({ name: 'newPlace', lat, lng })} />
        </Suspense>
      </Frame>
    );
    case 'myReviews': return <MyReviews cats={cats} />;
    case 'myPlaces': return <MyPlaces cats={cats} />;
    case 'editPlace': return <EditPlace id={route.id} cats={cats} />;
    case 'myPhotos': return <MyPhotos />;
    case 'wishlist': return <Wishlist cats={cats} />;
    case 'ask': return <AskAlf cats={cats} />;
    default: return <PlaceList cats={cats} me={me} onSignOut={signOut} brand={brand} />;
  }
}

// ---- sign in ---------------------------------------------------------------------

function Login({ onIn, brand }: { onIn: (u: FmUser) => void; brand: string }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try { onIn((await fmApi.login(username, password)).user); }
    catch (err) {
      setError(err instanceof Error && err.message !== 'Wrong username or password.'
        ? err.message : 'Forkert brugernavn eller adgangskode.');
    } finally { setBusy(false); }
  }
  return (
    <main className="fm-login">
      <Wordmark name={brand} />
      <p className="fm-tagline">Familiens egne anmeldelser af steder vi har været.</p>
      <form onSubmit={submit} className="fm-stack fm-sheet">
        <label className="fm-field"><span className="fm-label">Brugernavn</span>
          <input value={username} autoComplete="username" autoCapitalize="none"
                 onChange={(e) => setUsername(e.target.value)} /></label>
        <label className="fm-field"><span className="fm-label">Adgangskode</span>
          <input type="password" value={password} autoComplete="current-password"
                 onChange={(e) => setPassword(e.target.value)} /></label>
        {error && <p className="fm-error">{error}</p>}
        <button className="fm-primary" disabled={busy || !username || !password}>
          {busy ? 'Logger ind…' : 'Log ind'}
        </button>
      </form>
    </main>
  );
}

// ---- the list --------------------------------------------------------------------

function PlaceList({ cats, me, onSignOut, brand }: {
  cats: FmCategories; me: FmUser; onSignOut: () => void; brand: string;
}) {
  const [q, setQ] = useState('');
  const [cat, setCat] = useState('');
  const [places, setPlaces] = useState<FmPlace[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  // "Nær mig" (2.44.0): nearest first from the phone's position. Remembered
  // on the phone, because with thousands of imported places an A-Z list
  // is no way to find anything.
  const [nearOn, setNearOn] = useState(() => {
    try { return localStorage.getItem('fm.near') === '1'; } catch { return false; }
  });
  const [pos, setPos] = useState<{ lat: number; lng: number } | null>(null);
  const [posNote, setPosNote] = useState<string | null>(null);

  useEffect(() => {
    try { localStorage.setItem('fm.near', nearOn ? '1' : '0'); } catch { /* private mode */ }
    if (!nearOn) { setPos(null); setPosNote(null); return; }
    if (!navigator.geolocation) { setPosNote('Telefonen kan ikke give en position.'); setNearOn(false); return; }
    setPosNote('Finder din position…');
    navigator.geolocation.getCurrentPosition(
      (p) => { setPos({ lat: p.coords.latitude, lng: p.coords.longitude }); setPosNote(null); },
      () => { setPosNote('Positionen blev ikke givet. Tjek at siden må bruge placering.'); setNearOn(false); },
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 120000 });
  }, [nearOn]);

  useEffect(() => {
    if (nearOn && !pos) return;               // wait for the position
    let live = true;
    const t = window.setTimeout(() => {
      fmApi.places(q, cat, nearOn ? pos : null)
        .then((p) => { if (live) { setPlaces(p); setError(null); } })
        .catch((e) => { if (live) setError(e.message); });
    }, q ? 250 : 0);
    return () => { live = false; window.clearTimeout(t); };
  }, [q, cat, nearOn, pos]);

  return (
    <div className="fm-page">
      <header className="fm-top">
        <div className="fm-top-row">
          <Wordmark name={brand} />
          <button className="fm-burger" onClick={() => setMenu(true)} aria-expanded={menu}
                  aria-label="Menu">
            <span /><span /><span />
          </button>
        </div>
        {menu && <Menu me={me} onClose={() => setMenu(false)} onSignOut={onSignOut} />}
        <input className="fm-search" type="search" value={q} placeholder="Søg efter sted eller by"
               onChange={(e) => setQ(e.target.value)} />
        <div className="fm-chips" role="group" aria-label="Kategori">
          <button className={`fm-near${nearOn ? ' on' : ''}`} aria-pressed={nearOn}
                  onClick={() => setNearOn((v) => !v)}>Nær mig</button>
          <button className={cat === '' ? 'on' : ''} onClick={() => setCat('')}>Alle</button>
          {Object.entries(cats).map(([key, c]) => (
            <button key={key} className={cat === key ? 'on' : ''}
                    onClick={() => setCat(cat === key ? '' : key)}>
              <span aria-hidden>{c.icon}</span> {c.label}
            </button>
          ))}
        </div>
      </header>

      <main className="fm-list">
        {error && <p className="fm-error">{error}</p>}
        {posNote && <p className="fm-dim fm-pad">{posNote}</p>}
        {places === null && !error && !posNote && <p className="fm-dim fm-pad">Henter steder…</p>}
        {places?.length === 0 && (
          <div className="fm-empty">
            <p>{q || cat ? 'Ingen steder passer på søgningen.' : 'Der er ingen steder endnu.'}</p>
            <p className="fm-dim">Tilføj det første sted, I har besøgt.</p>
          </div>
        )}
        {places?.map((p) => <PlaceCard key={p.id} p={p} cats={cats} />)}
        {places?.some((p) => p.source === 'osm') && <OsmCredit />}
      </main>

      <footer className="fm-bottom fm-bottom-two">
        <button className="fm-primary fm-ask-btn" onClick={() => go({ name: 'ask' })}>Spørg Alf</button>
        <button className="fm-primary" onClick={() => go({ name: 'map' })}>Tilføj et sted</button>
      </footer>
    </div>
  );
}

// ---- one place -------------------------------------------------------------------

function PlaceView({ id, cats, me }: { id: number; cats: FmCategories; me: FmUser }) {
  const [place, setPlace] = useState<FmPlace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [photo, setPhoto] = useState<number | null>(null);

  useEffect(() => {
    fmApi.place(id).then(setPlace).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <Frame title="Sted" back={{ name: 'list' }}><p className="fm-error">{error}</p></Frame>;
  if (!place) return <Frame title="Sted" back={{ name: 'list' }}><p className="fm-dim fm-pad">Henter…</p></Frame>;
  const cat = cats[place.category];
  const web = webRatingText(place.webRating, place.webRatingCount);
  const mapsUrl = place.lat != null && place.lng != null
    ? `https://www.google.com/maps/search/?api=1&query=${place.lat},${place.lng}`
    : place.address ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${place.name} ${place.address}`)}` : null;

  const toggleWish = async () => {
    try { setPlace({ ...(await fmApi.setWished(place.id, !place.wished)), reviews: place.reviews }); }
    catch (e) { setError(e instanceof Error ? e.message : 'Kunne ikke gemme.'); }
  };

  return (
    <Frame title={cat?.label ?? 'Sted'} back={{ name: 'list' }}>
      {place.coverPhotoId ? (
        <img className="fm-cover" src={photoUrl(place.coverPhotoId)} alt=""
             onClick={() => setPhoto(place.coverPhotoId)} />
      ) : (
        <div className="fm-cover fm-cover-art" style={{ backgroundImage: `url("${categoryArt(place.category)}")` }} />
      )}
      <section className="fm-sheet fm-place-sheet">
        <div className="fm-place-head">
          <div>
            <h2 className="fm-place-name">{place.name}</h2>
            {place.address && <p className="fm-dim">{place.address}</p>}
            <p className="fm-facts">
              {mapsUrl && <a href={mapsUrl} target="_blank" rel="noreferrer">Vis på kort</a>}
              {place.website && <a href={place.website} target="_blank" rel="noreferrer">Hjemmeside</a>}
            </p>
            {web && <p className="fm-dim">{web}</p>}
          </div>
          <Score value={place.familyScore} label="Familiens karakter" />
        </div>
        <div className="fm-place-actions">
          <button className="fm-primary" onClick={() => go({ name: 'review', placeId: id, reviewId: null })}>
            Skriv en anmeldelse
          </button>
          <button className={`fm-wish${place.wished ? ' on' : ''}`} onClick={toggleWish}
                  aria-pressed={place.wished}>
            <span aria-hidden>{place.wished ? '♥' : '♡'}</span>
            {place.wished ? ' På ønskelisten' : ' Vil gerne besøge'}
          </button>
          {(place.createdBy === me.id || me.role === 'admin') && place.source !== 'osm' && (
            <button className="fm-secondary" onClick={() => go({ name: 'editPlace', id })}>Ret stedet</button>
          )}
        </div>
        {place.source === 'osm' && <OsmCredit />}
      </section>
      <section className="fm-reviews">
        {(place.reviews ?? []).length === 0 && (
          <p className="fm-dim fm-pad">Ingen i familien har anmeldt stedet endnu.</p>
        )}
        {(place.reviews ?? []).map((r) => (
          <ReviewCard key={r.id} r={r} cat={cat} canEdit={me.role === 'admin' || r.userId === me.id}
                      onPhoto={setPhoto} />
        ))}
      </section>
      {photo != null && (
        <div className="fm-lightbox" onClick={() => setPhoto(null)} role="dialog" aria-label="Billede">
          <img src={photoUrl(photo)} alt="" />
        </div>
      )}
    </Frame>
  );
}

function ReviewCard({ r, cat, canEdit, onPhoto }: {
  r: FmReview; cat: FmCategories[string] | undefined; canEdit: boolean;
  onPhoto: (id: number) => void;
}) {
  const shown = (cat?.fields ?? []).filter((f) => r.fields[f.key] != null);
  return (
    <article className="fm-review">
      <header className="fm-review-head">
        <div>
          <strong>{r.author}</strong>
          <span className="fm-dim"> {dateText(r.visitedOn)}</span>
          {r.who && <div className="fm-dim">Med: {r.who}</div>}
        </div>
        <Score value={r.overall} size="sm" />
      </header>
      {r.text && <p className="fm-review-text">{r.text}</p>}
      {shown.length > 0 && (
        <dl className="fm-fieldlist">
          {shown.map((f) => (
            <div key={f.key} className={f.part_of ? 'fm-part-row' : undefined}>
              <dt>{f.label}</dt>
              <dd>{f.kind === 'rating' ? <Score value={r.fields[f.key] as number} size="sm" />
                   : fieldText(f, r.fields[f.key])}</dd>
            </div>
          ))}
          {r.again != null && <div><dt>Vil gerne igen</dt><dd>{r.again ? 'Ja' : 'Nej'}</dd></div>}
        </dl>
      )}
      {shown.length === 0 && r.again != null && (
        <p className="fm-dim">Vil gerne igen: {r.again ? 'ja' : 'nej'}</p>
      )}
      {r.photos.length > 0 && (
        <div className="fm-photos">
          {r.photos.map((p) => (
            <img key={p.id} src={photoUrl(p.id, true)} alt="" loading="lazy"
                 onClick={() => onPhoto(p.id)} />
          ))}
        </div>
      )}
      {canEdit && (
        <button className="fm-link" onClick={() => go({ name: 'review', placeId: r.placeId, reviewId: r.id })}>
          Ret anmeldelsen
        </button>
      )}
    </article>
  );
}

// ---- write or edit a review ---------------------------------------------------------

function ReviewEditor({ placeId, reviewId, cats }: {
  placeId: number; reviewId: number | null; cats: FmCategories;
}) {
  const [place, setPlace] = useState<FmPlace | null>(null);
  const [draft, setDraft] = useState<ReviewDraft>(() => emptyDraft());
  const [existing, setExisting] = useState<FmReview | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const previews = useMemo(() => files.map((f) => URL.createObjectURL(f)), [files]);
  useEffect(() => () => previews.forEach((u) => URL.revokeObjectURL(u)), [previews]);

  const load = useCallback(() => {
    fmApi.place(placeId).then((p) => {
      setPlace(p);
      const r = reviewId ? p.reviews?.find((x) => x.id === reviewId) ?? null : null;
      setExisting(r);
      if (r) setDraft(draftFrom(r));
    }).catch((e) => setError(e.message));
  }, [placeId, reviewId]);
  useEffect(load, [load]);

  const back: FmRoute = { name: 'place', id: placeId };
  if (!place) {
    return <Frame title="Anmeldelse" back={back}>
      {error ? <p className="fm-error">{error}</p> : <p className="fm-dim fm-pad">Henter…</p>}
    </Frame>;
  }
  const cat = cats[place.category];
  const set = (patch: Partial<ReviewDraft>) => setDraft((d) => ({ ...d, ...patch }));

  async function save() {
    const body = reviewBody(draft, cat);
    if (typeof body === 'string') { setError(body); return; }
    setBusy(true); setError(null);
    try {
      const saved = existing ? await fmApi.updateReview(existing.id, body)
        : await fmApi.createReview(placeId, body);
      if (files.length) await fmApi.addPhotos(saved.id, files);
      goBack(back);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Kunne ikke gemme.');
      // A new review that saved but whose photos failed is now an existing
      // one - a second tap must not write it twice.
      setBusy(false);
      if (!existing) load();
    }
  }

  async function removeReview() {
    if (!existing || !window.confirm('Slet anmeldelsen og dens billeder?')) return;
    setBusy(true);
    try { await fmApi.deleteReview(existing.id); goBack(back); }
    catch (e) { setError(e instanceof Error ? e.message : 'Kunne ikke slette.'); setBusy(false); }
  }

  async function removePhoto(id: number) {
    if (!window.confirm('Slet billedet?')) return;
    try {
      await fmApi.deletePhoto(id);
      setExisting((r) => r && { ...r, photos: r.photos.filter((p) => p.id !== id) });
    } catch (e) { setError(e instanceof Error ? e.message : 'Kunne ikke slette.'); }
  }

  return (
    <Frame title={existing ? 'Ret anmeldelse' : 'Ny anmeldelse'} back={back}>
      <div className="fm-form fm-stack">
        <h2 className="fm-place-name">{place.name}</h2>
        <ScoreInput label="Samlet karakter" required value={draft.overall}
                    onChange={(v) => set({ overall: v })} />
        <label className="fm-field"><span className="fm-label">Besøgt</span>
          <input type="date" value={draft.visitedOn} onChange={(e) => set({ visitedOn: e.target.value })} /></label>
        <label className="fm-field"><span className="fm-label">Hvem var med</span>
          <input value={draft.who} maxLength={200} placeholder="F.eks. hele familien"
                 onChange={(e) => set({ who: e.target.value })} /></label>

        <h3 className="fm-sub">{cat.label}</h3>
        {cat.fields.map((f) => f.computed ? (
          // "Mad" and "Drikkevarer" are worked out from the parts under them,
          // not set by hand. (2.50.0, drinks 2.50.1)
          <div key={f.key} className="fm-computed">
            <div>
              <span className="fm-label">{f.label}</span>
              <span className="fm-dim">
                {computedScore(f, draft.fields) != null ? 'Gennemsnit af karaktererne herunder'
                  : draft.fields[f.key] != null ? 'Fra før - giv dem herunder karakter for at beregne'
                  : 'Giv en eller flere herunder karakter'}
              </span>
            </div>
            <Score value={computedScore(f, draft.fields)
                          ?? (typeof draft.fields[f.key] === 'number' ? draft.fields[f.key] as number : null)}
                   size="sm" label={f.label} />
          </div>
        ) : (
          <div key={f.key} className={f.part_of ? 'fm-part' : undefined}>
            <FieldInput field={f} value={draft.fields[f.key]}
                        onChange={(v) => set({ fields: { ...draft.fields, [f.key]: v } })} />
          </div>
        ))}

        <div className="fm-field"><span className="fm-label">Vil I gerne igen?</span>
          <YesNo value={draft.again} onChange={(v) => set({ again: v })} /></div>
        <label className="fm-field"><span className="fm-label">Fortæl om besøget</span>
          <textarea rows={5} value={draft.text} maxLength={4000}
                    onChange={(e) => set({ text: e.target.value })} /></label>

        <div className="fm-field">
          <span className="fm-label">Billeder</span>
          <div className="fm-photos">
            {existing?.photos.map((p) => (
              <span key={p.id} className="fm-photo-edit">
                <img src={photoUrl(p.id, true)} alt="" />
                <button type="button" aria-label="Slet billedet" onClick={() => removePhoto(p.id)}>×</button>
              </span>
            ))}
            {previews.map((u, i) => (
              <span key={u} className="fm-photo-edit new">
                <img src={u} alt="" />
                <button type="button" aria-label="Fjern billedet"
                        onClick={() => setFiles((f) => f.filter((_, j) => j !== i))}>×</button>
              </span>
            ))}
          </div>
          <label className="fm-secondary fm-filebtn">
            Tilføj billeder
            <input type="file" accept="image/jpeg,image/png,image/webp" multiple hidden
                   onChange={(e) => {
                     const picked = Array.from(e.target.files ?? []);
                     setFiles((f) => [...f, ...picked].slice(0, 10));
                     e.target.value = '';
                   }} />
          </label>
        </div>

        {error && <p className="fm-error">{error}</p>}
        <button className="fm-primary" disabled={busy} onClick={save}>
          {busy ? 'Gemmer…' : existing ? 'Gem ændringer' : 'Gem anmeldelsen'}
        </button>
        {existing && (
          <button className="fm-link fm-danger" disabled={busy} onClick={removeReview}>
            Slet anmeldelsen
          </button>
        )}
      </div>
    </Frame>
  );
}

// ---- add a place -----------------------------------------------------------------

function NewPlace({ cats, at }: { cats: FmCategories; at: { lat: number; lng: number } | null }) {
  const [name, setName] = useState('');
  const [category, setCategory] = useState('');
  const [address, setAddress] = useState('');
  // A point tapped on the map arrives with the route. (2.47.0)
  const [pos, setPos] = useState<{ lat: number; lng: number } | null>(at);
  const [posNote, setPosNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [found, setFound] = useState<string | null>(null);

  // A point from the map or "Brug min position": look up its address - and
  // when OSM has a place there, its name and category. Only empty fields
  // are filled; what the person typed stays. (2.49.0)
  useEffect(() => {
    if (!pos) { setFound(null); return; }
    let live = true;
    setFound('Finder adressen…');
    fmApi.reverse(pos.lat, pos.lng).then((r) => {
      if (!live) return;
      if (r.address) setAddress((a) => a || r.address);
      if (r.name) setName((n) => n || r.name!);
      if (r.category && cats[r.category]) setCategory((c) => c || r.category!);
      setFound(r.source === 'nominatim' ? (r.name ? 'Navn og adresse fra OpenStreetMap.' : 'Adresse fra OpenStreetMap.')
        : r.source === 'town' ? 'Adressen kunne ikke slås op - kun nærmeste by.' : null);
    }).catch(() => { if (live) setFound(null); });
    return () => { live = false; };
  }, [pos, cats]);

  function locate() {
    if (!navigator.geolocation) { setPosNote('Telefonen kan ikke give en position.'); return; }
    setPosNote('Finder din position…');
    navigator.geolocation.getCurrentPosition(
      (p) => { setPos({ lat: p.coords.latitude, lng: p.coords.longitude }); setPosNote(null); },
      () => setPosNote('Positionen blev ikke givet. Tjek at siden må bruge placering.'),
      { enableHighAccuracy: true, timeout: 15000 });
  }

  async function save() {
    setBusy(true); setError(null);
    try {
      const p = await fmApi.createPlace({ name, category, address, lat: pos?.lat ?? null, lng: pos?.lng ?? null });
      // The new-place form gives way to the place, and the review opens on
      // top of it - so saving the review lands on the place, not the form.
      replaceWith({ name: 'place', id: p.id });
      go({ name: 'review', placeId: p.id, reviewId: null });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Kunne ikke gemme.');
      setBusy(false);
    }
  }

  return (
    <Frame title="Nyt sted" back={{ name: 'list' }}>
      <div className="fm-form fm-stack">
        <label className="fm-field"><span className="fm-label">Navn</span>
          <input value={name} maxLength={200} onChange={(e) => setName(e.target.value)} /></label>
        <div className="fm-field">
          <span className="fm-label">Kategori</span>
          <div className="fm-catpick">
            {Object.entries(cats).map(([key, c]) => (
              <button key={key} type="button" className={category === key ? 'on' : ''}
                      onClick={() => setCategory(key)}>
                <span aria-hidden>{c.icon}</span> {c.label}
              </button>
            ))}
          </div>
        </div>
        <label className="fm-field"><span className="fm-label">Adresse eller by</span>
          <input value={address} maxLength={200} onChange={(e) => setAddress(e.target.value)} />
          {found && <span className="fm-dim">{found}</span>}</label>
        <div className="fm-field">
          <span className="fm-label">Placering</span>
          {pos ? (
            <p className="fm-dim">Gemt: {pos.lat.toFixed(5)}, {pos.lng.toFixed(5)}{' '}
              <button type="button" className="fm-link" onClick={() => setPos(null)}>Fjern</button></p>
          ) : (
            <button type="button" className="fm-secondary" onClick={locate}>Brug min position</button>
          )}
          {posNote && <p className="fm-dim">{posNote}</p>}
        </div>
        {error && <p className="fm-error">{error}</p>}
        <button className="fm-primary" disabled={busy || !name.trim() || !category} onClick={save}>
          {busy ? 'Gemmer…' : 'Gem og skriv anmeldelse'}
        </button>
      </div>
    </Frame>
  );
}

// ---- the list's card (2.45.0) -------------------------------------------------------

/** One place as a cream card: the family's newest photo or the category's
    drawing, the name, one line (the newest review, else distance and
    category), and the family's score when there is one. */
function PlaceCard({ p, cats }: { p: FmPlace; cats: FmCategories }) {
  const where = [distanceText(p.distanceKm), cats[p.category]?.label ?? p.category, p.address]
    .filter(Boolean).join(', ');
  return (
    <button className="fm-card" onClick={() => go({ name: 'place', id: p.id })}>
      <span className="fm-card-pic">
        {p.coverPhotoId
          ? <img src={photoUrl(p.coverPhotoId, true)} alt="" loading="lazy" />
          : <img src={categoryArt(p.category)} alt="" loading="lazy" />}
      </span>
      <span className="fm-card-main">
        <span className="fm-card-name">{p.name}</span>
        <span className="fm-card-line">{p.latestText ?? where}</span>
        {p.latestText && <span className="fm-card-sub">{where}</span>}
      </span>
      <span className="fm-card-side">
        {p.familyScore != null && <Score value={p.familyScore} size="sm" label="Familiens karakter" />}
        {p.wished && <span className="fm-card-heart" aria-label="På ønskelisten">♥</span>}
      </span>
    </button>
  );
}

// ---- Spørg Alf (2.46.0) ------------------------------------------------------------------

const RADII: [number | null, string][] = [[null, 'Auto'], [5, '5 km'], [10, '10 km'],
                                          [25, '25 km'], [50, '50 km']];

const EXAMPLES = [
  'Jeg mangler en aktivitet for mit barn på 4 år omkring Vojens',
  'Jeg er sulten efter en pizza i Flensborg',
  'Hvor kan vi få is i nærheden?',
];

/** One question at a time: a new one replaces the last answer. The work
    runs in the server's GPU queue; this page polls it, and picks the
    answer up again if the phone was locked or the page reloaded. */
function AskAlf({ cats }: { cats: FmCategories }) {
  const [q, setQ] = useState('');
  const [st, setSt] = useState<FmAsk | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [usePos, setUsePos] = useState(() => {
    try { return localStorage.getItem('fm.near') === '1'; } catch { return false; }
  });
  // Chosen on the page, remembered on the phone; null = Alf decides. (2.47.0)
  const [radius, setRadius] = useState<number | null>(() => {
    try { const v = Number(localStorage.getItem('fm.radius')); return v > 0 ? v : null; } catch { return null; }
  });
  const pickRadius = (v: number | null) => {
    setRadius(v);
    try { localStorage.setItem('fm.radius', v ? String(v) : ''); } catch { /* private mode */ }
  };
  const busy = st?.state === 'queued' || st?.state === 'working';

  useEffect(() => { fmApi.askState().then(setSt).catch(() => {}); }, []);
  useEffect(() => {
    if (!busy) return;
    const t = window.setInterval(() => { fmApi.askState().then(setSt).catch(() => {}); }, 700);
    return () => window.clearInterval(t);
  }, [busy]);

  const position = () => new Promise<{ lat: number; lng: number } | null>((resolve) => {
    if (!usePos || !navigator.geolocation) { resolve(null); return; }
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
      () => resolve(null), { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
  });

  async function send(question: string) {
    if (!question.trim() || busy) return;
    setError(null);
    try { setSt(await fmApi.ask(question.trim(), await position(), radius)); setQ(''); }
    catch (e) { setError(e instanceof Error ? e.message : 'Alf kunne ikke tage imod spørgsmålet.'); }
  }

  const places = new Map((st?.places ?? []).map((p) => [p.id, p]));
  const answer = st?.text ? parseAnswer(st.text, new Set(places.keys())) : [];
  const named = [...new Set(answer.flat().filter((a) => a.kind === 'place')
    .map((a) => (a as { id: number }).id))].map((id) => places.get(id)!).filter(Boolean);

  return (
    <Frame title="Spørg Alf" back={{ name: 'list' }}>
      <div className="fm-stack fm-ask">
        <div className="fm-sheet fm-ask-box">
          <textarea rows={3} value={q} maxLength={400} placeholder="Hvad har I lyst til?"
                    onChange={(e) => setQ(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(q); } }} />
          <div className="fm-radius" role="group" aria-label="Afstand">
            <span className="fm-radius-label">Afstand</span>
            {RADII.map(([v, label]) => (
              <button key={label} className={radius === v ? 'on' : ''} aria-pressed={radius === v}
                      onClick={() => pickRadius(v)}>{label}</button>
            ))}
          </div>
          <div className="fm-ask-row">
            <label className="fm-ask-pos">
              <input type="checkbox" checked={usePos} onChange={(e) => setUsePos(e.target.checked)} />
              Brug min position
            </label>
            <button className="fm-primary fm-ask-send" disabled={busy || !q.trim()} onClick={() => send(q)}>
              Spørg
            </button>
          </div>
        </div>
        {!st?.question && !busy && (
          <div className="fm-examples">
            {EXAMPLES.map((ex) => (
              <button key={ex} className="fm-example" onClick={() => send(ex)}>{ex}</button>
            ))}
          </div>
        )}
        {error && <p className="fm-error">{error}</p>}
        {st?.question && (
          <div className="fm-sheet fm-answer" aria-live="polite">
            <p className="fm-ask-q">{st.question}</p>
            {busy && (
              <>
                {/* One scene per phase; while the answer streams in, the
                    text itself is the progress. (2.48.0) */}
                {!(st.phase === 'write' && st.text) && (
                  <AlfAnimation phase={asPhase(st.phase, st.state)} />
                )}
                <p className="fm-ask-step">
                  {st.state === 'queued' && st.ahead ? `Venter - ${st.ahead} foran i køen…` : st.step}
                </p>
              </>
            )}
            {st.state === 'failed' && <p className="fm-error">{st.error}</p>}
            {answer.map((para, i) => (
              <p key={i} className="fm-answer-p">
                {para.map((a, j) => a.kind === 'text' ? <span key={j}>{a.text}</span> : (
                  // Alf writes the name itself ("Legeland [[12]]"), so the
                  // marker becomes a small pin after it, not the name again.
                  <button key={j} className="fm-answer-link" aria-label={`Se ${places.get(a.id)?.name ?? 'stedet'}`}
                          onClick={() => go({ name: 'place', id: a.id })}>
                    <span aria-hidden>📍</span>
                  </button>
                ))}
              </p>
            ))}
            {st.state === 'done' && (
              <p className="fm-dim fm-ask-meta">
                {st.where ? `Søgt efter ${st.searched ? st.searched.charAt(0).toLowerCase() + st.searched.slice(1) : 'steder'}`
                  + ` omkring ${st.where}${st.radiusKm ? `, ${st.radiusKm} km` : ''}.` : ''}
                {st.webAdded ? ` ${st.webAdded} nye steder fundet på nettet og gemt.` : ''}
              </p>
            )}
          </div>
        )}
        {st?.state === 'done' && named.length > 0 && (
          <div className="fm-list-cards">
            {named.map((p) => <PlaceCard key={p.id} p={p} cats={cats} />)}
          </div>
        )}
      </div>
    </Frame>
  );
}

// ---- the burger menu (2.45.0) ----------------------------------------------------------

/** The person's own things. Closes with × or by choosing - a tap beside it
    does nothing, like every panel in the app. */
function Menu({ me, onClose, onSignOut }: {
  me: FmUser; onClose: () => void; onSignOut: () => void;
}) {
  const open = (r: FmRoute) => { onClose(); go(r); };
  // Rendered into <body>: inside the sticky header it shared the header's
  // stacking context, and the fixed "Tilføj et sted" painted over it.
  return createPortal(
    <div className="fm-scrim" role="dialog" aria-modal="true" aria-label="Menu">
      <nav className="fm-drawer">
        <div className="fm-drawer-head">
          <span className="fm-drawer-who">{me.username}</span>
          <button className="fm-x" onClick={onClose} aria-label="Luk menuen">×</button>
        </div>
        <button className="fm-drawer-item" onClick={() => open({ name: 'myPlaces' })}>Mine steder</button>
        <button className="fm-drawer-item" onClick={() => open({ name: 'myReviews' })}>Mine anmeldelser</button>
        <button className="fm-drawer-item" onClick={() => open({ name: 'myPhotos' })}>Mine billeder</button>
        <button className="fm-drawer-item" onClick={() => open({ name: 'wishlist' })}>Vil gerne besøge</button>
        <a className="fm-drawer-item" href="/">Til forsiden (Alf og dagbog)</a>
        <button className="fm-drawer-item fm-drawer-out" onClick={() => { onClose(); onSignOut(); }}>Log ud</button>
      </nav>
    </div>,
    document.body,
  );
}

/** The places this person created - where to find one again to correct
    it. (2.49.5) */
function MyPlaces({ cats }: { cats: FmCategories }) {
  const [rows, setRows] = useState<FmPlace[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { fmApi.myPlaces().then(setRows).catch((e) => setError(e.message)); }, []);
  return (
    <Frame title="Mine steder" back={{ name: 'list' }}>
      <div className="fm-cards">
        {error && <p className="fm-error">{error}</p>}
        {rows === null && !error && <p className="fm-note">Henter…</p>}
        {rows?.length === 0 && <p className="fm-note">Du har ikke oprettet nogen steder endnu.</p>}
        {rows?.map((p) => <PlaceCard key={p.id} p={p} cats={cats} />)}
      </div>
    </Frame>
  );
}

/** Correct a place you created: name, category, address, website, note,
    position. Delete it too - unless someone else has reviewed it (the
    server says so in words). (2.49.5) */
function EditPlace({ id, cats }: { id: number; cats: FmCategories }) {
  const [p, setP] = useState<FmPlace | null>(null);
  const [form, setForm] = useState({ name: '', category: '', address: '', website: '', notes: '' });
  const [pos, setPos] = useState<{ lat: number; lng: number } | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    fmApi.place(id).then((x) => {
      setP(x);
      setForm({ name: x.name, category: x.category, address: x.address,
                website: x.website, notes: x.notes });
      setPos(x.lat != null && x.lng != null ? { lat: x.lat, lng: x.lng } : null);
    }).catch((e) => setError(e.message));
  }, [id]);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));
  const back: FmRoute = { name: 'place', id };

  function locate() {
    if (!navigator.geolocation) { setNote('Telefonen kan ikke give en position.'); return; }
    setNote('Finder din position…');
    navigator.geolocation.getCurrentPosition(
      (g) => { setPos({ lat: g.coords.latitude, lng: g.coords.longitude }); setNote('Ny position - husk at gemme.'); },
      () => setNote('Positionen blev ikke givet. Tjek at siden må bruge placering.'),
      { enableHighAccuracy: true, timeout: 15000 });
  }

  async function save() {
    setBusy(true); setError(null);
    try {
      await fmApi.updatePlace(id, { ...form, lat: pos?.lat ?? null, lng: pos?.lng ?? null });
      goBack(back);
    } catch (e) { setError(e instanceof Error ? e.message : 'Kunne ikke gemme.'); setBusy(false); }
  }

  async function remove() {
    if (!p || !window.confirm(`Slet "${p.name}"${p.reviewCount ? ' med dine anmeldelser og billeder' : ''}?`)) return;
    setBusy(true); setError(null);
    try { await fmApi.deletePlace(id); replaceWith({ name: 'myPlaces' }); }
    catch (e) { setError(e instanceof Error ? e.message : 'Kunne ikke slette.'); setBusy(false); }
  }

  if (!p) {
    return <Frame title="Ret stedet" back={back}>
      {error ? <p className="fm-error fm-pad">{error}</p> : <p className="fm-note">Henter…</p>}
    </Frame>;
  }
  return (
    <Frame title="Ret stedet" back={back}>
      <div className="fm-form fm-stack">
        <label className="fm-field"><span className="fm-label">Navn</span>
          <input value={form.name} maxLength={200} onChange={set('name')} /></label>
        <div className="fm-field">
          <span className="fm-label">Kategori</span>
          <div className="fm-catpick">
            {Object.entries(cats).map(([key, c]) => (
              <button key={key} type="button" className={form.category === key ? 'on' : ''}
                      onClick={() => setForm((f) => ({ ...f, category: key }))}>
                <span aria-hidden>{c.icon}</span> {c.label}
              </button>
            ))}
          </div>
          {p.reviewCount > 0 && form.category !== p.category && (
            <span className="fm-dim">Anmeldelsernes felter følger den gamle kategori.</span>
          )}
        </div>
        <label className="fm-field"><span className="fm-label">Adresse eller by</span>
          <input value={form.address} maxLength={200} onChange={set('address')} /></label>
        <label className="fm-field"><span className="fm-label">Hjemmeside</span>
          <input value={form.website} maxLength={500} inputMode="url" placeholder="https://…"
                 onChange={set('website')} /></label>
        <label className="fm-field"><span className="fm-label">Note</span>
          <textarea rows={3} value={form.notes} maxLength={4000} onChange={set('notes')} /></label>
        <div className="fm-field">
          <span className="fm-label">Placering</span>
          {pos ? <p className="fm-dim">{pos.lat.toFixed(5)}, {pos.lng.toFixed(5)}</p>
               : <p className="fm-dim">Ingen position.</p>}
          <button type="button" className="fm-secondary" onClick={locate}>Brug min position</button>
          {note && <p className="fm-dim">{note}</p>}
        </div>
        {error && <p className="fm-error">{error}</p>}
        <button className="fm-primary" disabled={busy || !form.name.trim()} onClick={save}>
          {busy ? 'Gemmer…' : 'Gem ændringer'}
        </button>
        <button className="fm-link fm-danger" disabled={busy} onClick={remove}>Slet stedet</button>
      </div>
    </Frame>
  );
}

function MyReviews({ cats }: { cats: FmCategories }) {
  const [rows, setRows] = useState<FmReview[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { fmApi.myReviews().then(setRows).catch((e) => setError(e.message)); }, []);
  return (
    <Frame title="Mine anmeldelser" back={{ name: 'list' }}>
      <div className="fm-cards">
        {error && <p className="fm-error">{error}</p>}
        {rows === null && !error && <p className="fm-note">Henter…</p>}
        {rows?.length === 0 && <p className="fm-note">Du har ikke skrevet nogen anmeldelser endnu.</p>}
        {rows?.map((r) => (
          <button key={r.id} className="fm-card" onClick={() => go({ name: 'place', id: r.placeId })}>
            <span className="fm-card-pic">
              <img src={r.photos[0] ? photoUrl(r.photos[0].id, true) : categoryArt(r.placeCategory ?? '')}
                   alt="" loading="lazy" />
            </span>
            <span className="fm-card-main">
              <span className="fm-card-name">{r.placeName}</span>
              <span className="fm-card-line">{r.text || cats[r.placeCategory ?? '']?.label}</span>
              <span className="fm-card-sub">{dateText(r.visitedOn)}</span>
            </span>
            <span className="fm-card-side"><Score value={r.overall} size="sm" /></span>
          </button>
        ))}
      </div>
    </Frame>
  );
}

function MyPhotos() {
  const [rows, setRows] = useState<FmMyPhoto[] | null>(null);
  const [open, setOpen] = useState<FmMyPhoto | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { fmApi.myPhotos().then(setRows).catch((e) => setError(e.message)); }, []);
  return (
    <Frame title="Mine billeder" back={{ name: 'list' }}>
      {error && <p className="fm-error">{error}</p>}
      {rows === null && !error && <p className="fm-note">Henter…</p>}
      {rows?.length === 0 && <p className="fm-note">Du har ikke lagt billeder op endnu.</p>}
      <div className="fm-grid">
        {rows?.map((ph) => (
          <button key={ph.id} onClick={() => setOpen(ph)} aria-label={ph.placeName}>
            <img src={photoUrl(ph.id, true)} alt="" loading="lazy" />
          </button>
        ))}
      </div>
      {open && (
        <div className="fm-lightbox" role="dialog" aria-label="Billede">
          <img src={photoUrl(open.id)} alt="" />
          <div className="fm-lightbox-bar">
            <button className="fm-secondary" onClick={() => { setOpen(null); go({ name: 'place', id: open.placeId }); }}>
              {open.placeName}{open.visitedOn ? `, ${dateText(open.visitedOn)}` : ''}
            </button>
            <button className="fm-x fm-x-light" onClick={() => setOpen(null)} aria-label="Luk">×</button>
          </div>
        </div>
      )}
    </Frame>
  );
}

function Wishlist({ cats }: { cats: FmCategories }) {
  const [rows, setRows] = useState<FmPlace[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    fmApi.places('', '', null, true).then(setRows).catch((e) => setError(e.message));
  }, []);
  return (
    <Frame title="Vil gerne besøge" back={{ name: 'list' }}>
      <div className="fm-cards">
        {error && <p className="fm-error">{error}</p>}
        {rows === null && !error && <p className="fm-note">Henter…</p>}
        {rows?.length === 0 && (
          <p className="fm-note">Din ønskeliste er tom. Tryk ♡ Vil gerne besøge på et sted for at gemme det her.</p>
        )}
        {rows?.map((p) => <PlaceCard key={p.id} p={p} cats={cats} />)}
      </div>
    </Frame>
  );
}

/** ODbL asks for the credit wherever OSM's data is shown. */
function OsmCredit() {
  return (
    <p className="fm-credit">
      Stedoplysninger: ©{' '}
      <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
        OpenStreetMap-bidragydere</a>
    </p>
  );
}

// ---- page frame -------------------------------------------------------------------

function Frame({ title, back, children }: { title: string; back: FmRoute; children: React.ReactNode }) {
  return (
    <div className="fm-page">
      <header className="fm-bar">
        <button className="fm-back" aria-label="Tilbage"
                onClick={() => goBack(back)}>
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden>
            <path d="M15 5 L8 12 L15 19" fill="none" stroke="currentColor" strokeWidth="2.6"
                  strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <span className="fm-bar-title">{title}</span>
      </header>
      <main>{children}</main>
    </div>
  );
}
