/** The category picker's options in sections (0.3.4: house first, then the
    car, ...), in the order the backend sends them (ledger.CATEGORY_GROUPS). */
export function CategoryOptions<T extends { key: string; group?: string }>({ categories, label }: {
  categories: T[]; label: (c: T) => string;
}) {
  const groups: [string, T[]][] = [];
  for (const c of categories) {
    const g = c.group ?? '';
    const last = groups[groups.length - 1];
    if (last && last[0] === g) last[1].push(c);
    else groups.push([g, [c]]);
  }
  return (
    <>
      {groups.map(([g, cs]) => g
        ? <optgroup key={g} label={g}>{cs.map((c) => <option key={c.key} value={c.key}>{label(c)}</option>)}</optgroup>
        : cs.map((c) => <option key={c.key} value={c.key}>{label(c)}</option>))}
    </>
  );
}
