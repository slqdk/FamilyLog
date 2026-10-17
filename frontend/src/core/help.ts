/**
 * Click-to-help (from SLQ 2.42.0).
 *
 * Every control carries `data-help="<id>"` on itself or an ancestor (a
 * settings row, a composer button, a card, an admin page's section). Alt +
 * click anywhere walks up to the nearest anchor and opens the Help drawer
 * at that id; the click itself is swallowed, so Alt+click never also
 * toggles the control, follows a link or - in Chrome - downloads one.
 *
 * The drawer lives in App; this module is the bus between the listener
 * and the drawer, so no component has to be threaded a callback.
 */

export const HELP_EVENT = 'app-help';

export interface HelpRequest {
  /** the entry to show; null opens the index */
  id: string | null;
  /** the control's label when the anchor did not resolve, for the "no help
      for this yet" line - a missing entry is a bug the drawer should name */
  label?: string;
}

export function openHelp(id: string | null, label?: string): void {
  window.dispatchEvent(new CustomEvent<HelpRequest>(HELP_EVENT, { detail: { id, label } }));
}

/** The anchor id for an element, or null. */
export function helpIdFor(el: Element | null): string | null {
  const host = el?.closest<HTMLElement>('[data-help]');
  return host?.dataset.help ?? null;
}

/** A short label for the thing under the pointer, for the fallback line. */
function labelFor(el: Element): string {
  const host = el.closest<HTMLElement>('button, label, [title], .props-row, h1, h2, h3, h4');
  const text = (host?.getAttribute('title') || host?.textContent || el.textContent || '')
    .trim().replace(/\s+/g, ' ');
  return text.slice(0, 60);
}

/** Install once (App). Capture phase, so it runs before the control's own
    handler and can stop it. */
export function installAltClickHelp(): () => void {
  const onClick = (e: MouseEvent) => {
    if (!e.altKey || e.ctrlKey || e.metaKey || e.button !== 0) return;
    const target = e.target as Element | null;
    if (!target || target.closest('.help-drawer')) return;   // clicks inside the drawer are normal
    e.preventDefault();
    e.stopPropagation();
    openHelp(helpIdFor(target), labelFor(target));
  };
  document.addEventListener('click', onClick, true);
  return () => document.removeEventListener('click', onClick, true);
}
