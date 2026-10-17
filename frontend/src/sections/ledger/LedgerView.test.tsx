import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { LedgerView } from './LedgerView';
import { kr, ledgerApi, monthLabel, type LedgerSummary, type LedgerAsk } from './api';
import { api } from '../../core/api';

const SUMMARY: LedgerSummary = {
  count: 3512, firstDate: '2023-01-02', lastDate: '2026-10-08',
  accounts: [{ account: 'Lønkonto', n: 3512, first: '2023-01-02', last: '2026-10-08' }],
  imports: [], merchants: 701, uncategorised: 0,
  categories: [{ key: 'home', label: 'Home & DIY', da: 'Bolig & byggemarked', counted: true },
               { key: 'transfers', label: 'Own transfers', da: 'Egne overførsler', counted: false }],
  settings: { model: 'qwen3.8:latest' },
  categorise: { state: 'none', left: 0 },
};

const ASK: LedgerAsk = {
  state: 'done', question: 'How much at Davidsens?', model: 'qwen3.8:latest',
  text: 'You paid **96.418,40 kr** to Davidsens Tømmerhandel in 31 payments.',
  counted: 'money out, matching "davidsens", in all data, own transfers left out',
  spec: { order: 'largest' },
  result: {
    count: 31, total: 96418.40, average: 3110.27, firstDate: '2023-03-08', lastDate: '2026-10-08',
    largest: 3110.27, groups: [], rowsShown: 1, matchedMerchants: [], excludedTransfers: null, notes: [],
    rows: [{ id: 1, account: 'Lønkonto', date: '2023-09-08', text: 'Betalingsservice DAVIDSENS TØMMERHANDEL A/S',
             amount: -3110.27, currency: 'DKK', kind: 'betalingsservice', merchantKey: 'davidsens',
             merchant: 'Davidsens Tømmerhandel', category: 'home', foreignAmount: null, foreignCurrency: null }],
  },
  steps: null,
};

describe('Økonomi', () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it('writes kroner the Danish way and months short', () => {
    expect(kr(9410.5)).toBe('9.410,50 kr');
    expect(kr(-1542.88)).toBe('−1.542,88 kr');
    expect(kr(13752.49, 0)).toBe('13.752 kr');
    expect(monthLabel('2026-03')).toBe('Mar 26');
  });

  it('asks to import first when the ledger is empty', async () => {
    vi.spyOn(ledgerApi, 'summary').mockResolvedValue({ ...SUMMARY, count: 0 });
    const onTab = vi.fn();
    render(<LedgerView tab="overview" onTab={onTab} />);
    fireEvent.click(await screen.findByText('Import a bank export'));
    expect(onTab).toHaveBeenCalledWith('import');
  });

  it('shows the answer with what the app counted and the rows behind it', async () => {
    vi.spyOn(ledgerApi, 'summary').mockResolvedValue(SUMMARY);
    vi.spyOn(ledgerApi, 'askState').mockResolvedValue(ASK);
    vi.spyOn(api, 'listOllamaModels').mockResolvedValue(['qwen3.8:latest']);
    const { container } = render(<LedgerView tab="ask" onTab={() => {}} />);
    expect(await screen.findByText('How much at Davidsens?')).toBeInTheDocument();
    await waitFor(() => expect(container.querySelector('.led-counted')?.textContent)
      .toContain('31 transactions, 96.418,40 kr'));
    expect(screen.getByText('The 1 largest of 31 matching transactions')).toBeInTheDocument();
    expect(screen.getByText('Davidsens Tømmerhandel')).toBeInTheDocument();
    expect(screen.getByText('−3.110,27 kr')).toBeInTheDocument();
  });

  it('sends a question and follows it until it is done', async () => {
    vi.spyOn(ledgerApi, 'summary').mockResolvedValue(SUMMARY);
    vi.spyOn(ledgerApi, 'askState').mockResolvedValueOnce({ state: 'none' }).mockResolvedValue(ASK);
    vi.spyOn(api, 'listOllamaModels').mockResolvedValue(['qwen3.8:latest']);
    const ask = vi.spyOn(ledgerApi, 'ask').mockResolvedValue({ ...ASK, state: 'working', text: '', result: null,
                                                                counted: null, step: 'Counting…' });
    render(<LedgerView tab="ask" onTab={() => {}} />);
    fireEvent.click(await screen.findByText('How much have I spent at Netto this year?'));
    expect(ask).toHaveBeenCalledWith('How much have I spent at Netto this year?', 'qwen3.8:latest');
    expect((await screen.findAllByText(/96\.418,40 kr/, {}, { timeout: 3000 })).length).toBeGreaterThan(0);
  });
});

describe('Økonomi overview (2.63.1)', () => {
  beforeEach(() => { vi.restoreAllMocks(); try { localStorage.clear(); } catch { /* */ } });

  const OV = {
    from: null, to: null, account: null, count: 10, firstDate: '2026-09-01', lastDate: '2026-09-30',
    spent: 3500, income: 0, otherIn: 1600, perMonth: 3500, transfersOut: 0, transfersIn: 0,
    months: [{ month: '2026-09', spent: 3500, income: 0, byCategory: { home: 3500 } }],
    days: [{ date: '2026-09-01', spent: 1000 }, { date: '2026-09-02', spent: 2500 }],
    baseline: { from: '2025-09', to: '2026-08', months: 12, perMonth: 2800, categories: { home: 2000 } },
    categories: [{ key: 'home', label: 'Home & DIY', spent: 3500, count: 2 }],
    topMerchants: Array.from({ length: 50 }, (_, i) => ({ key: `m${i}`, name: `Shop ${i}`, category: 'home',
                                                          spent: 100 - i, count: 1, last: '2026-09-02' })),
    recurring: [], uncategorised: 0,
  };

  it('steps through months, compares with the average month and lists 50 merchants', async () => {
    vi.spyOn(ledgerApi, 'summary').mockResolvedValue({ ...SUMMARY, firstDate: '2025-08-03', lastDate: '2026-10-08' });
    const ov = vi.spyOn(ledgerApi, 'overview').mockResolvedValue(OV);
    const { container } = render(<LedgerView tab="overview" onTab={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Month' }));
    await waitFor(() => expect(ov).toHaveBeenLastCalledWith('2026-10-01', '2026-10-31', '', 50, 12));
    fireEvent.click(screen.getByTitle('Month before'));
    await waitFor(() => expect(ov).toHaveBeenLastCalledWith('2026-09-01', '2026-09-30', '', 50, 12));
    expect(await screen.findByText('Money out per day - September 2026')).toBeInTheDocument();
    expect(screen.getByText('12 months before · this month +25%')).toBeInTheDocument();
    expect(screen.getByText('+ 1.600 kr other money in')).toBeInTheDocument();
    expect(screen.getByText('+1.500 kr')).toBeInTheDocument();           // home vs its average month
    expect(container.querySelectorAll('.led-top tbody tr').length).toBe(50);
    fireEvent.change(container.querySelector('.led-h3-row select')!, { target: { value: '100' } });
    await waitFor(() => expect(ov).toHaveBeenLastCalledWith('2026-09-01', '2026-09-30', '', 100, 12));
  });
});

describe('Økonomi model (FamilyLog 0.1.0)', () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it('offers the Settings model and sends none when it is chosen', async () => {
    vi.spyOn(ledgerApi, 'summary').mockResolvedValue({
      ...SUMMARY, settings: { model: 'gemma4:12b', override: '', chatRole: 'gemma4:12b', categoriseModel: 'gemma4:12b' } });
    vi.spyOn(ledgerApi, 'askState').mockResolvedValue({ state: 'none' });
    vi.spyOn(api, 'listOllamaModels').mockResolvedValue(['gemma4:12b', 'qwen3.6:27b']);
    const ask = vi.spyOn(ledgerApi, 'ask').mockResolvedValue({ state: 'queued', question: 'q' });
    render(<LedgerView tab="ask" onTab={() => {}} />);
    expect(await screen.findByRole('option', { name: 'Settings: gemma4:12b' })).toBeInTheDocument();
    fireEvent.click(await screen.findByText('How much have I spent at Netto this year?'));
    expect(ask).toHaveBeenCalledWith('How much have I spent at Netto this year?', undefined);
  });
});

