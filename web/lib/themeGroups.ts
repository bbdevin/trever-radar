import type { RadarStock, SectorFlow } from "@/lib/types";

export const OTHER_THEME = "其他";

export type ThemeStockGroup = {
  name: string;
  vs20: number | null;
  stocks: RadarStock[];
};

/**
 * WP-H1:依「當日最熱題材」分組。
 * 一檔多題材只歸 vs20 最高的那個;無題材進「其他」。
 * radar.themes 為空時回傳 null,呼叫端 fallback 原排序。
 */
export function groupStocksByHottestTheme(
  stocks: RadarStock[],
  themeFlows: SectorFlow[] | undefined,
): ThemeStockGroup[] | null {
  if (!themeFlows?.length) return null;

  const vs20ByName = new Map<string, number | null>();
  for (const t of themeFlows) vs20ByName.set(t.name, t.vs20);

  const buckets = new Map<string, RadarStock[]>();
  for (const s of stocks) {
    const key = pickHottestTheme(s.themes, vs20ByName) ?? OTHER_THEME;
    const list = buckets.get(key);
    if (list) list.push(s);
    else buckets.set(key, [s]);
  }

  const groups: ThemeStockGroup[] = [];
  for (const [name, list] of buckets) {
    groups.push({
      name,
      vs20: name === OTHER_THEME ? null : (vs20ByName.get(name) ?? null),
      stocks: list,
    });
  }

  groups.sort(compareThemeGroups);
  return groups;
}

function pickHottestTheme(
  themes: string[] | undefined,
  vs20ByName: Map<string, number | null>,
): string | null {
  if (!themes?.length) return null;
  let best: string | null = null;
  let bestScore = -Infinity;
  for (const name of themes) {
    const raw = vs20ByName.get(name);
    const score = raw == null ? -1 : raw;
    if (best === null || score > bestScore) {
      best = name;
      bestScore = score;
    }
  }
  return best;
}

function compareThemeGroups(a: ThemeStockGroup, b: ThemeStockGroup): number {
  if (a.name === OTHER_THEME) return 1;
  if (b.name === OTHER_THEME) return -1;
  const av = a.vs20;
  const bv = b.vs20;
  if (av != null && bv != null && av !== bv) return bv - av;
  if (av != null && bv == null) return -1;
  if (av == null && bv != null) return 1;
  return a.name.localeCompare(b.name, "zh-Hant");
}
