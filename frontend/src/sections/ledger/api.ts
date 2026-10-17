import type { StepsPayload } from '../../core/types';

/** Økonomi (2.63.0): the person's own bank and card transactions. Every
    number on these pages is computed by the backend in SQL; the model only
    turns a question into a search and writes up the result. */

export interface LedgerCategory { key: string; label: string; da: string; counted: boolean; group?: string }
export interface LedgerImport {
  id: number; account: string; filename: string; importedAt: string; rowsInFile: number;
  added: number; alreadyThere: number; firstDate: string | null; lastDate: string | null;
}
export interface CategoriseState {
  state: 'none' | 'queued' | 'working' | 'done' | 'failed' | 'stopped';
  left: number; total?: number; placed?: number; batches?: number; model?: string;
  error?: string | null; ahead?: number;
}
export interface LedgerSummary {
  count: number; firstDate: string | null; lastDate: string | null;
  accounts: { account: string; n: number; first: string; last: string }[];
  imports: LedgerImport[]; merchants: number; uncategorised: number;
  categories: LedgerCategory[];
  /** model = what questions use; override = this person's own choice ('' = the
      roles in Settings; FamilyLog 0.1.0); categoriseModel = what categorising uses. */
  settings: { model: string; override?: string; categoriseModel?: string; chatRole?: string };
  categorise: CategoriseState;
}
export interface LedgerMonth { month: string; spent: number; income: number; byCategory: Record<string, number> }
export interface LedgerOverview {
  from: string | null; to: string | null; account: string | null;
  count: number; firstDate: string | null; lastDate: string | null;
  spent: number; income: number; otherIn: number; perMonth: number; transfersOut: number; transfersIn: number;
  months: LedgerMonth[];
  /** Per day, for a period of up to two months (the Month view). */
  days: { date: string; spent: number }[] | null;
  /** Average month before the period, per category (Month view). */
  baseline: { from: string; to: string; months: number; perMonth: number;
              categories: Record<string, number> } | null;
  categories: { key: string; label: string; spent: number; count: number }[];
  topMerchants: { key: string; name: string; category: string; spent: number; count: number; last: string }[];
  recurring: { key: string; name: string; category: string; months: number; typical: number; last: string; yearly: number }[];
  uncategorised: number;
}
export interface LedgerTx {
  id: number; account: string; date: string; text: string; amount: number; currency: string;
  kind: string; merchantKey: string; merchant: string; category: string;
  foreignAmount: number | null; foreignCurrency: string | null;
}
export interface LedgerMerchant {
  key: string; name: string; category: string; source: string; sample: string;
  count: number; total: number; last: string | null;
}
export interface LedgerImportResult {
  importId: number; account: string; rowsInFile: number; added: number; alreadyThere: number;
  firstDate: string; lastDate: string; newUncategorised: number; uncategorised: number;
  skipped: number; categorise?: CategoriseState;
}
export interface LedgerAskResult {
  count: number; total: number; average: number | null; firstDate: string | null; lastDate: string | null;
  largest: number;
  groups: { group: string; count: number; total: number; average: number }[];
  rows: LedgerTx[]; rowsShown: number;
  matchedMerchants: { name: string; count: number }[];
  excludedTransfers: { count: number; sum: number } | null;
  notes: string[];
}
export interface LedgerAsk {
  state: 'none' | 'queued' | 'working' | 'done' | 'failed' | 'stopped';
  question?: string; model?: string; step?: string; text?: string; counted?: string | null;
  spec?: Record<string, unknown> | null; result?: LedgerAskResult | null; error?: string | null;
  previous?: string | null; ahead?: number; steps?: StepsPayload | null;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { const b = await res.json(); if (b?.detail) detail = String(b.detail); } catch { /* */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}
const send = (method: string, body?: unknown) => ({
  method, headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
});
const qs = (p: Record<string, string | number | undefined | null>) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== null && v !== '') u.set(k, String(v));
  return u.toString();
};

export const ledgerApi = {
  summary: () => fetch('/api/ledger/summary').then(json<LedgerSummary>),
  overview: (frm: string, to: string, account: string, top = 50, baseline = 0) =>
    fetch(`/api/ledger/overview?${qs({ frm, to, account, top, baseline: baseline || undefined })}`)
      .then(json<LedgerOverview>),
  transactions: (p: { q?: string; category?: string; merchant?: string; frm?: string; to?: string;
                      account?: string; direction?: string; order?: string; offset?: number; limit?: number }) =>
    fetch(`/api/ledger/transactions?${qs(p)}`).then(json<{ total: number; sum: number; rows: LedgerTx[] }>),
  merchants: (q: string, category: string) =>
    fetch(`/api/ledger/merchants?${qs({ q, category, limit: 1000 })}`).then(json<LedgerMerchant[]>),
  setMerchant: (key: string, change: { category?: string; name?: string }) =>
    fetch('/api/ledger/merchants', send('PUT', { key, ...change })).then(json<{ ok: boolean }>),
  importFile: (file: File, account: string) => {
    const fd = new FormData();
    fd.append('file', file);
    return fetch(`/api/ledger/import?${qs({ account })}`, { method: 'POST', body: fd })
      .then(json<LedgerImportResult>);
  },
  deleteImport: (id: number) =>
    fetch(`/api/ledger/imports/${id}`, { method: 'DELETE' }).then(json<{ removed: number }>),
  clear: () => fetch('/api/ledger', { method: 'DELETE' }).then(json<{ cleared: boolean }>),
  setModel: (model: string) => fetch('/api/ledger/settings', send('PUT', { model })).then(json<{ model: string }>),
  categorise: () => fetch('/api/ledger/categorise', { method: 'POST' }).then(json<CategoriseState>),
  categoriseState: () => fetch('/api/ledger/categorise').then(json<CategoriseState>),
  categoriseStop: () => fetch('/api/ledger/categorise/stop', { method: 'POST' }).then(json<CategoriseState>),
  ask: (question: string, model?: string) =>
    fetch('/api/ledger/ask', send('POST', { question, model })).then(json<LedgerAsk>),
  askState: () => fetch('/api/ledger/ask').then(json<LedgerAsk>),
  askStop: () => fetch('/api/ledger/ask/stop', { method: 'POST' }).then(json<LedgerAsk>),
  askExportUrl: '/api/ledger/ask/export',
};

/** 9410.5 -> "9.410,50 kr" - as the bank writes it. */
export function kr(x: number | null | undefined, decimals = 2): string {
  if (x == null || Number.isNaN(x)) return '–';
  const s = Math.abs(x).toLocaleString('da-DK', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  return `${x < 0 ? '−' : ''}${s} kr`;
}

/** "2026-03" -> "Mar 26" for an axis. */
export function monthLabel(m: string): string {
  const names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const [y, mm] = m.split('-');
  return `${names[Number(mm) - 1] ?? mm} ${y.slice(2)}`;
}
