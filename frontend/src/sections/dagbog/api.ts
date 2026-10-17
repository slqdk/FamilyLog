/** The Dagbog's administrator API (FamilyLog 0.2.0). */
export interface DagbogAdminSettings {
  tags: string[];
  foods: string[];
  fields: { key: string; label: string; kind: string }[];
  members: { id: number; username: string; role: string; fields: string[] }[];
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { const b = await res.json(); if (b?.detail) detail = String(b.detail); } catch { /* */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const dagbogAdmin = {
  settings: () => fetch('/api/dagbog/admin/settings').then(json<DagbogAdminSettings>),
  save: (body: { tags?: string[]; foods?: string[]; members?: Record<string, string[]> }) =>
    fetch('/api/dagbog/admin/settings', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(json<DagbogAdminSettings>),
};
