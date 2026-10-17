import { createElement } from 'react';
import type { SectionDef } from '../registry';
import { FAMILYMAP_TABS, FamilyMapAdmin, type FamilyMapTab } from './FamilyMapAdmin';
import './familymap.css';

/** FamilyMap's admin view. The family writes on their own page at /fm/
    (phone/, a second Vite entry); this is admin only. */
export const familyMapSection: SectionDef = {
  id: 'familymap',
  title: 'FamilyMap',
  helpId: 'nav.familymap',
  adminOnly: true,
  tabs: FAMILYMAP_TABS,
  render: (tab) => createElement(FamilyMapAdmin, {
    tab: (FAMILYMAP_TABS.some(([t]) => t === tab) ? tab : 'places') as FamilyMapTab,
  }),
};
