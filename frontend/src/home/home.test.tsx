import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { homeApi, type ChatState, type DagbogConfig } from './api';
import { Shortcuts } from './HomeApp';
import { Chat } from './Chat';
import { DagbogPage, weekNumber } from './Dagbog';
import { addDays, dayTitle, face, mean, parseRoute, routeHash, weekStart } from './logic';

describe('front page logic', () => {
  it('routes', () => {
    expect(parseRoute('')).toEqual({ name: 'home' });
    expect(parseRoute('#/dagbog')).toEqual({ name: 'dagbog', day: null });
    expect(parseRoute('#/dagbog/2026-10-15')).toEqual({ name: 'dagbog', day: '2026-10-15' });
    expect(parseRoute('#/dagbog/familien/2026-10-12')).toEqual({ name: 'family', week: '2026-10-12' });
    expect(parseRoute('#/dagbog/x')).toEqual({ name: 'dagbog', day: null });
    expect(routeHash({ name: 'family', week: null })).toBe('#/dagbog/familien');
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

describe('shortcuts', () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it('a family account gets Atlas and Dagbog, not Økonomi', async () => {
    vi.spyOn(homeApi, 'mine').mockResolvedValue({ days: [] });
    render(<Shortcuts me={{ id: 3, username: 'barn', role: 'family' }} atlas="Alf’s Atlas" />);
    expect(screen.getByText('Alf’s Atlas').closest('a')).toHaveAttribute('href', '/fm/');
    expect(screen.getByText('Dagbog')).toBeInTheDocument();
    expect(screen.queryByText('Økonomi')).toBeNull();
    expect(await screen.findByText('Hvordan var i dag?')).toBeInTheDocument();
  });

  it('a grown-up also gets Økonomi, into the admin app', async () => {
    vi.spyOn(homeApi, 'mine').mockResolvedValue({ days: [new Date().toISOString().slice(0, 10)] });
    render(<Shortcuts me={{ id: 1, username: 'admin', role: 'admin' }} atlas="Alf’s Atlas" />);
    expect(screen.getByText('Økonomi').closest('a')).toHaveAttribute('href', '/app/#ledger');
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
    { key: 'mental', kind: 'scale', label: 'Mentalt overskud', low: 'Intet overskud', high: 'Masser af overskud' },
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
    fireEvent.click(screen.getByLabelText('Mentalt overskud 2'));
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
      day: '2026-10-17', mood: 4, mental: 2, alcohol: 2, foods: ['Hjemmelavet', 'Kage'],
      tags: ['Sport'], highlight: 'Mål!' }));
    expect(await screen.findByText('Gemt ✓')).toBeInTheDocument();
  });
});
