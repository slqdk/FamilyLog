import activity from './art/activity.svg';
import attraction from './art/attraction.svg';
import city from './art/city.svg';
import hotel from './art/hotel.svg';
import nature from './art/nature.svg';
import playground from './art/playground.svg';
import restaurant from './art/restaurant.svg';

/** One drawn picture per category, for places the family has no photo of
    (2.45.0). Soft watercolour-style SVGs in src/fm/art. */
const ART: Record<string, string> = { activity, attraction, city, hotel, nature, playground, restaurant };

export function categoryArt(category: string): string {
  return ART[category] ?? nature;
}

/** The "A" with a sitting dog cut out of it - Alf's mark. Drawn to sit in a
    line of Nunito ExtraBold at cap height; the dog is negative space, so it
    shows whatever is behind the text. */
export function DogA({ title }: { title?: string }) {
  const id = 'fm-doga-cut';
  return (
    <svg className="fm-doga" viewBox="0 0 100 100" role={title ? 'img' : undefined}
         aria-label={title} aria-hidden={title ? undefined : true}>
      <defs>
        <mask id={id} maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100">
          <rect width="100" height="100" fill="#fff" />
          {/* sitting dog, facing right: head, floppy ear, snout, body, tail -
              scaled up about its seat so it still reads at header size (2.46.0: larger, in a wider A - at 42 px it was 11 px tall) */}
          <g fill="#000" transform="translate(51 86) scale(1.62) translate(-51 -78)">
            <circle cx="53" cy="47" r="7.2" />
            <ellipse cx="61.5" cy="50" rx="5" ry="3.4" />
            <ellipse cx="48.2" cy="50.5" rx="3.1" ry="6.6" transform="rotate(14 48.2 50.5)" />
            <path d="M47 54 Q41 64 41.5 75 Q42 83 48 83 H61 Q64 83 63 78 L59.5 64 Q58 56 55 53.5 Z" />
            <path d="M42.5 76 Q36.5 74 36 68" stroke="#000" strokeWidth="3.2" fill="none" strokeLinecap="round" />
          </g>
        </mask>
      </defs>
      <path mask={`url(#${id})`} fill="currentColor"
            d="M0 100 L38 5 Q50 -7 62 5 L100 100 H78 L73 90 H27 L22 100 Z" />
    </svg>
  );
}

/** The page's name, with the dog as the first "A" of its last word when it
    has one ("Alf's Atlas" -> "Alf's " + dog-A + "tlas"); otherwise the dog
    stands in front. The name is a setting, so this cannot be a fixed image. */
export function Wordmark({ name, className }: { name: string; className?: string }) {
  const cut = name.lastIndexOf(' ') + 1;
  const last = name.slice(cut);
  if (/^[Aa]/.test(last)) {
    return (
      <h1 className={`fm-wordmark ${className ?? ''}`} aria-label={name}>
        <span aria-hidden>{name.slice(0, cut)}</span><DogA /><span aria-hidden>{last.slice(1)}</span>
      </h1>
    );
  }
  return (
    <h1 className={`fm-wordmark ${className ?? ''}`} aria-label={name}>
      <DogA /><span aria-hidden> {name}</span>
    </h1>
  );
}
