import type { ReactNode } from 'react';
import { ledgerSection } from './ledger';
import { familyMapSection } from './familymap';

/** What a section brings to the shell. The backend has the matching
    registry in backend/app/sections/__init__.py. Adding a section: a folder
    here with an index.ts exporting one of these, one line below, and its
    help entries in docs/HELP.md (ids start with the section id). */
export interface SectionDef {
  id: string;
  title: string;
  /** help id of the navigation button */
  helpId: string;
  adminOnly?: boolean;
  tabs: [string, string][];
  render: (tab: string, onTab: (t: string) => void) => ReactNode;
}

export const SECTIONS: SectionDef[] = [ledgerSection, familyMapSection];

export function sectionsFor(role: string): SectionDef[] {
  return SECTIONS.filter((s) => !s.adminOnly || role === 'admin');
}
