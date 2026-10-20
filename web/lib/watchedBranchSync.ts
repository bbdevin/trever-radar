// 自選「特定分點」組合綁帳號(docs/52 §6):本機紀錄格式、登入時本機／雲端合併、雲端錯誤分類,
// 以及一個不依賴 React／Supabase 的同步器(storage 與雲端 API 由呼叫端注入,方便測試)。
// 執行測試: node --test web/lib/watchedBranchSync.test.ts
//
// 合併規則(登入且已核准、讀到雲端那一列之後):
//   1. 雲端有合法的一列:
//      - 本機有「還沒寫上雲端」的改動(dirty)、屬於這個帳號(或從沒和任何帳號同步過),
//        而且本機改動時間晚於雲端 updated_at → 本機勝,立刻 upsert 上去(離線／表還沒建時的改動不會丟)。
//      - 其他情況 → 雲端勝,覆蓋本機。
//   2. 雲端沒有這一列(或讀回不合法):本機有存過、屬於這個帳號(或從沒同步過)→ 用本機並上傳(第一次綁帳號);
//      本機屬於別的帳號(同一台換人登入)→ 照樣顯示、不上傳;本機什麼都沒有 → 預設組合、不寫任何東西。
//   3. 讀／寫失敗:一律留在本機(改動維持 dirty,下次登入或下次改動再試)。表不存在或沒權限 → 這次載入不再碰雲端
//      (不重試、不洗 console);其他錯誤(斷線等)整次載入最多 warn 一次。
// 舊格式(只有 {branches, anchor})視為「還沒同步、時間未知(0)」:雲端有就用雲端,沒有就上傳本機。

import { isValidBranchSet, normalizeSet, type BranchSet } from "./watchedBranches.ts";

export const LOCAL_KEY = "watched_branch_set_v1";
export const CLOUD_TABLE = "watched_branch_sets";

export interface LocalRecord {
  set: BranchSet;
  /** 本機最後一次改動(或採用雲端版本)的時間,ms;0 = 不知道(舊格式) */
  editedAt: number;
  /** 本機改動還沒確認寫進雲端 */
  dirty: boolean;
  /** 這份組合最後屬於哪個帳號;null = 從沒和帳號同步過 */
  uid: string | null;
}

/** 雲端一列(只取這三欄;user_id 由 RLS 與查詢條件保證是本人)。 */
export interface CloudRow {
  branches: unknown;
  anchor: unknown;
  updated_at: unknown;
}

export interface CloudWrite {
  user_id: string;
  branches: string[];
  anchor: string;
  updated_at: string;
}

export interface CloudError {
  code?: string | null;
  message?: string | null;
  status?: number | null;
}

export interface CloudApi {
  load(uid: string): Promise<{ row: CloudRow | null; error: CloudError | null }>;
  save(row: CloudWrite): Promise<{ error: CloudError | null }>;
}

export interface KeyValue {
  get(key: string): string | null;
  set(key: string, value: string): void;
}

export function defaultSet(): BranchSet {
  return normalizeSet(null);
}

/** 本機存的字串 → 紀錄;沒存過、壞值、或沒有任何可用分點 → null。 */
export function parseLocal(raw: string | null): LocalRecord | null {
  if (!raw) return null;
  let r: unknown;
  try {
    r = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!r || typeof r !== "object") return null;
  const o = r as { branches?: unknown; anchor?: unknown; edited_at?: unknown; dirty?: unknown; uid?: unknown };
  if (!Array.isArray(o.branches)) return null;
  const set = normalizeSet(o);
  // normalizeSet 對全壞的清單會回預設;那不是使用者存的,當作沒存過
  const kept = o.branches.some((b) => typeof b === "string" && set.branches.includes(b.trim()));
  if (!kept) return null;
  const legacy = typeof o.edited_at !== "number";
  const editedAt = !legacy && Number.isFinite(o.edited_at) && (o.edited_at as number) > 0 ? (o.edited_at as number) : 0;
  return {
    set,
    editedAt,
    dirty: legacy ? true : o.dirty === true,
    uid: typeof o.uid === "string" && o.uid ? o.uid : null,
  };
}

/** 存回本機;branches／anchor 留在最上層,舊版程式照樣讀得懂。 */
export function serializeLocal(rec: LocalRecord): string {
  return JSON.stringify({
    branches: rec.set.branches,
    anchor: rec.set.anchor,
    edited_at: rec.editedAt,
    dirty: rec.dirty,
    uid: rec.uid,
  });
}

/** 雲端一列 → 組合＋時間;不合法(理論上 DB check 已擋)→ null。 */
export function parseCloudRow(row: CloudRow | null | undefined): { set: BranchSet; at: number } | null {
  if (!row) return null;
  const candidate = { branches: row.branches, anchor: row.anchor };
  if (!isValidBranchSet(candidate)) return null;
  const at = typeof row.updated_at === "string" ? Date.parse(row.updated_at) : NaN;
  return {
    set: { branches: [...(row.branches as string[])], anchor: row.anchor as string },
    at: Number.isFinite(at) ? at : 0,
  };
}

function owned(local: LocalRecord | null, uid: string): local is LocalRecord {
  return local != null && (local.uid === null || local.uid === uid);
}

/** 見檔頭合併規則。record = null:不用改本機(什麼都沒存,顯示預設)。 */
export function mergeOnLoad(
  local: LocalRecord | null,
  cloudRow: CloudRow | null,
  uid: string,
): { record: LocalRecord | null; push: boolean } {
  const cloud = parseCloudRow(cloudRow);
  if (cloud) {
    if (owned(local, uid) && local.dirty && local.editedAt > cloud.at) {
      return { record: { ...local, uid }, push: true };
    }
    return { record: { set: cloud.set, editedAt: cloud.at, dirty: false, uid }, push: false };
  }
  if (owned(local, uid)) return { record: { ...local, dirty: true, uid }, push: true };
  return { record: local, push: false };
}

export type CloudFailure = "missing" | "denied" | "other";

/** 表還沒建(PostgREST PGRST205／Postgres 42P01／404)、沒權限(42501／401／403)、其他(斷線、5xx…)。 */
export function classifyCloudError(e: CloudError | null | undefined): CloudFailure {
  const code = e?.code ?? "";
  const msg = e?.message ?? "";
  const status = e?.status ?? 0;
  if (code === "PGRST205" || code === "42P01" || code === "PGRST204" || status === 404 || /does not exist|schema cache|could not find the table/i.test(msg)) {
    return "missing";
  }
  if (code === "42501" || status === 401 || status === 403 || /permission denied|row-level security/i.test(msg)) {
    return "denied";
  }
  return "other";
}

function sameSet(a: BranchSet, b: BranchSet): boolean {
  return a.anchor === b.anchor && a.branches.length === b.branches.length && a.branches.every((x, i) => x === b.branches[i]);
}

/**
 * 一個頁面載入共用一個(watchedBranchSet.ts 的 singleton):
 * - attach(uid):登入且已核准時傳 user id,未登入／未核准／登出傳 null。回傳該顯示的組合。
 * - edit(set):使用者改組合;先存本機(dirty),已 attach 帳號時排一次 upsert。
 * 寫雲端一次只送一個請求;送的時候又有改動,送完再送最新的那份(不會亂序蓋掉)。
 */
export class BranchSetSync {
  private cloudOff = false;
  private warned = false;
  private uid: string | null = null;
  private saving: Promise<void> | null = null;
  private again = false;
  private readonly now: () => number;
  private readonly deps: { kv: KeyValue; api: CloudApi; now?: () => number; warn?: (msg: string) => void };

  constructor(deps: { kv: KeyValue; api: CloudApi; now?: () => number; warn?: (msg: string) => void }) {
    this.deps = deps;
    this.now = deps.now ?? Date.now;
  }

  /** 這次載入已停用雲端(表不存在或沒權限)。 */
  get cloudDisabled(): boolean {
    return this.cloudOff;
  }

  local(): LocalRecord | null {
    return parseLocal(this.deps.kv.get(LOCAL_KEY));
  }

  current(): BranchSet {
    return this.local()?.set ?? defaultSet();
  }

  private store(rec: LocalRecord): void {
    this.deps.kv.set(LOCAL_KEY, serializeLocal(rec));
  }

  private fail(error: CloudError): void {
    const kind = classifyCloudError(error);
    if (kind !== "other") {
      this.cloudOff = true;
      return;
    }
    if (!this.warned) {
      this.warned = true;
      this.deps.warn?.(`${CLOUD_TABLE}: ${error.message ?? "request failed"}; using local copy`);
    }
  }

  async attach(uid: string | null): Promise<BranchSet> {
    this.uid = uid;
    if (!uid || this.cloudOff) return this.current();
    let res: Awaited<ReturnType<CloudApi["load"]>>;
    try {
      res = await this.deps.api.load(uid);
    } catch (e) {
      res = { row: null, error: { message: e instanceof Error ? e.message : String(e) } };
    }
    if (this.uid !== uid) return this.current(); // 期間換人或登出:丟掉結果
    if (res.error) {
      this.fail(res.error);
      return this.current();
    }
    // 重新讀本機:讀雲端期間使用者若改過,那份是 dirty 且較新,合併時會勝出
    const { record, push } = mergeOnLoad(this.local(), res.row, uid);
    if (record) this.store(record);
    if (push) void this.flush();
    return record?.set ?? defaultSet();
  }

  edit(next: BranchSet): BranchSet {
    const set = normalizeSet(next);
    const prev = this.local();
    // 一定比它所根據的版本(可能是別台裝置時鐘較快寫的雲端時間)新
    const editedAt = Math.max(this.now(), (prev?.editedAt ?? 0) + 1);
    this.store({ set, editedAt, dirty: true, uid: this.uid ?? prev?.uid ?? null });
    if (this.uid && !this.cloudOff) void this.flush();
    return set;
  }

  /** 等目前的雲端寫入結束(測試用)。 */
  async idle(): Promise<void> {
    while (this.saving) await this.saving;
  }

  private flush(): Promise<void> {
    if (this.saving) {
      this.again = true;
      return this.saving;
    }
    this.saving = (async () => {
      do {
        this.again = false;
        const uid = this.uid;
        const rec = this.local();
        if (!uid || this.cloudOff || !rec || !rec.dirty) break;
        if (rec.uid !== null && rec.uid !== uid) break;
        if (!isValidBranchSet(rec.set)) break;
        let error: CloudError | null;
        try {
          ({ error } = await this.deps.api.save({
            user_id: uid,
            branches: rec.set.branches,
            anchor: rec.set.anchor,
            // 舊格式時間未知(0)→ 用現在,不寫 1970
            updated_at: new Date(rec.editedAt || this.now()).toISOString(),
          }));
        } catch (e) {
          error = { message: e instanceof Error ? e.message : String(e) };
        }
        if (error) {
          this.fail(error);
          break;
        }
        const cur = this.local();
        if (cur && this.uid === uid && cur.editedAt === rec.editedAt && sameSet(cur.set, rec.set)) {
          this.store({ ...cur, dirty: false, uid });
        }
      } while (this.again);
    })().finally(() => {
      this.saving = null;
      // 迴圈最後一次檢查之後才排進來的改動(或送失敗期間的改動):再送一次;只會因使用者改動觸發,不會自己繞圈
      if (this.again) {
        this.again = false;
        void this.flush();
      }
    });
    return this.saving;
  }
}
