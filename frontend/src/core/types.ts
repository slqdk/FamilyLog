/** Shared DTOs of the shell (the sections keep theirs next to their views). */

export type Gender = '' | 'female' | 'male';
export interface AuthUser { id: number; username: string; role: 'admin' | 'user' | 'family'; gender?: Gender; createdAt?: string }
export interface AuthStatus { needsSetup: boolean; user: AuthUser | null }
export interface Meta { name: string; version: string }

export interface UserDto extends AuthUser { online?: boolean }

export interface HelpEntryDto {
  id: string; title: string; where: string; since: string; changed: string; body: string;
}
export interface HelpDto { version: string; name: string; entries: HelpEntryDto[] }

/** One row of an answer's step tree (backend core/telemetry.py).
 *  start/end are seconds since the job started; end is null while running. */
export interface StepDto {
  id: number;
  parent: number | null;
  label: string;
  kind: 'queue' | 'info' | 'stage' | 'model' | 'prompt' | 'thinking' | 'writing' | string;
  start: number;
  end: number | null;
  state: 'run' | 'ok' | 'error' | 'stopped';
  tokens: number | null;
  detail: string | null;
  approx: boolean;
  flag?: string;
}
export interface StepsSummary {
  totalS: number; queueS: number; firstOutputS: number | null; firstTokenS: number | null;
  tokensOut: number | null; tps: number | null; promptTokens: number | null;
  contextLimit: number | null; model: string | null; modelCalls: number; running: boolean;
}
export interface StepsPayload { startedAt: number; serverNow: number; steps: StepDto[]; summary: StepsSummary }

/** GET /api/settings (backend core/settings.py public()). */
export interface SettingsDto {
  ollamaUrl: string;
  modelChat: string; modelVision: string; modelCategorise: string;
  ollamaKeepAlive: string; contextMax: number;
  comfyUrl: string; comfyFreeFirst: boolean; gpuBroker: string;
  searchProvider: 'duckduckgo' | 'searxng' | 'brave'; searxngUrl: string;
  searchResults: number; searchFetch: number; searchBlockedRanges: string;
  searchApiKeySet: boolean;
  nominatimUrl: string; overpassUrl: string; timezone: string;
  /** key -> environment variable that pins it (read-only in the UI) */
  envPinned: Record<string, string>;
}
export type SettingsPatch = Partial<Omit<SettingsDto, 'envPinned' | 'searchApiKeySet'>> & {
  searchApiKey?: string | null;
};

export interface OllamaModel {
  name: string; size: number | null; family: string | null; parameters: string | null;
  quantization: string | null;
}
export interface OllamaTest { ok: boolean; url: string; models: OllamaModel[]; error: string | null }
export interface ComfyTest { ok: boolean; url: string; message: string }

export interface QueueJob { id: number; kind: string; state: string; enqueuedAt: number; startedAt: number | null }
export interface Diagnostics {
  version: string;
  queue: { broker: string; running: QueueJob | null; pending: QueueJob[] };
  recent: { time: string; level: string; message: string; where: string; traceback: string | null }[];
  logTail: string;
}
