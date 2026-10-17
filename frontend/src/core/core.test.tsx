import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { api } from './api';
import { SettingsPage } from './SettingsPage';
import { StepTree } from './StepTree';
import { App } from '../App';
import { sectionsFor, SECTIONS } from '../sections/registry';
import type { SettingsDto } from './types';

const SETTINGS: SettingsDto = {
  ollamaUrl: 'http://30.11.0.104:11434', modelChat: '', modelVision: '', modelCategorise: '',
  ollamaKeepAlive: '', contextMax: 16384, comfyUrl: '', comfyFreeFirst: true, gpuBroker: 'local',
  searchProvider: 'duckduckgo', searxngUrl: '', searchResults: 4, searchFetch: 3, searchBlockedRanges: '',
  searchApiKeySet: false, nominatimUrl: 'https://nominatim.openstreetmap.org',
  overpassUrl: 'https://overpass-api.de/api/interpreter', timezone: 'Europe/Copenhagen', envPinned: {},
};

function mockSettings(over: Partial<SettingsDto> = {}) {
  vi.spyOn(api, 'getSettings').mockResolvedValue({ ...SETTINGS, ...over });
  vi.spyOn(api, 'listOllamaModels').mockResolvedValue([]);
  vi.spyOn(api, 'users').mockResolvedValue([{ id: 1, username: 'admin', role: 'admin', online: true }]);
  vi.spyOn(api, 'diagnostics').mockResolvedValue({
    version: '0.1.0', queue: { broker: 'local', running: null, pending: [] }, recent: [], logTail: '' });
}

describe('Settings', () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it('tests the typed Ollama address and offers its models per role', async () => {
    mockSettings();
    const test = vi.spyOn(api, 'testOllama').mockResolvedValue({
      ok: true, url: 'http://mock:11434', error: null,
      models: [{ name: 'qwen3.6:27b', size: 17.4e9, family: 'qwen3', parameters: '27B', quantization: 'Q4_K_M' },
               { name: 'qwen3-vl:8b', size: 6.1e9, family: 'qwen3vl', parameters: '8B', quantization: 'Q4_K_M' }],
    });
    const save = vi.spyOn(api, 'saveSettings').mockImplementation(async (p) => ({ ...SETTINGS, ...p } as SettingsDto));
    const { container } = render(<SettingsPage me={{ id: 1 }} />);
    const url = await screen.findByDisplayValue('http://30.11.0.104:11434');
    fireEvent.change(url, { target: { value: 'http://mock:11434' } });
    fireEvent.click(screen.getByRole('button', { name: 'Test Ollama' }));
    expect(test).toHaveBeenCalledWith('http://mock:11434');
    expect(await screen.findByText(/Connected - 2 models/)).toBeInTheDocument();
    const models = container.querySelector('[data-help="settings.models"]') as HTMLElement;
    const [chat, vision] = within(models).getAllByRole('combobox');
    fireEvent.change(chat, { target: { value: 'qwen3.6:27b' } });
    fireEvent.change(vision, { target: { value: 'qwen3-vl:8b' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save (3)' }));
    await waitFor(() => expect(save).toHaveBeenCalledWith(
      { ollamaUrl: 'http://mock:11434', modelChat: 'qwen3.6:27b', modelVision: 'qwen3-vl:8b' }));
    expect(await screen.findByText('Saved.')).toBeInTheDocument();
  });

  it('says why a test failed', async () => {
    mockSettings();
    vi.spyOn(api, 'testOllama').mockResolvedValue({ ok: false, url: 'x', models: [],
      error: 'Ollama at http://30.11.0.104:11434 is not answering: timed out' });
    render(<SettingsPage me={{ id: 1 }} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Test Ollama' }));
    expect(await screen.findByText(/is not answering: timed out/)).toBeInTheDocument();
  });

  it('a Brave key typed and erased again is no change; Remove clears it', async () => {
    mockSettings({ searchProvider: 'brave', searchApiKeySet: true });
    const save = vi.spyOn(api, 'saveSettings').mockImplementation(async (p) => ({ ...SETTINGS, ...p } as SettingsDto));
    render(<SettingsPage me={{ id: 1 }} />);
    const key = await screen.findByPlaceholderText('•••••••• (saved)');
    fireEvent.change(key, { target: { value: 'abc' } });
    fireEvent.change(key, { target: { value: '' } });
    expect(screen.getByRole('button', { name: 'Saved' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save (1)' }));
    await waitFor(() => expect(save).toHaveBeenCalledWith({ searchApiKey: null }));
  });

  it('locks a value the environment pins and names the variable', async () => {
    mockSettings({ envPinned: { ollamaUrl: 'APP_OLLAMA_URL' } });
    render(<SettingsPage me={{ id: 1 }} />);
    expect(await screen.findByDisplayValue('http://30.11.0.104:11434')).toBeDisabled();
    expect(screen.getByText('APP_OLLAMA_URL')).toBeInTheDocument();
  });
});

describe('Shell', () => {
  beforeEach(() => { vi.restoreAllMocks(); try { localStorage.clear(); } catch { /* */ } });

  it('shows the login with the app name when nobody is signed in', async () => {
    vi.spyOn(api, 'meta').mockResolvedValue({ name: 'FamilyLog', version: '0.1.0' });
    vi.spyOn(api, 'authStatus').mockResolvedValue({ needsSetup: true, user: null });
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'FamilyLog' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create administrator' })).toBeInTheDocument();
  });

  it('lists the sections from the registry; FamilyMap only for the admin', () => {
    expect(SECTIONS.map((s) => s.id)).toEqual(['ledger', 'familymap']);
    expect(sectionsFor('user').map((s) => s.id)).toEqual(['ledger']);
    expect(sectionsFor('admin').map((s) => s.id)).toEqual(['ledger', 'familymap']);
  });
});

describe('Steps', () => {
  it('summarises and opens into a tree', () => {
    render(<StepTree payload={{
      startedAt: 1000, serverNow: 1010,
      steps: [
        { id: 1, parent: null, label: 'Answer', kind: 'stage', start: 0, end: 4.2, state: 'ok', tokens: null, detail: null, approx: false },
        { id: 2, parent: 1, label: 'qwen3.6:27b', kind: 'model', start: 0.1, end: 4.2, state: 'ok', tokens: 120, detail: null, approx: false },
      ],
      summary: { totalS: 4.2, queueS: 0, firstOutputS: 1, firstTokenS: 1.5, tokensOut: 120, tps: 30,
                 promptTokens: 900, contextLimit: 16384, model: 'qwen3.6:27b', modelCalls: 1, running: false },
    }} />);
    expect(screen.getByText(/4\.2 s · first token 1\.5 s · 120 tokens out/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Steps/ }));
    expect(screen.getByText('qwen3.6:27b')).toBeInTheDocument();
    expect(screen.getByText('120 tok')).toBeInTheDocument();
  });
});
