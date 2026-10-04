/**
 * 首頁「多方榜」建置器(docs/48 §1.1)。在 VPS 主機上、export-json 之後、deploy 之前跑;
 * 失敗不得擋 deploy(呼叫端 warn-and-continue)。
 *
 * 用 Node 直接跑前端同一份 TS(type stripping),不移植 Python:
 *   node --experimental-strip-types web/scripts/build-bull-board.mjs [--data <dir>] [--log <dir>]
 * 預設 --data = web/public/data、--log = <repo>/data/bull_board_log。
 *
 * 讀 radar.json → 逐檔讀 stocks/*.json(一次一檔,不同時持有原始 JSON)→ summaryFromStockJson
 * (與個股頁同一次呼叫)→ selectBoard → 原子寫 bull_board.json(.tmp → rename)→ 追加一行到
 * <log>/YYYY-MM.jsonl,並把當月檔複製到 <data>/bull_board_log/YYYY-MM.jsonl。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { boardLogLine, buildBullBoard, selectBoard } from "../lib/bullBoard.ts";
import { lastCandleDate, summaryFromStockJson } from "../lib/bullBearFromStock.ts";

const t0 = performance.now();
const here = path.dirname(fileURLToPath(import.meta.url));
const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, v, i, all) => (v.startsWith("--") ? [...acc, [v.slice(2), all[i + 1]]] : acc), []),
);
const DATA = path.resolve(args.data ?? path.join(here, "..", "public", "data"));
const LOG = path.resolve(args.log ?? path.join(here, "..", "..", "data", "bull_board_log"));

const readJson = (p) => JSON.parse(fs.readFileSync(p, "utf8"));

/** 台北時間的 ISO 字串(+08:00),與 radar.json 的 generated_at 同一種寫法。 */
function taipeiIso(d = new Date()) {
  return new Date(d.getTime() + 8 * 3600_000).toISOString().replace(/\.\d{3}Z$/, "+08:00");
}

function writeAtomic(file, text) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, text);
  fs.renameSync(tmp, file);
}

function chgPct(candles) {
  const n = candles?.length ?? 0;
  if (n < 2 || !candles[n - 2].c) return null;
  return Math.round(((candles[n - 1].c - candles[n - 2].c) / candles[n - 2].c) * 10000) / 100;
}

/** 紀錄最早的資料日:讀最早那個月檔的第一行。 */
function earliestLogged(dir) {
  if (!fs.existsSync(dir)) return null;
  const months = fs.readdirSync(dir).filter((f) => /^\d{4}-\d{2}\.jsonl$/.test(f)).sort();
  for (const m of months) {
    const first = fs.readFileSync(path.join(dir, m), "utf8").split("\n").find((l) => l.trim());
    if (first) {
      try {
        return JSON.parse(first).data_date ?? null;
      } catch {
        /* 壞行:看下一個月 */
      }
    }
  }
  return null;
}

const radar = readJson(path.join(DATA, "radar.json"));
const radarById = new Map((radar.stocks ?? []).map((s) => [s.id, s]));
const stockDir = path.join(DATA, "stocks");
const files = fs.readdirSync(stockDir).filter((f) => f.endsWith(".json")).sort();

const cands = [];
let holdersWeek = null;
let failed = 0;
const tRead = performance.now();
for (const f of files) {
  let data;
  try {
    data = readJson(path.join(stockDir, f));
  } catch (e) {
    failed += 1;
    console.warn(`bull-board: skip ${f}: ${e?.message ?? e}`);
    continue;
  }
  const lastT = lastCandleDate(data);
  const scored = data.scores != null;
  // 母體外的檔不必算多空(省時間);母體判斷仍交給 selectBoard。
  if (!scored || lastT !== radar.data_date) continue;
  const r = radarById.get(data.id);
  const last = data.candles[data.candles.length - 1];
  const hw = data.holders_history?.[0]?.t ?? null;
  if (hw && (!holdersWeek || hw > holdersWeek)) holdersWeek = hw;
  let summary;
  try {
    summary = summaryFromStockJson(data);
  } catch (e) {
    failed += 1;
    console.warn(`bull-board: summary failed ${f}: ${e?.message ?? e}`);
    continue;
  }
  cands.push({
    id: data.id,
    name: r?.name ?? data.name,
    market: r?.market ?? data.market,
    industry: r?.industry ?? data.industry ?? null,
    close: r?.close ?? last?.c ?? null,
    chg_pct: r ? r.chg_pct ?? null : chgPct(data.candles),
    turnover: r?.turnover ?? last?.amt ?? null,
    final: r?.scores?.final ?? data.scores?.final ?? null,
    state: r?.state ?? null,
    scored,
    lastT,
    summary,
  });
}
const readMs = performance.now() - tRead;

const sel = selectBoard(cands, radar.data_date);
const generatedAt = taipeiIso();
const logged = earliestLogged(LOG);
const logFrom = logged && logged < radar.data_date ? logged : radar.data_date;
const board = buildBullBoard(radar, sel, { generatedAt, logFrom, holdersWeek });

writeAtomic(path.join(DATA, "bull_board.json"), JSON.stringify(board));

const month = generatedAt.slice(0, 7);
const logFile = path.join(LOG, `${month}.jsonl`);
fs.mkdirSync(LOG, { recursive: true });
fs.appendFileSync(logFile, `${JSON.stringify(boardLogLine(board, sel))}\n`);
writeAtomic(path.join(DATA, "bull_board_log", `${month}.jsonl`), fs.readFileSync(logFile, "utf8"));

const elapsed = (performance.now() - t0) / 1000;
console.log(
  `bull-board timing: files=${files.length} universe=${board.universe} qualified=${board.qualified} ` +
    `failed=${failed} read+summary=${(readMs / 1000).toFixed(2)}s per_file=${files.length ? (readMs / files.length).toFixed(2) : 0}ms ` +
    `elapsed=${elapsed.toFixed(2)}s`,
);
