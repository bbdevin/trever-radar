// 執行測試: node --test web/lib/watchedBranchSync.test.ts
// 自選「特定分點」組合綁帳號(docs/52 §6):驗證(與 SQL check 同規則)、本機格式、合併、錯誤退回本機。
import assert from "node:assert/strict";
import { test } from "node:test";

import { DEFAULT_BRANCH_SET, isValidBranchName, isValidBranchSet, normalizeSet, type BranchSet } from "./watchedBranches.ts";
import {
  BranchSetSync,
  classifyCloudError,
  LOCAL_KEY,
  mergeOnLoad,
  parseCloudRow,
  parseLocal,
  serializeLocal,
  type CloudApi,
  type CloudError,
  type CloudRow,
  type CloudWrite,
  type LocalRecord,
} from "./watchedBranchSync.ts";

const UID = "00000000-0000-4000-8000-000000000001";
const OTHER = "00000000-0000-4000-8000-000000000002";
const A = "富邦-新店";
const B = "永豐金-內湖";
const C = "元大-松江";
const D = "凱基-台北";

const rec = (set: BranchSet, editedAt: number, dirty: boolean, uid: string | null): LocalRecord => ({ set, editedAt, dirty, uid });
const row = (branches: unknown, anchor: unknown, at: string | null = "2026-10-20T01:00:00.000Z"): CloudRow => ({ branches, anchor, updated_at: at });
const T_CLOUD = Date.parse("2026-10-20T01:00:00.000Z");

// ---------- 驗證(與 watched_branch_names_ok／anchor check 同規則) ----------

test("isValidBranchName mirrors the SQL check", () => {
  assert.ok(isValidBranchName(A));
  assert.ok(isValidBranchName("592E"));
  assert.ok(isValidBranchName("甲".repeat(64)));
  assert.ok(!isValidBranchName("甲".repeat(65)));
  assert.ok(!isValidBranchName(""));
  assert.ok(!isValidBranchName(" 甲"));
  assert.ok(!isValidBranchName("甲 "));
  assert.ok(!isValidBranchName("甲\n"));
  assert.ok(!isValidBranchName("甲\u0001乙"));
  assert.ok(!isValidBranchName("甲\u007f"));
  assert.ok(!isValidBranchName("甲\u0085乙")); // C1
  assert.ok(!isValidBranchName(42));
  assert.ok(!isValidBranchName(null));
});

test("isValidBranchSet: 1–6, unique, anchor in branches", () => {
  assert.ok(isValidBranchSet({ branches: [A], anchor: A }));
  assert.ok(isValidBranchSet({ branches: [A, B, C], anchor: C }));
  assert.ok(isValidBranchSet({ branches: ["1", "2", "3", "4", "5", "6"], anchor: "6" }));
  assert.ok(!isValidBranchSet({ branches: ["1", "2", "3", "4", "5", "6", "7"], anchor: "1" }));
  assert.ok(!isValidBranchSet({ branches: [], anchor: A }));
  assert.ok(!isValidBranchSet({ branches: [A, A], anchor: A }));
  assert.ok(!isValidBranchSet({ branches: [A, B], anchor: C }));
  assert.ok(!isValidBranchSet({ branches: [A, null], anchor: A }));
  assert.ok(!isValidBranchSet({ branches: [A, "x\ny"], anchor: A }));
  assert.ok(!isValidBranchSet({ branches: A, anchor: A }));
  assert.ok(!isValidBranchSet(null));
});

test("normalizeSet output always passes isValidBranchSet (drops control chars)", () => {
  const inputs: unknown[] = [
    null,
    { branches: [" 富邦-新店 ", "x\ny", "\u0007", B, B, "甲".repeat(70)], anchor: "x\ny" },
    { branches: ["1", "2", "3", "4", "5", "6", "7", "8"], anchor: "8" },
    { branches: ["\u0001"], anchor: "\u0001" },
    { branches: [1, 2, 3] },
  ];
  for (const i of inputs) assert.ok(isValidBranchSet(normalizeSet(i)), JSON.stringify(i));
  assert.deepEqual(normalizeSet(inputs[1]), { branches: [A, B], anchor: A });
});

// ---------- 本機格式 ----------

test("parseLocal: legacy {branches, anchor} = dirty, time unknown, no owner", () => {
  const r = parseLocal(JSON.stringify({ branches: [A, C], anchor: C }));
  assert.deepEqual(r, rec({ branches: [A, C], anchor: C }, 0, true, null));
});

test("parseLocal: round trip and junk", () => {
  const r = rec({ branches: [B, A], anchor: A }, 1234, false, UID);
  assert.deepEqual(parseLocal(serializeLocal(r)), r);
  assert.equal(parseLocal(null), null);
  assert.equal(parseLocal(""), null);
  assert.equal(parseLocal("{not json"), null);
  assert.equal(parseLocal("42"), null);
  assert.equal(parseLocal(JSON.stringify({ branches: ["\n"], anchor: "\n" })), null);
  assert.equal(parseLocal(JSON.stringify({ anchor: A })), null);
  // 舊版程式讀新格式照樣看得懂
  assert.deepEqual(normalizeSet(JSON.parse(serializeLocal(r))), r.set);
});

test("parseCloudRow rejects invalid rows", () => {
  assert.deepEqual(parseCloudRow(row([A, B], B)), { set: { branches: [A, B], anchor: B }, at: T_CLOUD });
  assert.equal(parseCloudRow(row([A, B], C)), null);
  assert.equal(parseCloudRow(row([A, A], A)), null);
  assert.equal(parseCloudRow(row("x", "x")), null);
  assert.equal(parseCloudRow(null), null);
  assert.deepEqual(parseCloudRow(row([A], A, null)), { set: { branches: [A], anchor: A }, at: 0 });
});

// ---------- 合併 ----------

test("merge: cloud wins over clean local", () => {
  const local = rec({ branches: [A], anchor: A }, T_CLOUD + 999, false, UID);
  assert.deepEqual(mergeOnLoad(local, row([B, C], C), UID), {
    record: rec({ branches: [B, C], anchor: C }, T_CLOUD, false, UID),
    push: false,
  });
});

test("merge: newer offline local edit wins and is pushed", () => {
  const local = rec({ branches: [A, D], anchor: D }, T_CLOUD + 1, true, UID);
  assert.deepEqual(mergeOnLoad(local, row([B, C], C), UID), { record: local, push: true });
  // 從沒同步過(登出時改的)也算本人
  const anon = rec({ branches: [A, D], anchor: D }, T_CLOUD + 1, true, null);
  assert.deepEqual(mergeOnLoad(anon, row([B, C], C), UID), { record: { ...anon, uid: UID }, push: true });
});

test("merge: older dirty local and legacy local lose to cloud", () => {
  const older = rec({ branches: [A, D], anchor: D }, T_CLOUD - 1, true, UID);
  assert.equal(mergeOnLoad(older, row([B], B), UID).push, false);
  assert.deepEqual(mergeOnLoad(older, row([B], B), UID).record?.set, { branches: [B], anchor: B });
  const legacy = parseLocal(JSON.stringify({ branches: [A, C], anchor: C }));
  assert.deepEqual(mergeOnLoad(legacy, row([B], B), UID).record?.set, { branches: [B], anchor: B });
});

test("merge: another account's local never wins and is never pushed", () => {
  const theirs = rec({ branches: [A, D], anchor: D }, T_CLOUD + 1e9, true, OTHER);
  assert.deepEqual(mergeOnLoad(theirs, row([B], B), UID), { record: rec({ branches: [B], anchor: B }, T_CLOUD, false, UID), push: false });
  assert.deepEqual(mergeOnLoad(theirs, null, UID), { record: theirs, push: false });
});

test("merge: no cloud row seeds from own local; nothing stored = nothing written", () => {
  const legacy = parseLocal(JSON.stringify({ branches: [A, C], anchor: C }))!;
  assert.deepEqual(mergeOnLoad(legacy, null, UID), { record: { ...legacy, uid: UID }, push: true });
  const clean = rec({ branches: [A], anchor: A }, 5, false, UID);
  assert.deepEqual(mergeOnLoad(clean, null, UID), { record: { ...clean, dirty: true }, push: true });
  assert.deepEqual(mergeOnLoad(null, null, UID), { record: null, push: false });
  // 讀回不合法的雲端列 = 當作沒有
  assert.deepEqual(mergeOnLoad(clean, row([A, A], A), UID).push, true);
});

// ---------- 錯誤分類 ----------

test("classifyCloudError", () => {
  assert.equal(classifyCloudError({ code: "PGRST205", message: "Could not find the table 'public.watched_branch_sets' in the schema cache", status: 404 }), "missing");
  assert.equal(classifyCloudError({ code: "42P01", message: 'relation "public.watched_branch_sets" does not exist' }), "missing");
  assert.equal(classifyCloudError({ status: 404 }), "missing");
  assert.equal(classifyCloudError({ code: "42501", message: "new row violates row-level security policy", status: 403 }), "denied");
  assert.equal(classifyCloudError({ code: "42501", message: "permission denied for table watched_branch_sets", status: 401 }), "denied");
  assert.equal(classifyCloudError({ message: "TypeError: Failed to fetch", status: 0 }), "other");
  assert.equal(classifyCloudError({ code: "23514", message: "violates check constraint", status: 400 }), "other");
});

// ---------- 同步器(假 storage／假雲端) ----------

class MemKV {
  data = new Map<string, string>();
  get(k: string) {
    return this.data.get(k) ?? null;
  }
  set(k: string, v: string) {
    this.data.set(k, v);
  }
}

class FakeCloud implements CloudApi {
  row: CloudRow | null = null;
  loadError: CloudError | null = null;
  saveError: CloudError | null = null;
  loads = 0;
  saves: CloudWrite[] = [];
  gate: Promise<void> | null = null;
  async load(_uid: string) {
    this.loads += 1;
    return this.loadError ? { row: null, error: this.loadError } : { row: this.row, error: null };
  }
  async save(w: CloudWrite) {
    if (this.gate) await this.gate;
    this.saves.push(structuredClone(w));
    if (this.saveError) return { error: this.saveError };
    this.row = { branches: w.branches, anchor: w.anchor, updated_at: w.updated_at };
    return { error: null };
  }
}

function setup(now = 10_000) {
  const kv = new MemKV();
  const api = new FakeCloud();
  const warns: string[] = [];
  let t = now;
  const sync = new BranchSetSync({ kv, api, now: () => t, warn: (m) => warns.push(m) });
  return { kv, api, warns, sync, tick: (ms: number) => (t += ms) };
}

test("sync: logged out = local only, never touches cloud", async () => {
  const { api, sync, kv } = setup();
  assert.deepEqual(await sync.attach(null), DEFAULT_BRANCH_SET);
  sync.edit({ branches: [A, B], anchor: B });
  await sync.idle();
  assert.equal(api.loads, 0);
  assert.equal(api.saves.length, 0);
  assert.deepEqual(parseLocal(kv.get(LOCAL_KEY)), rec({ branches: [A, B], anchor: B }, 10_000, true, null));
});

test("sync: table missing → falls back to local, stops calling the cloud, no warnings", async () => {
  const { api, sync, kv, warns } = setup();
  kv.set(LOCAL_KEY, JSON.stringify({ branches: [A, C], anchor: C }));
  api.loadError = { code: "PGRST205", message: "Could not find the table 'public.watched_branch_sets' in the schema cache", status: 404 };
  assert.deepEqual(await sync.attach(UID), { branches: [A, C], anchor: C });
  assert.equal(sync.cloudDisabled, true);
  sync.edit({ branches: [A, C, D], anchor: A });
  sync.edit({ branches: [A, D], anchor: A });
  await sync.idle();
  assert.deepEqual(await sync.attach(UID), { branches: [A, D], anchor: A });
  assert.equal(api.loads, 1);
  assert.equal(api.saves.length, 0);
  assert.deepEqual(warns, []);
  assert.equal(parseLocal(kv.get(LOCAL_KEY))?.dirty, true); // 表建好、重新載入後會上傳
});

test("sync: network error keeps local, warns once, retries on next edit", async () => {
  const { api, sync, warns, kv } = setup();
  api.loadError = { message: "TypeError: Failed to fetch", status: 0 };
  assert.deepEqual(await sync.attach(UID), DEFAULT_BRANCH_SET);
  assert.equal(sync.cloudDisabled, false);
  api.saveError = { message: "TypeError: Failed to fetch", status: 0 };
  sync.edit({ branches: [B], anchor: B });
  await sync.idle();
  sync.edit({ branches: [B, C], anchor: B });
  await sync.idle();
  assert.equal(api.saves.length, 2);
  assert.equal(warns.length, 1);
  assert.equal(parseLocal(kv.get(LOCAL_KEY))?.dirty, true);
  api.saveError = null;
  sync.edit({ branches: [B, C, D], anchor: B });
  await sync.idle();
  assert.equal(parseLocal(kv.get(LOCAL_KEY))?.dirty, false);
  assert.deepEqual(api.row, { branches: [B, C, D], anchor: B, updated_at: new Date(10_000 + 2).toISOString() });
});

test("sync: denied (pending account / RLS) disables cloud without retry loop", async () => {
  const { api, sync, warns } = setup();
  api.saveError = { code: "42501", message: "new row violates row-level security policy for table \"watched_branch_sets\"", status: 403 };
  await sync.attach(UID);
  sync.edit({ branches: [B], anchor: B });
  await sync.idle();
  sync.edit({ branches: [B, C], anchor: B });
  await sync.idle();
  assert.equal(api.saves.length, 1);
  assert.equal(sync.cloudDisabled, true);
  assert.deepEqual(warns, []);
});

test("sync: cloud row loads on login and overwrites a clean local copy", async () => {
  const { api, sync, kv } = setup();
  kv.set(LOCAL_KEY, serializeLocal(rec({ branches: [A], anchor: A }, 9_000, false, UID)));
  api.row = row([C, D], D);
  assert.deepEqual(await sync.attach(UID), { branches: [C, D], anchor: D });
  await sync.idle();
  assert.equal(api.saves.length, 0);
  assert.deepEqual(parseLocal(kv.get(LOCAL_KEY)), rec({ branches: [C, D], anchor: D }, T_CLOUD, false, UID));
});

test("sync: first login seeds the cloud from the legacy local set", async () => {
  const { api, sync, kv } = setup();
  kv.set(LOCAL_KEY, JSON.stringify({ branches: [A, C], anchor: C }));
  assert.deepEqual(await sync.attach(UID), { branches: [A, C], anchor: C });
  await sync.idle();
  assert.deepEqual(api.saves, [{ user_id: UID, branches: [A, C], anchor: C, updated_at: new Date(10_000).toISOString() }]);
  assert.equal(parseLocal(kv.get(LOCAL_KEY))?.dirty, false);
});

test("sync: nothing stored and no cloud row → default, nothing written", async () => {
  const { api, sync, kv } = setup();
  assert.deepEqual(await sync.attach(UID), DEFAULT_BRANCH_SET);
  await sync.idle();
  assert.equal(api.saves.length, 0);
  assert.equal(kv.get(LOCAL_KEY), null);
});

test("sync: edits upsert own row with the right body; rapid edits end with the latest set", async () => {
  const { api, sync, tick } = setup();
  await sync.attach(UID);
  let release!: () => void;
  api.gate = new Promise((r) => (release = r));
  sync.edit({ branches: [A], anchor: A });
  tick(5);
  sync.edit({ branches: [A, B], anchor: A });
  tick(5);
  sync.edit({ branches: [A, B, C], anchor: C });
  release();
  await sync.idle();
  assert.equal(api.saves.length, 2); // 第一筆在飛的時候後兩筆合成一次
  assert.deepEqual(api.saves.at(-1), { user_id: UID, branches: [A, B, C], anchor: C, updated_at: new Date(10_010).toISOString() });
  for (const s of api.saves) assert.equal(s.user_id, UID);
});

test("sync: an edit made while the cloud read is in flight is not overwritten", async () => {
  const { api, sync, kv, tick } = setup(T_CLOUD + 60_000);
  api.row = row([C], C);
  const p = sync.attach(UID);
  tick(1);
  sync.edit({ branches: [A, D], anchor: D }); // attach 尚未讀完
  assert.deepEqual(await p, { branches: [A, D], anchor: D });
  await sync.idle();
  assert.deepEqual(api.row?.branches, [A, D]);
  assert.equal(parseLocal(kv.get(LOCAL_KEY))?.dirty, false);
});

test("sync: switching account mid-read discards the stale result", async () => {
  const { api, sync, kv } = setup();
  kv.set(LOCAL_KEY, serializeLocal(rec({ branches: [A], anchor: A }, 1, false, OTHER)));
  api.row = row([C], C);
  const p = sync.attach(UID);
  void sync.attach(null); // 期間登出
  assert.deepEqual(await p, { branches: [A], anchor: A });
  assert.equal(parseLocal(kv.get(LOCAL_KEY))?.uid, OTHER);
});

test("sync: another account's leftover local set is shown but never uploaded", async () => {
  const { api, sync } = setup();
  const kv = (sync as unknown as { deps: { kv: MemKV } }).deps.kv;
  kv.set(LOCAL_KEY, serializeLocal(rec({ branches: [A, D], anchor: D }, 50_000, true, OTHER)));
  assert.deepEqual(await sync.attach(UID), { branches: [A, D], anchor: D });
  await sync.idle();
  assert.equal(api.saves.length, 0);
  // 本人改過之後才上傳,且上傳的是本人的
  sync.edit({ branches: [A], anchor: A });
  await sync.idle();
  assert.equal(api.saves.length, 1);
  assert.equal(api.saves[0].user_id, UID);
});

test("sync: edit timestamp is always newer than the version it was based on", async () => {
  const { api, sync, kv } = setup(1_000); // 本機時鐘比寫雲端那台慢
  api.row = row([C], C);
  await sync.attach(UID);
  sync.edit({ branches: [C, D], anchor: C });
  await sync.idle();
  assert.equal(parseLocal(kv.get(LOCAL_KEY))?.editedAt, T_CLOUD + 1);
  assert.equal(api.saves[0].updated_at, new Date(T_CLOUD + 1).toISOString());
});
