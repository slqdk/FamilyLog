import { useEffect, useMemo, useRef, useState } from 'react';
import { AlfAnimation, asPhase } from '../sections/familymap/phone/anim';
import { categoryArt } from '../sections/familymap/phone/art';
import { parseAnswer } from '../sections/familymap/phone/logic';
import { photoUrl, type FmUser } from '../sections/familymap/phone/types';
import { homeApi, type ChatJob, type ChatState, type PlaceCard } from './api';
import { hello } from './logic';

const EXAMPLES = [
  'Hvad skal vi lave i weekenden?',
  'Find en legeplads i nærheden',
  'Giv mig en nem aftensmad til fire',
  'Hjælp mig med at forklare brøker til en 10-årig',
];

/** Alf: a conversation per person. Places come back as links into Alf's
    Atlas; while Alf works, the same little animations as Spørg Alf. */
export function Chat({ me, resetKey }: { me: FmUser; resetKey: number }) {
  const [state, setState] = useState<ChatState | null>(null);
  const [text, setText] = useState('');
  const [usePos, setUsePos] = useState(() => {
    try { return localStorage.getItem('home.pos') === '1'; } catch { return false; }
  });
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const job = state?.job ?? null;
  const busy = sending || job?.state === 'queued' || job?.state === 'working';

  useEffect(() => { homeApi.chat().then(setState).catch((e) => setError(e.message)); }, []);
  useEffect(() => {
    if (resetKey === 0) return;
    homeApi.chatNew().then(setState).catch((e) => setError(e.message));
  }, [resetKey]);
  useEffect(() => {
    if (!busy || sending) return;
    const t = window.setInterval(() => {
      homeApi.chat().then(setState).catch(() => {});
    }, 600);
    return () => window.clearInterval(t);
  }, [busy, sending]);
  useEffect(() => {
    try { localStorage.setItem('home.pos', usePos ? '1' : '0'); } catch { /* private mode */ }
  }, [usePos]);
  const count = state?.messages.length ?? 0;
  useEffect(() => { endRef.current?.scrollIntoView?.({ block: 'end' }); }, [count, job?.text, job?.state]);

  function position(): Promise<{ lat: number; lng: number } | null> {
    return new Promise((resolve) => {
      if (!usePos || !navigator.geolocation) { resolve(null); return; }
      navigator.geolocation.getCurrentPosition(
        (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
        () => resolve(null), { enableHighAccuracy: false, timeout: 10000, maximumAge: 120000 });
    });
  }

  async function sendText(msg: string) {
    msg = msg.trim();
    if (!msg || busy) return;
    setSending(true); setError(null);
    try { setState(await homeApi.chatSend(msg, await position())); setText(''); }
    catch (e) { setError((e as Error).message); }
    finally { setSending(false); }
  }

  const messages = state?.messages ?? [];
  const showJob = job && (job.state === 'queued' || job.state === 'working' || job.state === 'failed');

  return (
    <>
      <main className="hm-chat" aria-live="polite">
        {state && !state.model && (
          <p className="fm-error">Alf har ingen model endnu - bed administratoren vælge en chatmodel under Indstillinger.</p>
        )}
        {messages.length === 0 && !showJob && (
          <div className="fm-sheet hm-intro">
            <p className="hm-intro-hi">{hello()} {me.username}!</p>
            <p>Jeg er Alf. Spørg mig om hvad som helst - og vil I ud, finder jeg steder ud fra
              familiens egne anmeldelser.</p>
            <div className="fm-examples">
              {EXAMPLES.map((ex) => (
                <button key={ex} className="fm-example" disabled={busy} onClick={() => void sendText(ex)}>{ex}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => m.role === 'user'
          ? <div key={m.id} className="hm-msg hm-me">{m.content}</div>
          : <AlfMessage key={m.id} text={m.content} places={m.places} searched={m.meta.searched ?? null} />)}
        {showJob && <Working job={job} />}
        {error && <p className="fm-error">{error}</p>}
        <div ref={endRef} />
      </main>
      <footer className="hm-composer">
        <div className="hm-composer-box">
          <textarea rows={1} value={text} maxLength={1000} placeholder="Skriv til Alf…"
                    aria-label="Besked til Alf"
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey && window.matchMedia('(pointer: fine)').matches) {
                        e.preventDefault(); void sendText(text);
                      }
                    }} />
          {busy && job?.state !== undefined && !sending
            ? <button className="hm-send hm-stop" aria-label="Stop"
                      onClick={async () => setState(await homeApi.chatStop())}>■</button>
            : <button className="hm-send" aria-label="Send" disabled={busy || !text.trim()}
                      onClick={() => void sendText(text)}>↑</button>}
        </div>
        <label className="hm-pos">
          <input type="checkbox" checked={usePos} onChange={(e) => setUsePos(e.target.checked)} />
          Brug min position til steder
        </label>
      </footer>
    </>
  );
}

function Working({ job }: { job: ChatJob }) {
  if (job.state === 'failed') return <p className="fm-error">{job.error}</p>;
  return (
    <div className="hm-msg hm-alf">
      {!(job.phase === 'write' && job.text) && <AlfAnimation phase={asPhase(job.phase, job.state)} />}
      {job.text
        ? <AnswerText text={job.text} places={job.places} />
        : <p className="fm-ask-step">{job.state === 'queued' && job.ahead ? `Venter - ${job.ahead} foran i køen…` : job.step}</p>}
    </div>
  );
}

function AlfMessage({ text, places, searched }: { text: string; places: PlaceCard[]; searched: string | null }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="hm-msg hm-alf">
      <AnswerText text={text} places={places} />
      {places.length > 0 && (
        <>
          <button className="fm-link hm-more" onClick={() => setOpen(!open)}>
            {open ? (places.length === 1 ? 'Skjul stedet' : 'Skjul stederne')
                  : places.length === 1 ? 'Vis stedet' : `Vis ${places.length} steder`}
          </button>
          {open && (
            <div className="hm-places">
              {searched && <p className="fm-dim">Søgte efter: {searched}</p>}
              {places.map((p) => <PlaceLink key={p.id} p={p} />)}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** Alf's text, with [[id]] as a pin linking the place in Alf's Atlas. */
function AnswerText({ text, places }: { text: string; places: PlaceCard[] }) {
  const known = useMemo(() => new Map(places.map((p) => [p.id, p])), [places]);
  const paras = parseAnswer(text, new Set(known.keys()));
  return (
    <>
      {paras.map((para, i) => (
        <p key={i} className="hm-p">
          {para.map((a, j) => a.kind === 'text' ? <span key={j}>{a.text}</span> : (
            <a key={j} className="fm-answer-link" href={`/fm/#/sted/${a.id}`}
               aria-label={`Se ${known.get(a.id)?.name ?? 'stedet'}`}><span aria-hidden>📍</span></a>
          ))}
        </p>
      ))}
    </>
  );
}

function PlaceLink({ p }: { p: PlaceCard }) {
  return (
    <a className="fm-card hm-place" href={`/fm/#/sted/${p.id}`}>
      <span className="fm-card-pic">
        <img src={p.coverPhotoId ? photoUrl(p.coverPhotoId, true) : categoryArt(p.category)} alt="" loading="lazy" />
      </span>
      <span className="fm-card-main">
        <span className="fm-card-name">{p.name}</span>
        <span className="fm-card-sub">{[p.distanceKm != null ? `${p.distanceKm} km` : null, p.address]
          .filter(Boolean).join(', ')}</span>
      </span>
    </a>
  );
}
