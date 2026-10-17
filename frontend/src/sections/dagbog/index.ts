import { createElement } from 'react';
import type { SectionDef } from '../registry';
import { DagbogAdmin } from './DagbogAdmin';
import './dagbog.css';

/** The Dagbog's settings (admin). The family writes their days on the
    front page (src/home); this is where the activity list and each
    person's fields are kept. */
export const dagbogSection: SectionDef = {
  id: 'dagbog',
  title: 'Dagbog',
  helpId: 'nav.dagbog',
  adminOnly: true,
  tabs: [['settings', 'Settings']],
  render: () => createElement(DagbogAdmin),
};
