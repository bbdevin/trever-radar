/**
 * 拆檔一致性 + 大小量測(docs/44 P1 §3.2)。
 *
 *   node --experimental-strip-types scripts/verify-split-merge.mjs --legacy <舊佈局 data 目錄> --split <新佈局 data 目錄>
 *
 * 對每一檔:用前端的 mergeStockParts 把 <split>/stocks/core/{id}.json + hist + chips 接回,
 * 與 <legacy>/stocks/{id}.json 深度比對(assert.deepStrictEqual,與個股頁拿到的物件同一個函式)。
 * 同時統計 raw 與 brotli(瀏覽器實際下載的量級)大小:舊單一檔 vs 核心 / 核心+chips(第一次畫面)/ 全部。
 * 任一檔不相等就 exit 1。
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";

import { mergeStockParts } from "../lib/stockParts.ts";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, v, i, all) => (v.startsWith("--") ? [...acc, [v.slice(2), all[i + 1]]] : acc), []),
);
const LEGACY = path.resolve(args.legacy);
const SPLIT = path.resolve(args.split);
const readJson = (p) => JSON.parse(fs.readFileSync(p, "utf8"));
const br = (buf) => zlib.brotliCompressSync(buf, { params: { [zlib.constants.BROTLI_PARAM_QUALITY]: 5 } }).length;
const size = (p) => {
  const buf = fs.readFileSync(p);
  return { raw: buf.length, br: br(buf) };
};

const radar = readJson(path.join(LEGACY, "radar.json"));
const union = new Set((radar.stocks ?? []).map((s) => s.id));
const files = fs.readdirSync(path.join(LEGACY, "stocks")).filter((f) => f.endsWith(".json")).sort();

const rows = [];
let mismatches = 0;
for (const f of files) {
  const id = f.slice(0, -5);
  const legacy = readJson(path.join(LEGACY, "stocks", f));
  const corePath = path.join(SPLIT, "stocks", "core", f);
  const core = readJson(corePath);
  const histRel = core.parts.hist?.file ?? null;
  const chipsRel = core.parts.chips?.file ?? null;
  const hist = histRel ? readJson(path.join(SPLIT, "stocks", histRel)) : null;
  const chips = chipsRel ? readJson(path.join(SPLIT, "stocks", chipsRel)) : null;
  const merged = mergeStockParts(core, hist, chips);
  try {
    assert.deepStrictEqual(merged, legacy);
  } catch (e) {
    mismatches += 1;
    console.error(`MISMATCH ${id}: ${String(e.message).split("\n").slice(0, 6).join("\n")}`);
  }
  const sLegacy = size(path.join(LEGACY, "stocks", f));
  const sCore = size(corePath);
  const sChips = chipsRel ? size(path.join(SPLIT, "stocks", chipsRel)) : { raw: 0, br: 0 };
  const sHist = histRel ? size(path.join(SPLIT, "stocks", histRel)) : { raw: 0, br: 0 };
  rows.push({
    id, union: union.has(id), bars: legacy.candles.length, hist_bars: hist?.bars ?? 0,
    legacy: sLegacy, core: sCore, chips: sChips, hist: sHist,
  });
}

const q = (vals, p) => {
  const s = [...vals].sort((a, b) => a - b);
  return s.length ? s[Math.min(s.length - 1, Math.round(p * (s.length - 1)))] : 0;
};
const kb = (n) => `${(n / 1024).toFixed(0)} KB`;
function summarize(group, label) {
  if (!group.length) return;
  const line = (name, pick) =>
    `  ${name.padEnd(26)} p50 ${kb(q(group.map(pick), 0.5)).padStart(8)}  p90 ${kb(q(group.map(pick), 0.9)).padStart(8)}  max ${kb(Math.max(...group.map(pick))).padStart(8)}`;
  console.log(`${label} (${group.length} 檔)`);
  console.log(line("legacy raw", (r) => r.legacy.raw));
  console.log(line("core raw", (r) => r.core.raw));
  console.log(line("core+chips raw (首畫面)", (r) => r.core.raw + r.chips.raw));
  console.log(line("core+chips+hist raw", (r) => r.core.raw + r.chips.raw + r.hist.raw));
  console.log(line("legacy brotli", (r) => r.legacy.br));
  console.log(line("core brotli", (r) => r.core.br));
  console.log(line("core+chips brotli (首畫面)", (r) => r.core.br + r.chips.br));
  console.log(line("core+chips+hist brotli", (r) => r.core.br + r.chips.br + r.hist.br));
}
console.log(`verify-split-merge: stocks=${files.length} mismatches=${mismatches} union=${rows.filter((r) => r.union).length}`);
summarize(rows.filter((r) => r.union), "聯集(全歷史)");
summarize(rows.filter((r) => !r.union), "其餘(600 根)");
const totals = (pick) => rows.reduce((s, r) => s + pick(r), 0);
console.log(`全部檔案合計 raw: legacy ${kb(totals((r) => r.legacy.raw))} → core ${kb(totals((r) => r.core.raw))} + chips ${kb(totals((r) => r.chips.raw))} + hist ${kb(totals((r) => r.hist.raw))}`);
for (const id of (args.show ?? "2330,4967,6488").split(",")) {
  const r = rows.find((x) => x.id === id);
  if (r) console.log(`${id}: union=${r.union} bars=${r.bars} hist_bars=${r.hist_bars} legacy ${kb(r.legacy.raw)}/${kb(r.legacy.br)}br → core ${kb(r.core.raw)}/${kb(r.core.br)}br chips ${kb(r.chips.raw)}/${kb(r.chips.br)}br hist ${kb(r.hist.raw)}/${kb(r.hist.br)}br`);
}
if (args.out) fs.writeFileSync(args.out, JSON.stringify(rows));
process.exitCode = mismatches ? 1 : 0;
