import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { homeApi, type ChatState, type CyDayInfo, type CyOwn, type CyState, type DagbogConfig, type DagbogEntry, type DagbogStats, type OkOverview } from './api';
import { Shortcuts } from './HomeApp';
import { Chat } from './Chat';
import { DagbogPage, hoursText, weekNumber } from './Dagbog';
import { FamilyPage } from './DagbogFamily';
import { CyklusCalendar, CyklusDayPage, CyklusPage } from './Cyklus';
import { OkonomiPage } from './Okonomi';
import { addDays, addMonths, dayTitle, face, kr, longDate, mean, monthGrid, monthTitle, parseRoute, routeHash, todayLocal, weekStart } from './logic';

describe('front page logic', () => {
  it('routes', () => {
    expect(parseRoute('')).toEqual({ name: 'home' });
    expect(parseRoute('#/dagbog')).toEqual({ name: 'dagbog', day: null });
    expect(parseRoute('#/dagbog/2026-10-15')).toEqual({ name: 'dagbog', day: '2026-10-15' });
    expect(parseRoute('#/dagbog/familien/2026-10-12')).toEqual({ name: 'family', person: null });   // an old week link
    expect(parseRoute('#/dagbog/familien/4')).toEqual({ name: 'family', person: 4, stats: false });
    expect(parseRoute('#/dagbog/familien/4/statistik')).toEqual({ name: 'family', person: 4, stats: true });
    expect(routeHash({ name: 'family', person: 4, stats: true })).toBe('#/dagbog/familien/4/statistik');
    expect(parseRoute('#/dagbog/x')).toEqual({ name: 'dagbog', day: null });
    expect(routeHash({ name: 'family', person: null })).toBe('#/dagbog/familien');
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

  it('motion in hours', () => {
    expect([0, 30, 60, 90, 480].map(hoursText)).toEqual(['0 t', '½ t', '1 t', '1½ t', '8 t']);
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
      lastDate: null, uncategorised: 0, months: [], accounts: [], model: true, ask: null });
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
    expect(screen.getAllByText('Søparken').every((x) => x.closest('a')?.getAttribute('href') === '/fm/#/sted/7')).toBe(true);
  });

  it('links the place name itself, with one bracket or two (0.3.6)', async () => {
    vi.spyOn(homeApi, 'chat').mockResolvedValue({ ...STATE, messages: [STATE.messages[0],
      { ...STATE.messages[1], content: 'Her er pizza:\n\nSøparken [7] (0.5 km). Også **Søparken** [[7]].' }] });
    render(<Chat me={{ id: 1, username: 'mor', role: 'family' }} resetKey={0} />);
    const links = await screen.findAllByLabelText('Se Søparken');
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveTextContent('Søparken');
    expect(links[0]).toHaveAttribute('href', '/fm/#/sted/7');
    expect(screen.queryByText(/\[7\]/)).toBeNull();
    expect(screen.queryByText(/\*\*/)).toBeNull();
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
    { key: 'exercise', kind: 'slider', label: 'Motion', min: 0, max: 480, step: 30, unit: 'min', format: 'hours' },
    { key: 'foods', kind: 'foods', label: 'Mad', hint: 'Hvad spiste du i dag?' },
    { key: 'soda', kind: 'slider', label: 'Sodavand', min: 0, max: 10, step: 1, unit: 'glas' },
    { key: 'alcohol', kind: 'slider', label: 'Alkohol', min: 0, max: 20, step: 1, unit: 'genstande' },
    { key: 'tags', kind: 'tags', label: 'Aktiviteter' },
    { key: 'sick', kind: 'sick', label: 'Sygdom og skader', options: ['Feber', 'Skadet'] },
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
    const slider = screen.getByRole('slider', { name: 'Mentalt overskud' });     // a slider since 0.3.7
    expect(slider).toHaveAttribute('aria-valuetext', 'Ikke valgt');
    fireEvent.change(slider, { target: { value: '8' } });
    expect(slider).toHaveAttribute('aria-valuetext', '8 af 10');
    fireEvent.click(screen.getByText('Hjemmelavet'));
    fireEvent.click(screen.getByText('Kage'));
    expect(screen.queryByText('Søvn')).toBeNull();
    const motion = screen.getByRole('slider', { name: 'Motion' });       // half hours (0.3.8)
    expect(motion).toHaveAttribute('step', '30');
    fireEvent.change(motion, { target: { value: '90' } });
    expect(motion).toHaveAttribute('aria-valuetext', '1½ t');
    fireEvent.change(screen.getByRole('slider', { name: 'Alkohol' }), { target: { value: '2' } });
    fireEvent.click(screen.getByText('Sport'));
    fireEvent.click(screen.getByText('Feber'));
    fireEvent.change(screen.getByLabelText('Om sygdommen'), { target: { value: 'I seng' } });
    fireEvent.change(screen.getByPlaceholderText('Hvad var det bedste ved dagen?'), { target: { value: 'Mål!' } });
    // 0.3.9: the family sees the text and photo - unless she keeps the day to herself.
    const share = screen.getByRole('checkbox', { name: '👪 Familien kan se teksten og billedet' });
    expect(share).toBeChecked();
    fireEvent.click(share);
    expect(screen.getByText('🔒 Kun du kan se teksten og billedet')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Gem dagen'));
    await waitFor(() => expect(save).toHaveBeenCalledWith({
      day: '2026-10-17', mood: 4, mental: 8, alcohol: 2, exercise: 90, soda: null, foods: ['Hjemmelavet', 'Kage'],
      tags: ['Sport'], sick: ['Feber'], sickNote: 'I seng', highlight: 'Mål!', shared: false }));
    expect(await screen.findByText('Gemt ✓')).toBeInTheDocument();
  });

  it('a user account has no family: its text is its own', async () => {
    vi.spyOn(homeApi, 'dagbogConfig').mockResolvedValue(CONFIG);
    vi.spyOn(homeApi, 'entry').mockResolvedValue({ entry: null });
    render(<DagbogPage day="2026-10-17" role="user" />);
    expect(await screen.findByText('🔒 Kun du kan se teksten og billedet.')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).toBeNull();
  });
});

const ME = { id: 1, username: 'admin', role: 'admin' };
const MEMBERS = [{ id: 1, username: 'admin', fields: [] }, { id: 2, username: 'mor', fields: [] }];
const dayOf = (day: string, more: Partial<DagbogEntry> = {}): DagbogEntry => ({
  userId: 2, day, mood: 4, mental: 7, alcohol: 0, exercise: 60, soda: 1, foods: ['Vitaminer'], tags: ['Sport'],
  sick: [], sickNote: '', updatedAt: 'v', ...more });

describe('Dagbog → Familien (0.3.9)', () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it('a card per person with the last seven days and the newest text', async () => {
    const today = todayLocal();
    vi.spyOn(homeApi, 'family').mockResolvedValue({ from: addDays(today, -6), to: today, members: MEMBERS,
      entries: [dayOf(today, { mood: 5, highlight: 'Vi vandt' }), dayOf(addDays(today, -1), { mood: 3 })] });
    render(<FamilyPage me={ME} person={null} />);
    const mor = await screen.findByRole('link', { name: 'mor: åbn' });
    expect(mor).toHaveAttribute('href', '#/dagbog/familien/2');
    expect(mor.textContent).toContain('“Vi vandt”');
    expect(mor.textContent).toContain('4,0');                                 // her week's mood
    expect(screen.getByRole('link', { name: 'Mig: åbn' }).textContent).toContain('Intet i ugen');
  });

  it("a person's days with text and photo, going back a page at a time", async () => {
    const today = todayLocal();
    vi.spyOn(homeApi, 'family').mockResolvedValue({ from: today, to: today, members: MEMBERS, entries: [] });
    vi.spyOn(homeApi, 'personMonth').mockResolvedValue({ month: today.slice(0, 7), days: { [today]: 4 } });
    const person = vi.spyOn(homeApi, 'person')
      .mockResolvedValueOnce({ person: { id: 2, username: 'mor' }, own: false, fields: [], total: 3, firstDay: '2025-01-02',
        more: true, entries: [dayOf(today, { highlight: 'Vi vandt', hasPhoto: true, sick: ['Hoste'], sickNote: 'Lidt' })] })
      .mockResolvedValueOnce({ person: { id: 2, username: 'mor' }, own: false, fields: [], total: 3, firstDay: '2025-01-02',
        more: false, entries: [dayOf('2025-01-02', { mood: 2 })] });
    render(<FamilyPage me={ME} person={2} />);
    expect(await screen.findByText('Vi vandt')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /mor/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByAltText(/Billede fra/).getAttribute('src')).toContain('&user=2');
    expect(screen.getByText('🏃 1 t motion')).toBeInTheDocument();
    expect(screen.getByText('🤒 Hoste')).toBeInTheDocument();
    expect(screen.queryByText('Ret')).toBeNull();                               // not hers to edit
    fireEvent.click(screen.getByText('Hent ældre dage'));
    expect(await screen.findByText('Det var alle 3 dage - siden torsdag 2. jan.', { exact: false })).toBeInTheDocument();
    expect(person).toHaveBeenLastCalledWith(2, today);
    // The calendar jumps the list to a day.
    fireEvent.click(screen.getByRole('button', { name: /I dag, humør 4/ }));
    await waitFor(() => expect(person).toHaveBeenLastCalledWith(2, addDays(today, 1)));
  });

  it("a person's statistics", async () => {
    const today = todayLocal();
    vi.spyOn(homeApi, 'family').mockResolvedValue({ from: today, to: today, members: MEMBERS, entries: [] });
    const s: DagbogStats = { person: { id: 2, username: 'mor' }, from: null, to: null, days: 28,
      fields: ['mood', 'mental', 'exercise', 'tags', 'foods'], span: 28, coverage: 100, mood: 3.5, mental: 6,
      amounts: { exercise: { total: 840, days: 28, perDay: 30, perWeek: 210 }, alcohol: null,
                 soda: { total: 5, days: 2, perDay: 2.5, perWeek: null } }, sickDays: 0, bestStreak: 28,
      months: [{ month: '2026-09', days: 10, mood: 3, mental: 5, exerciseHours: 4, alcohol: 2 },
               { month: '2026-10', days: 18, mood: 4, mental: 7, exerciseHours: 8, alcohol: 0 }],
      weekdays: [4, 3, null, 3, 5, 4, 4], topTags: [{ name: 'Sport', days: 14 }], topFoods: [{ name: 'Vitaminer', days: 28 }],
      topSick: [], links: [{ label: 'Sport', kind: 'Aktivitet', with: 5, without: 2, diff: 3, days: 14 }] };
    const stats = vi.spyOn(homeApi, 'dagbogStats').mockResolvedValue(s);
    render(<FamilyPage me={ME} person={2} stats />);
    expect(await screen.findByText('Det følger med humøret')).toBeInTheDocument();
    expect(screen.getByText('Humør 5,0 med, 2,0 uden')).toBeInTheDocument();
    expect(screen.getByText('3½ t')).toBeInTheDocument();                       // 7 days or more: a week
    expect(screen.getByText('om ugen i snit')).toBeInTheDocument();
    expect(screen.queryByText('Alkohol')).toBeNull();                           // not one of her fields
    expect(screen.getByText('Vitaminer')).toBeInTheDocument();
    expect(stats).toHaveBeenLastCalledWith(2, addDays(today, -29));
    fireEvent.click(screen.getByRole('button', { name: 'Alt' }));
    await waitFor(() => expect(stats).toHaveBeenLastCalledWith(2, ''));
  });
});

const MONTH: OkOverview = {
  from: '2026-09-01', to: '2026-09-30', account: null, isMonth: true, perMonth: 12000, months: 1,
  count: 40, spent: 12000, income: 30000, otherIn: 0, transfersOut: 0,
  baselinePerMonth: 10000, baselineMonths: 6, days: null,
  categories: [{ key: 'groceries', name: 'Dagligvarer', spent: 5000, count: 20, usual: 4000 }],
  topMerchants: [{ key: 'netto', name: 'Netto', spent: 2500, count: 9, category: 'groceries', categoryName: 'Dagligvarer' }],
  recurring: [{ key: 'tryg', name: 'Forsikring', typical: 800, yearly: 9600, category: 'insurance', categoryName: 'Forsikring' }],
};
const OK_STATE = { access: true as const, own: true, owner: 'mor', count: 40, firstDate: '2025-10-01', lastDate: '2026-09-30',
  uncategorised: 2, months: ['2026-08', '2026-09'], accounts: ['Lønkonto', 'MasterCard'], model: true, ask: null };
const TX = { date: '2026-09-03', merchant: 'Netto', text: 'NETTO SKAGEN', amount: -120, category: 'groceries',
  categoryName: 'Dagligvarer', merchantKey: 'netto' };
const CATS = [{ key: 'rent', name: 'Husleje', group: 'Hus & bolig' }, { key: 'groceries', name: 'Dagligvarer', group: 'Mad' }];

describe('Økonomi on the phone', () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  beforeEach(() => { try { localStorage.clear(); } catch { /* */ } });

  it('shows the month against a usual one, then a year and one account', async () => {
    vi.spyOn(homeApi, 'okState').mockResolvedValue(OK_STATE);
    const ov = vi.spyOn(homeApi, 'okOverview').mockResolvedValue(MONTH);
    vi.spyOn(homeApi, 'okTx').mockResolvedValue({ total: 1, sum: -120, rows: [TX] });
    render(<OkonomiPage month={null} me={{ role: 'family' }} />);
    await waitFor(() => expect(ov).toHaveBeenCalledWith('2026-09-01', '2026-09-30', ''));  // the newest month first
    expect(await screen.findByText('20 % over en normal måned')).toBeInTheDocument();
    expect(screen.queryByText(/admin-appen/)).toBeNull();                // a family account has no admin app
    fireEvent.click(screen.getByText('Dagligvarer'));
    expect(await screen.findByLabelText('Posteringer: Dagligvarer')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Periode'), { target: { value: 'year' } });
    await waitFor(() => expect(ov).toHaveBeenCalledWith('2026-01-01', '2026-12-31', ''));
    fireEvent.change(screen.getByLabelText('Konto'), { target: { value: 'MasterCard' } });
    await waitFor(() => expect(ov).toHaveBeenCalledWith('2026-01-01', '2026-12-31', 'MasterCard'));
  });

  it('searches transactions and moves a shop to another category', async () => {
    vi.spyOn(homeApi, 'okState').mockResolvedValue(OK_STATE);
    vi.spyOn(homeApi, 'okOverview').mockResolvedValue(MONTH);
    const tx = vi.spyOn(homeApi, 'okTx').mockResolvedValue({ total: 1, sum: -120, rows: [TX] });
    vi.spyOn(homeApi, 'okMerchants').mockResolvedValue({ merchants: [], categories: CATS });
    const set = vi.spyOn(homeApi, 'okSetMerchant').mockResolvedValue({ ok: true });
    render(<OkonomiPage month={null} me={{ role: 'admin' }} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Posteringer' }));
    fireEvent.change(screen.getByLabelText('Søg i posteringer'), { target: { value: 'netto' } });
    await waitFor(() => expect(tx).toHaveBeenCalledWith(expect.objectContaining({ q: 'netto', frm: '2026-09-01' })));
    fireEvent.click(await screen.findByLabelText(/Netto -120,00 kr - Dagligvarer/));
    fireEvent.change(await screen.findByLabelText('Kategori for butikken'), { target: { value: 'rent' } });
    fireEvent.click(screen.getByText('Gem'));
    await waitFor(() => expect(set).toHaveBeenCalledWith('netto', { category: 'rent' }));
  });

  it('lists the shops and shows the months side by side', async () => {
    vi.spyOn(homeApi, 'okState').mockResolvedValue(OK_STATE);
    vi.spyOn(homeApi, 'okOverview').mockResolvedValue(MONTH);
    vi.spyOn(homeApi, 'okMerchants').mockResolvedValue({ categories: CATS, merchants: [{ key: 'netto', name: 'Netto',
      category: 'groceries', categoryName: 'Dagligvarer', source: 'rule', sample: 'NETTO', count: 9, total: -2500, last: '2026-09-03' }] });
    vi.spyOn(homeApi, 'okTrend').mockResolvedValue({ categories: [{ key: 'groceries', name: 'Dagligvarer', spent: 9000 }],
      months: [{ month: '2026-08', spent: 9000, income: 30000, byCategory: { groceries: 4000 } },
               { month: '2026-09', spent: 12000, income: 30000, byCategory: { groceries: 5000 } }] });
    render(<OkonomiPage month={null} me={{ role: 'admin' }} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Butikker' }));
    expect(await screen.findByText('Netto')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Udvikling' }));
    expect(await screen.findByText(/Alt forbrug: 10.500 kr pr. måned i snit/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Hvad'), { target: { value: 'groceries' } });
    expect(await screen.findByText(/Dagligvarer: 4.500 kr pr. måned i snit/)).toBeInTheDocument();
  });

  it('says so when there is no access', async () => {
    vi.spyOn(homeApi, 'okState').mockResolvedValue({ access: false });
    render(<OkonomiPage month={null} />);
    expect(await screen.findByText('Du har ikke Økonomi.')).toBeInTheDocument();
  });

  it('an empty Økonomi starts with reading in a bank export, then places the shops', async () => {
    vi.spyOn(homeApi, 'okState').mockResolvedValue({ access: true, own: true, owner: 'mor', count: 0,
      firstDate: null, lastDate: null, uncategorised: 0, months: [], accounts: [], model: false, ask: null });
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
