// 全站追蹤名單的管理員覆寫(純邏輯;branchTrackList.tsx 用、branchTrackResolve.test.ts 驗)。
//
// 系統名單(manual 種子＋演算法自動入選)由 VPS 匯出;管理員在 Supabase
// `branch_track_list`(一份、全站一致)存的是「相對系統名單的差異」:
//   - state 'mute'  :系統名單裡有、但不要 → muted
//   - state 'track' :系統名單裡沒有、但要 → added
// 有效追蹤 = (系統名單 − muted) ∪ added。VPS 夜間把這張表併回系統名單前,
// 前端用這裡的規則先疊加,讓所有人的畫面一致。
//
// 這支檔案不 import 任何東西:node --test 認不得 "@/" 別名。

export type TrackAction =
  | { kind: "upsert"; state: "mute" | "track" }
  | { kind: "delete" };

/** 這個分點對這位使用者來說算不算追蹤。 */
export function effectiveTracked(
  name: string,
  serverTracked: boolean,
  muted: ReadonlySet<string>,
  added: ReadonlySet<string>,
): boolean {
  if (added.has(name)) return true;
  if (muted.has(name)) return false;
  return serverTracked;
}

/** 系統名單 − muted ∪ added。 */
export function effectiveTrackedSet(
  serverList: Iterable<string>,
  muted: ReadonlySet<string>,
  added: ReadonlySet<string>,
): Set<string> {
  const out = new Set<string>();
  for (const name of serverList) if (!muted.has(name)) out.add(name);
  for (const name of added) out.add(name);
  return out;
}

/**
 * 按一下星號要寫什麼。按下去一定翻轉「有效追蹤」,而且只留必要的那一列:
 * - 系統名單有、沒被 mute → 寫 'mute'。
 * - 名單加入的(added)→ 刪掉那一列;目前 muted → 刪掉那一列(回到系統預設)。
 * - 都沒有 → 寫 'track'。
 * 多餘列(系統名單後來自己收錄了、卻還留著 'track';或系統名單已移除、卻還留著
 * 'mute')也照「翻轉後與系統預設相同就刪、不同才寫」處理,不會按了沒反應。
 */
export function nextAction(
  name: string,
  serverTracked: boolean,
  muted: ReadonlySet<string>,
  added: ReadonlySet<string>,
): TrackAction {
  const target = !effectiveTracked(name, serverTracked, muted, added);
  if (target === serverTracked) return { kind: "delete" };
  return { kind: "upsert", state: target ? "track" : "mute" };
}

/**
 * 口袋名單「追蹤分點同買」徽章:背後的分點只要有一個沒被 mute 就照常顯示。
 * 舊 payload 沒帶 branches 時無從判斷 → 照常顯示(不藏資料)。
 */
export function pocketBadgeVisible(
  branches: readonly string[] | null | undefined,
  muted: ReadonlySet<string>,
): boolean {
  if (!branches || branches.length === 0) return true;
  return branches.some((name) => !muted.has(name));
}
