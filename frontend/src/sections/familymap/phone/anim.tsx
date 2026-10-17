/** What Alf is doing while an answer is on its way (2.48.0) - one small
    scene per phase the server reports:

    queue       sitting, wagging, waiting his turn
    understand  head tilted, a question mark bobbing
    search      a magnifier going over a little map, pins popping up
    web         a globe turning
    think       thought bubbles rising
    write       a pencil drawing lines on a note

    Pure SVG + CSS keyframes (fm.css, "Alf animations"): nothing to load,
    and with reduced motion switched on the scenes stand still. */

export type AlfPhase = 'queue' | 'understand' | 'search' | 'web' | 'think' | 'write';

/** Alf sitting, facing right - the same dog as in the logo. */
function Dog({ tilt }: { tilt?: boolean }) {
  return (
    <g className="alf-dog" fill="currentColor">
      <path className="alf-tail" d="M42.5 76 Q36.5 74 36 68" stroke="currentColor"
            strokeWidth="3.2" fill="none" strokeLinecap="round" />
      <path d="M47 54 Q41 64 41.5 75 Q42 83 48 83 H61 Q64 83 63 78 L59.5 64 Q58 56 55 53.5 Z" />
      <g className={tilt ? 'alf-head alf-tilt' : 'alf-head'}>
        <circle cx="53" cy="47" r="7.2" />
        <ellipse cx="61.5" cy="50" rx="5" ry="3.4" />
        <ellipse cx="48.2" cy="50.5" rx="3.1" ry="6.6" transform="rotate(14 48.2 50.5)" />
      </g>
    </g>
  );
}

function Prop({ phase }: { phase: AlfPhase }) {
  switch (phase) {
    case 'queue':
      return (
        <g className="alf-dots" fill="currentColor">
          <circle cx="92" cy="70" r="4" /><circle cx="106" cy="70" r="4" /><circle cx="120" cy="70" r="4" />
        </g>
      );
    case 'understand':
      return (
        <text className="alf-q" x="70" y="40" fontSize="26" fontWeight="800" fill="currentColor">?</text>
      );
    case 'search':
      return (
        <g>
          <rect x="84" y="46" width="62" height="38" rx="6" className="alf-paper" />
          <path d="M88 70 Q100 58 112 66 T142 60" className="alf-road" />
          <g className="alf-pins" fill="currentColor">
            <circle cx="96" cy="60" r="3.2" /><circle cx="118" cy="72" r="3.2" /><circle cx="136" cy="56" r="3.2" />
          </g>
          <g className="alf-glass">
            <circle cx="104" cy="62" r="9" className="alf-lens" />
            <path d="M110.5 68.5 L118 76" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
          </g>
        </g>
      );
    case 'web':
      return (
        <g className="alf-globe" stroke="currentColor" strokeWidth="2.4" fill="none">
          <circle cx="112" cy="62" r="20" className="alf-globe-face" />
          <ellipse className="alf-meridian" cx="112" cy="62" rx="10" ry="20" />
          <ellipse className="alf-meridian alf-meridian-2" cx="112" cy="62" rx="10" ry="20" />
          <path d="M92 62 H132 M95 51 H129 M95 73 H129" />
        </g>
      );
    case 'think':
      return (
        <g className="alf-bubbles" fill="currentColor">
          <circle cx="66" cy="38" r="2.6" /><circle cx="74" cy="28" r="3.8" />
          <ellipse cx="92" cy="18" rx="13" ry="9" />
        </g>
      );
    case 'write':
      return (
        <g>
          <rect x="86" y="40" width="50" height="46" rx="5" className="alf-paper" />
          <path className="alf-line alf-line-1" d="M93 52 H129" />
          <path className="alf-line alf-line-2" d="M93 62 H125" />
          <path className="alf-line alf-line-3" d="M93 72 H119" />
          <g className="alf-pencil">
            <path d="M0 0 L16 -16 L21 -11 L5 5 Z" fill="currentColor" />
            <path d="M0 0 L5 5 L-2 7 Z" className="alf-lead" />
          </g>
        </g>
      );
  }
}

export function AlfAnimation({ phase }: { phase: AlfPhase }) {
  return (
    <svg className={`alf-anim alf-${phase}`} viewBox="28 8 124 82" role="img"
         aria-label="Alf arbejder">
      <path d="M30 86 H150" className="alf-ground" />
      <Dog tilt={phase === 'understand' || phase === 'think'} />
      <Prop phase={phase} />
    </svg>
  );
}

export function asPhase(p: string | undefined, state: string | undefined): AlfPhase {
  const known: AlfPhase[] = ['queue', 'understand', 'search', 'web', 'think', 'write'];
  if (known.includes(p as AlfPhase)) return p as AlfPhase;
  return state === 'queued' ? 'queue' : 'understand';
}
