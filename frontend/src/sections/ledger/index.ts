import { createElement } from 'react';
import type { SectionDef } from '../registry';
import { LEDGER_TABS, LedgerView, type LedgerTab } from './LedgerView';
import './ledger.css';

/** Økonomi: each person's own bank and card transactions. */
export const ledgerSection: SectionDef = {
  id: 'ledger',
  title: 'Økonomi',
  helpId: 'nav.ledger',
  tabs: LEDGER_TABS,
  render: (tab, onTab) => createElement(LedgerView, {
    tab: (LEDGER_TABS.some(([t]) => t === tab) ? tab : 'overview') as LedgerTab,
    onTab: (t: LedgerTab) => onTab(t),
  }),
};
