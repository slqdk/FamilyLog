import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { homeApi, type ChatState, type CyDayInfo, type CyOwn, type CyState, type DagbogConfig, type OkMonth } from './api';
import { Shortcuts } from './HomeApp';
import { Chat } from './Chat';
import { DagbogPage, weekNumber } from './Dagbog';
import { CyklusCalendar, CyklusDayPage, CyklusPage } from './Cyklus';
import { OkonomiPage } from './Okonomi';
import { addDays, addMonths, dayTitle, face, kr, longDate, mean, monthGrid, monthTitle, parseRoute, routeHash, todayLocal, weekStart } from './logic';

describe('front page logic', () => {
  it('routes', () => {
    expect(parseRoute('')).toEqual({ name: 'home' });
    expect(parseRoute('#/dagbog')).toEqual({ name: 'dagbog', day: null });
    expect(parseRoute('#/dagbog/2026-10-15')).toEqual({ name: 'dagbog', day: '2026-10-15' });
    expect(parseRoute('#/dagbog/familien/2026-10-12')).toEqual({ name: 'family', week: '2026-10-12' });
    expect(parseRoute('#/dagbog/x')).toEqual({ name: 'dagbog', day: null });
    expect(routeHash({ name: 'family', week: null })).toBe('#/dagbog/familien');
    expect(parseRoute('#/okonomi/2026-09')).toEqual({ name: 'okonomi', month: '2026-09' });
    expect(parseRoute('#/okonomi/2026-13')).toEqual({ name: 'okonomi', month: null });
    expect(parseRoute('#/cyklus/dag/2026-10-17')).toEqual({ name: 'cyklusDay', day: '2026-10-17' });
    expect(parseRoute('#/cyklus/kalender')).toEqual({ name: 'cyklusCal', month: null });
    expect(parseRoute('#/cyklus/deling')).toEqual({ name: 'cyklusShare' });
    expect(routeHash({ name: 'cyklusCal', month: '2026-11' })).toBe('#/cyklus/kalender/2026-11');
  });

  it('months and money', () => {
    expect(addMonths('2026-12', 1)).toBe('2027-01');
    expect(addMonths('2026-01', -1)).toBe('2025-12');
    expect(monthTitle('2026-10')).toBe('Oktober 2026');
    const g = monthGrid('2026-10');                        // 1 October 2026 is a Thursday
    expect(g.slice(0, 4)).toEqual([null, null, null, '2026-10-01']);
    expect(g.filter(Boolean)).toHaveLength(31);
    expect(kr(12345.6).replace(/\s/g, ' ')).toBe('12.346 kr');
    expect(kr(-9.5, true).replace(/\s/g, ' ')).toBe('-9,50 kr');
  });

  it('counts days and weeks in local time', () => {
    expect(addDays('2026-10-31', 1)).toBe('2026-11-01');
    expect(addDays('2026-03-01', -1)).toBe('2026-02-28');
    expect(weekStart('2026-10-17')).toBe('2026-10-12');          // a Saturday -> Monday
    expect(weekStart('2026-10-12')).toBe('2026-10-12');
    expect(weekNumber('2026-10-12')).toBe(42);
    expect(weekNumber('2027-01-01')).toBe(53);
    expect(dayTitle('2026-10-17', '2026-10-17')).toBe('I dag');
    expect(dayTitle('2026-10-16', '2026-10-17')).toBe('I går');
    expect(dayTitle('2026-10-15', '2026-10-17')).toBe('Torsdag 15. okt');
  });

  it('averages and faces', () => {
    expect(mean([4, null, 2, undefined])).toBe(3);
    expect(mean([null])).toBeNull();
    expect(face(5)).toBe('😄');
    expect(face(2.6)).toBe('😐');
    expect(face(null)).toBe('·');
  });
});

const NO_CY: CyState = { enabled: false, shared: [], options: { flows: [], symptoms: [], moods: [], disclaimer: '', phases: {} } };

describe('shortcuts', () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it('a family account without access gets Atlas and Dagbog only', async () => {
    vi.spyOn(homeApi, 'mine').mockResolvedValue({ days: [] });
    vi.spyOn(homeApi, 'okState').mockResolvedValue({ access: false });
    vi.spyOn(homeApi, 'cyState').mockResolvedValue(NO_CY);
    render(<Shortcuts me={{ id: 3, username: 'barn', role: 'family' }} atlas="Alf’s Atlas" />);
    expect(screen.getByText('Alf’s Atlas').closest('a')).toHaveAttribute('href', '/fm/');
    expect(screen.getByText('Dagbog')).toBeInTheDocument();
    expect(await screen.findByText('Hvordan var i dag?')).toBeInTheDocument();
    expect(screen.queryByText('Økonomi')).toBeNull();
    expect(screen.queryByText('Cyklus')).toBeNull();
  });

  it('Økonomi opens the phone page for a family account with its own Økonomi', async () => {
    vi.spyOn(homeApi, 'mine').mockResolvedValue({ days: [] });
    vi.spyOn(homeApi, 'okState').mockResolvedValue({ access: true, own: false, owner: 'far', count: 3, firstDate: null,
      lastDate: null, uncategorised: 0, months: [], model: true, ask: null });
    vi.spyOn(homeApi, 'cyState').mockResolvedValue(NO_CY);
    render(<Shortcuts me={{ id: 3, username: 'mor', role: 'family' }} atlas="Alf’s Atlas" />);
    expect((await screen.findByText('Økonomi')).closest('a')).toHaveAttribute('href', '#/okonomi');
    expect(screen.getByText('Konti og forbrug')).toBeInTheDocument();
  });

  it('Cyklus shows her cycle day, or what is shared with you', async () => {
    vi.spyOn(homeApi, 'mine').mockResolvedValue({ days: [] });
    vi.spyOn(homeApi, 'okState').mockResolvedValue({ access: false });
    vi.spyOn(homeApi, 'cyState').mockResolvedValue({ ...NO_CY, shared: [{ id: 2, name: 'mor', today: '2026-10-17',
      empty: false, shareFertile: false, shareDetails: false, phase: 'pms', phaseLabel: 'PMS-dage', cycleDay: 25 }] });
    render(<Shortcuts me={{ id: 1, username: 'far', role: 'user' }} atlas="Alf’s Atlas" />);
    expect((await screen.findByText('Cyklus')).closest('a')).toHaveAttribute('href', '#/cyklus');
    expect(screen.getByText('mor: pms-dage')).toBeInTheDocument();
  });
});

const STATE: ChatState = {
  model: true, job: null,
  messages: [
    { id: 1, role: 'user', content: 'Find en legeplads', places: [], createdAt: '', meta: {} },
    { id: 2, role: 'assistant', content: 'Prøv Søparken [[7]] - den er god.', createdAt: '',
      meta: { route: 'places', searched: 'Legeplads' },
      places: [{ id: 7, name: 'Søparken', category: 'playground', address: 'Vojens', familyScore: 88,
                 reviewCount: 1, coverPhotoId: null, distanceKm: 1.2, source: 'family', wished: false,
                 latestText: null }] },
  ],
};

describe('Alf on the front page', () => {
  beforeEach(() => { vi.restoreAllMocks(); try { localStorage.clear(); } catch { /* */ } });

  it('shows the conversation with places linked into the Atlas', async () => {
    vi.spyOn(homeApi, 'chat').mockResolvedValue(STATE);
    render(<Chat me={{ id: 1, username: 'mor', role: 'family' }} resetKey={0} />);
    expect(await screen.findByText('Find en legeplads')).toBeInTheDocument();
    expect(screen.getByLabelText('Se Søparken')).toHaveAttribute('href', '/fm/#/sted/7');
    fireEvent.click(screen.getByText('Vis stedet'));
    expect(screen.getByText('Søparken').closest('a')).toHaveAttribute('href', '/fm/#/sted/7');
  });

  it('sends a message from an example and says when there is no model', async () => {
    vi.spyOn(homeApi, 'chat').mockResolvedValue({ model: false, job: null, messages: [] });
    const send = vi.spyOn(homeApi, 'chatSend').mockResolvedValue({
      model: true, messages: [{ id: 1, role: 'user', content: 'Hvad skal vi lave i weekenden?', places: [], createdAt: '', meta: {} }],
      job: { state: 'queued', step: 'Venter på sin tur…', phase: 'queue', text: '', places: [], error: null,
             route: null, searched: null, where: null } });
    render(<Chat me={{ id: 1, username: 'mor', role: 'family' }} resetKey={0} />);
    expect(await screen.findByText(/ingen model endnu/)).toBeInTheDocument();
    fireEvent.click(screen.getByText('Hvad skal vi lave i weekenden?'));
    await waitFor(() => expect(send).toHaveBeenCalledWith('Hvad skal vi lave i weekenden?', null));
    expect(await screen.findByText('Venter på sin tur…')).toBeInTheDocument();
  });
});

const CONFIG: DagbogConfig = {
  today: '2026-10-17', maxDaysBack: 366, tags: ['Sport', 'Venner'], foods: ['Hjemmelavet', 'Kage', 'Chips'],
  fields: [
    { key: 'mood', kind: 'scale', label: 'Humør', low: 'Rigtig skidt', high: 'Rigtig godt', faces: ['😞', '🙁', '😐', '🙂', '😄'] },
    { key: 'mental', kind: 'scale', label: 'Mentalt overskud', low: 'Intet overskud', high: 'Masser af overskud', max: 10 },
    { key: 'foods', kind: 'foods', label: 'Mad', hint: 'Hvad spiste du i dag?' },
    { key: 'alcohol', kind: 'count', label: 'Alkohol', unit: 'genstande', max: 30 },
    { key: 'tags', kind: 'tags', label: 'Aktiviteter' },
    { key: 'highlight', kind: 'private', label: 'Dagens højdepunkt' },
  ],
};

describe('Dagbog', () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it('fills in a day and saves only what was touched', async () => {
    vi.spyOn(homeApi, 'dagbogConfig').mockResolvedValue(CONFIG);
    vi.spyOn(homeApi, 'entry').mockResolvedValue({ entry: null });
    const save = vi.spyOn(homeApi, 'saveEntry').mockImplementation(async (b) => ({
      entry: { userId: 1, mood: null, mental: null, alcohol: null, foods: [],
               tags: [], updatedAt: 'x', highlight: '', hasPhoto: false, ...b } as never }));
    render(<DagbogPage day="2026-10-17" />);
    fireEvent.click(await screen.findByLabelText('Humør 4'));
    expect(screen.getAllByRole('radio', { name: /^Mentalt overskud \d+$/ })).toHaveLength(10);
    fireEvent.click(screen.getByLabelText('Mentalt overskud 8'));
    fireEvent.click(screen.getByText('Hjemmelavet'));
    fireEvent.click(screen.getByText('Kage'));
    expect(screen.queryByText('Søvn')).toBeNull();
    fireEvent.click(screen.getByLabelText('Flere'));
    fireEvent.click(screen.getByLabelText('Flere'));
    fireEvent.click(screen.getByText('Sport'));
    fireEvent.change(screen.getByPlaceholderText('Hvad var det bedste ved dagen?'), { target: { value: 'Mål!' } });
    expect(screen.getByText('🔒 Kun du kan se teksten og billedet.')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Gem dagen'));
    await waitFor(() => expect(save).toHaveBeenCalledWith({
      day: '2026-10-17', mood: 4, mental: 8, alcohol: 2, foods: ['Hjemmelavet', 'Kage'],
      tags: ['Sport'], highlight: 'Mål!' }));
    expect(await screen.findByText('Gemt ✓')).toBeInTheDocument();
  });
});

const MONTH: OkMonth = {
  month: '2026-09', count: 40, spent: 12000, income: 30000, otherIn: 0, transfersOut: 0,
  baselinePerMonth: 10000, baselineMonths: 6, days: null,
  categories: [{ key: 'groceries', name: 'Dagligvarer', spent: 5000, count: 20, usual: 4000 }],
  topMerchants: [{ key: 'netto', name: 'Netto', spent: 2500, count: 9, categoryName: 'Dagligvarer' }],
  recurring: [{ name: 'Forsikring', typical: 800, yearly: 9600, categoryName: 'Forsikring' }],
};

describe('Økonomi on the phone', () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it('shows the month against a usual one', async () => {
    vi.spyOn(homeApi, 'okState').mockResolvedValue({ access: true, own: true, owner: 'mor', count: 40,
      firstDate: '2026-08-01', lastDate: '2026-09-30', uncategorised: 2, months: ['2026-08', '2026-09'], model: true, ask: null });
    const month = vi.spyOn(homeApi, 'okMonth').mockResolvedValue(MONTH);
    vi.spyOn(homeApi, 'okTx').mockResolvedValue({ total: 1, sum: -120, rows: [{ date: '2026-09-03', merchant: 'Netto',
      text: 'NETTO', amount: -120, category: 'groceries', categoryName: 'Dagligvarer', merchantKey: 'netto' }] });
    render(<OkonomiPage month={null} me={{ role: 'family' }} />);
    await waitFor(() => expect(month).toHaveBeenCalledWith('2026-09'));  // the newest month first
    expect(await screen.findByText('20 % over en normal måned')).toBeInTheDocument();
    expect(screen.queryByText(/admin-appen/)).toBeNull();                // a family account has no admin app
    fireEvent.click(screen.getByText('Dagligvarer'));
    expect(await screen.findByLabelText('Posteringer: Dagligvarer')).toBeInTheDocument();
  });

  it('says so when there is no access', async () => {
    vi.spyOn(homeApi, 'okState').mockResolvedValue({ access: false });
    render(<OkonomiPage month={null} />);
    expect(await screen.findByText('Du har ikke Økonomi.')).toBeInTheDocument();
  });

  it('an empty Økonomi starts with reading in a bank export, then places the shops', async () => {
    vi.spyOn(homeApi, 'okState').mockResolvedValue({ access: true, own: true, owner: 'mor', count: 0,
      firstDate: null, lastDate: null, uncategorised: 0, months: [], model: false, ask: null });
    const data = { imports: [], accounts: [], count: 0, left: 1, model: false,
      uncategorised: [{ key: 'zxq', name: 'Zxq Butik', sample: 'ZXQ', count: 2, total: -300 }],
      categorise: { state: 'none', left: 1 }, categories: [{ key: 'rent', name: 'Husleje', group: 'Hus & bolig' }, { key: 'groceries', name: 'Dagligvarer', group: 'Mad' }] };
    vi.spyOn(homeApi, 'okData').mockResolvedValue(data);
    const imp = vi.spyOn(homeApi, 'okImport').mockResolvedValue({ added: 12, alreadyThere: 0, rowsInFile: 12, uncategorised: 1, skipped: 0 });
    const place = vi.spyOn(homeApi, 'okSetCategory').mockResolvedValue({ ok: true });
    render(<OkonomiPage month={null} me={{ role: 'family' }} />);
    expect(await screen.findByText('Kom i gang')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Konto'), { target: { value: 'Lønkonto' } });
    const file = new File(['x'], 'eksport.csv', { type: 'text/csv' });
    fireEvent.change(document.querySelector('.ok-pick input[type=file]')!, { target: { files: [file] } });
    await waitFor(() => expect(imp).toHaveBeenCalledWith(file, 'Lønkonto'));
    expect(await screen.findByText('12 nye posteringer.')).toBeInTheDocument();
    const pick = screen.getByLabelText('Kategori for Zxq Butik');
    expect([...pick.querySelectorAll('optgroup')].map((g) => g.getAttribute('label'))).toEqual(['Hus & bolig', 'Mad']);
    fireEvent.change(pick, { target: { value: 'groceries' } });
    await waitFor(() => expect(place).toHaveBeenCalledWith('zxq', 'groceries'));
  });
});

const OPTIONS = { flows: [{ key: 'let', label: 'Let' }, { key: 'kraftig', label: 'Kraftig' }],
  symptoms: ['Kramper', 'Hovedpine'], moods: ['Glad', 'Irritabel'], disclaimer: 'Ikke prævention.', phases: {} };
const OWN: CyOwn = {
  status: { empty: false, today: '2026-10-17', cycleDay: 20, phase: 'luteal', phaseLabel: 'Lutealfase',
    phaseText: 'Energien falder ofte lidt.', inPeriod: false, periodDay: null, nextStart: '2026-10-26', daysUntilNext: 9,
    late: 0, ovulation: '2026-11-09', fertileFrom: '2026-11-04', fertileTo: '2026-11-10', fertileToday: false,
    lastStart: '2026-09-28', lastOpen: false,
    averages: { cycle: 28, cycleSource: 'målt', period: 5, cyclesMeasured: 2, spread: 0, regular: null, history: [28, 28] } },
  forecast: [], patterns: { luteal: { label: 'Lutealfase', days: 4, top: [{ name: 'Træt', count: 3 }], mood: 3.2, mental: null } },
  periods: [{ id: 1, start: '2026-09-28', end: '2026-10-02', periodDays: 5, cycleLength: null }],
  settings: { cycleLength: null, periodLength: null, shareFertile: false, shareDetails: false, viewers: [] },
  today: { day: '2026-10-17', flow: '', symptoms: [], moods: [], note: '' },
};

const TODAY = todayLocal();
const INFO: CyDayInfo = { day: TODAY, past: false, isToday: true, kind: '', cycleDay: 20, phase: 'luteal',
  title: 'Cyklusdag 20', sub: 'Cyklusdag 20 · Lutealfase', phaseLabel: 'Lutealfase', text: 'Energien falder ofte lidt.',
  chance: 'lav', chanceLabel: 'Lav', nextPeriodIn: 9, log: null,
  forecast: { items: [{ key: 'energy', label: 'Energi', value: 3, source: 'typisk' }, { key: 'mood', label: 'Humør', value: 4, source: 'dagbog' }],
    expect: ['Oppustet'], expectSource: 'typisk', behaviour: 'Roligere tempo.' } };

describe('Cyklus', () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it('her own page: the countdown, the day explained and a period start', async () => {
    vi.spyOn(homeApi, 'cyState').mockResolvedValue({ enabled: true, shared: [], options: OPTIONS, own: OWN });
    vi.spyOn(homeApi, 'cyCalendar').mockResolvedValue({ days: [] });
    const info = vi.spyOn(homeApi, 'cyDayInfo').mockImplementation(async (day) => ({ ...INFO, day,
      title: day === TODAY ? 'Cyklusdag 20' : 'Menstruation ventes' }));
    const start = vi.spyOn(homeApi, 'cyStart').mockResolvedValue({ ...OWN,
      status: { ...OWN.status, inPeriod: true, periodDay: 1, cycleDay: 1, phase: 'menstruation' } });
    render(<CyklusPage />);
    expect(await screen.findByText('Menstruation om 9 dage')).toBeInTheDocument();
    expect(await screen.findByText('Humør og adfærd i dag')).toBeInTheDocument();
    expect(screen.getByText('Chance for graviditet')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Energi 3 af 5' })).toBeInTheDocument();
    // Tapping a coming day explains that day instead.
    const later = addDays(TODAY, 9);
    fireEvent.click(screen.getAllByRole('button', { pressed: false }).find((b) => b.getAttribute('aria-label')?.startsWith(dayTitle(later, TODAY)))!);
    await waitFor(() => expect(info).toHaveBeenCalledWith(later));
    expect(await screen.findByText('Menstruation ventes')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Tilbage til i dag'));
    expect(screen.getByText('Ikke prævention.')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Menstruationen startede i dag'));
    await waitFor(() => expect(start).toHaveBeenCalled());
    expect(await screen.findByText('Menstruationsdag 1')).toBeInTheDocument();
  });

  it('someone she shares with taps a coming day for its prediction and mood', async () => {
    vi.spyOn(homeApi, 'cyState').mockResolvedValue({ enabled: false, options: OPTIONS, shared: [{
      id: 2, name: 'mor', today: TODAY, empty: false, shareFertile: false, shareDetails: false,
      cycleDay: 20, phase: 'luteal', phaseLabel: 'Lutealfase', phaseText: 'Energien kan være lidt lavere.',
      inPeriod: false, periodDay: null, nextStart: addDays(TODAY, 9), daysUntilNext: 9, late: 0,
      week: [], forecast: INFO.forecast }] });
    vi.spyOn(homeApi, 'cySharedCalendar').mockResolvedValue({ days: [{ day: addDays(TODAY, 5), kind: 'pms' }] });
    const sd = vi.spyOn(homeApi, 'cySharedDay').mockResolvedValue({ day: addDays(TODAY, 5), isToday: false, kind: 'pms',
      cycleDay: 25, phase: 'pms', title: 'PMS-dag', sub: 'Cyklusdag 25 · PMS-dage', phaseLabel: 'PMS-dage',
      text: 'PMS er sandsynlig.', nextPeriodIn: 4,
      forecast: { items: [{ key: 'patience', label: 'Tålmodighed', value: 2, source: 'typisk' }], expect: ['Irritabel'],
        expectSource: 'typisk', behaviour: 'Kortere lunte.' } });
    render(<CyklusPage />);
    expect(await screen.findByText('mor i dag: humør og adfærd')).toBeInTheDocument();
    const later = addDays(TODAY, 5);
    fireEvent.click(await screen.findByLabelText(`${dayTitle(later, TODAY)}: PMS`));
    await waitFor(() => expect(sd).toHaveBeenCalledWith(2, later));
    expect(await screen.findByText('PMS-dag')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Tålmodighed 2 af 5' })).toBeInTheDocument();
    expect(screen.queryByText(/chance for graviditet/)).toBeNull();
  });

  it('a shared card shows what she shares and nothing else', async () => {
    vi.spyOn(homeApi, 'cyState').mockResolvedValue({ enabled: false, options: OPTIONS, shared: [{
      id: 2, name: 'mor', today: '2026-10-17', empty: false, shareFertile: false, shareDetails: false,
      cycleDay: 25, phase: 'pms', phaseLabel: 'PMS-dage', phaseText: 'Lidt ekstra tålmodighed hjælper.',
      inPeriod: false, periodDay: null, nextStart: '2026-10-21', daysUntilNext: 4, late: 0,
      week: [{ day: '2026-10-17', kind: 'pms' }] }] });
    vi.spyOn(homeApi, 'cySharedCalendar').mockResolvedValue({ days: [] });
    render(<CyklusPage />);
    expect(await screen.findByText('Menstruation om 4 dage')).toBeInTheDocument();
    expect(screen.getByText('PMS-dage')).toBeInTheDocument();
    expect(screen.queryByText(/Frugtbare/)).toBeNull();
    expect(screen.queryByText('Menstruationen startede i dag')).toBeNull();
  });

  it('the calendar: tap a day for its sheet, edit periods day by day, a year at a glance', async () => {
    vi.spyOn(homeApi, 'cyCalendar').mockResolvedValue({ days: [{ day: TODAY, kind: 'period', cycleDay: 1, flow: '', logged: false }] });
    vi.spyOn(homeApi, 'cyDayInfo').mockResolvedValue({ ...INFO, title: 'Menstruationsdag 1', cycleDay: 1 });
    const toggle = vi.spyOn(homeApi, 'cyToggle').mockResolvedValue(OWN);
    render(<CyklusCalendar month={null} />);
    const day = await screen.findByLabelText(`${longDate(TODAY)}: menstruation`);
    fireEvent.click(day);
    expect(await screen.findByText('Menstruationsdag 1')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Luk'));
    fireEvent.click(screen.getByText('Rediger menstruationsdatoer'));
    fireEvent.click(screen.getByLabelText(`${longDate(TODAY)}: menstruation`));
    await waitFor(() => expect(toggle).toHaveBeenCalledWith(TODAY));
    fireEvent.click(screen.getByText('Færdig'));
    fireEvent.click(screen.getByRole('tab', { name: 'År' }));
    expect(await screen.findByLabelText(monthTitle(TODAY.slice(0, 7)))).toBeInTheDocument();
  });

  it('logs a day', async () => {
    vi.spyOn(homeApi, 'cyState').mockResolvedValue({ enabled: true, shared: [], options: OPTIONS, own: OWN });
    vi.spyOn(homeApi, 'cyDay').mockResolvedValue({ day: { day: '2026-10-15', flow: '', symptoms: [], moods: [], note: '' } });
    const save = vi.spyOn(homeApi, 'cySaveDay').mockImplementation(async (d) => ({ ...OWN, today: { note: '', ...d } as never }));
    render(<CyklusDayPage day="2026-10-15" />);
    fireEvent.click(await screen.findByText('Kraftig'));
    fireEvent.click(screen.getByText('Kramper'));
    fireEvent.click(screen.getByText('Irritabel'));
    fireEvent.click(screen.getByText('Gem dagen'));
    await waitFor(() => expect(save).toHaveBeenCalledWith({ day: '2026-10-15', flow: 'kraftig',
      symptoms: ['Kramper'], moods: ['Irritabel'], note: '' }));
  });
});
