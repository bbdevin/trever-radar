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
 * <log>/YYYY-MM.jsonl(同一 data_date 最後一行內容相同、只差時間戳 → 不追加,見 lib/bullBoardLog.ts),
 * 並把當月檔複製到 <data>/bull_board_log/YYYY-MM.jsonl。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { boardLogLine, buildBullBoard, selectBoard } from "../lib/bullBoard.ts";
import { lastCandleDate, summaryFromStockJson } from "../lib/bullBearFromStock.ts";
import { shouldAppendLogLine } from "../lib/bullBoardLog.ts";
import { mergeIfSplit } from "../lib/stockParts.ts";
import { hottestListedTheme } from "../lib/themeGroups.ts";

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
// 拆檔佈局(docs/44 P1 §3.2):有 stocks/core/ 就讀核心並把 chips/hist 接回(與個股頁同一個
// mergeStockParts);沒有就讀舊單一檔 stocks/*.json。兩種佈局算出來的 bull_board.json 相同。
const coreDir = path.join(stockDir, "core");
const splitLayout = fs.existsSync(coreDir) && fs.statSync(coreDir).isDirectory();
const readDir = splitLayout ? coreDir : stockDir;
const files = fs.readdirSync(readDir).filter((f) => f.endsWith(".json")).sort();
// 拆檔佈局下 hist/chips 接回;hist 檔不在(並行 export 剛換雜湊)→ 有舊單一檔就讀舊檔,沒有就丟出讓外層略過。
const mergeParts = (f, core) =>
  mergeIfSplit(core, (rel) => {
    const p = path.join(stockDir, rel);
    if (fs.existsSync(p)) return readJson(p);
    const legacy = path.join(stockDir, f);
    if (rel.startsWith("hist/") && fs.existsSync(legacy)) throw Object.assign(new Error("hist missing"), { legacy });
    throw new Error(`part missing: ${rel}`);
  });

const cands = [];
let holdersWeek = null;
let failed = 0;
const tRead = performance.now();
for (const f of files) {
  let data;
  try {
    data = readJson(path.join(readDir, f));
  } catch (e) {
    failed += 1;
    console.warn(`bull-board: skip ${f}: ${e?.message ?? e}`);
    continue;
  }
  // 最後一根 K 與 scores 都在核心:母體外的檔連 hist/chips 都不必讀(省時間)。母體判斷仍交給 selectBoard。
  const lastT = lastCandleDate(data);
  const scored = data.scores != null;
  if (!scored || lastT !== radar.data_date) continue;
  if (splitLayout) {
    try {
      data = mergeParts(f, data);
    } catch (e) {
      if (e?.legacy) {
        try {
          data = readJson(e.legacy);
        } catch (e2) {
          failed += 1;
          console.warn(`bull-board: skip ${f}: ${e2?.message ?? e2}`);
          continue;
        }
      } else {
        failed += 1;
        console.warn(`bull-board: skip ${f}: ${e?.message ?? e}`);
        continue;
      }
    }
  }
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
    // 族群檢視用(docs/48 §1.1,只影響顯示):與首頁「題材」排序同一個最熱題材挑法,只取今日在榜題材
    theme: hottestListedTheme(r?.themes, radar.themes),
  });
}
const readMs = performance.now() - tRead;

const sel = selectBoard(cands, radar.data_date);
// BULL_BOARD_NOW(ISO)只給測試固定時鐘用(跨月重建);正式環境不設。
const generatedAt = taipeiIso(process.env.BULL_BOARD_NOW ? new Date(process.env.BULL_BOARD_NOW) : new Date());
const logged = earliestLogged(LOG);
const logFrom = logged && logged < radar.data_date ? logged : radar.data_date;
const board = buildBullBoard(radar, sel, { generatedAt, logFrom, holdersWeek });

writeAtomic(path.join(DATA, "bull_board.json"), JSON.stringify(board));

const month = generatedAt.slice(0, 7);
const logFile = path.join(LOG, `${month}.jsonl`);
fs.mkdirSync(LOG, { recursive: true });
const readIf = (p) => (fs.existsSync(p) ? fs.readFileSync(p, "utf8") : "");
const prevLog = readIf(logFile);
// 跨月重建(例:11/01 重建 10/31):同一 data_date 的前幾行在資料日那個月的檔裡。
const dataMonthFile = path.join(LOG, `${String(radar.data_date).slice(0, 7)}.jsonl`);
const history = dataMonthFile === logFile ? prevLog : readIf(dataMonthFile) + "\n" + prevLog;
const logLine = boardLogLine(board, sel);
if (shouldAppendLogLine(history, logLine)) {
  // 上一行若被截斷(沒有換行),先補換行,新行才不會黏在壞行後面。
  const sep = prevLog && !prevLog.endsWith("\n") ? "\n" : "";
  fs.appendFileSync(logFile, `${sep}${JSON.stringify(logLine)}\n`);
} else {
  console.log("bull-board log: unchanged, skipped");
}
// 異地副本:資料日那個月與當月,存在的才複製(跳過追加時當月檔可能還不存在)。
for (const f of new Set([dataMonthFile, logFile])) {
  if (fs.existsSync(f)) writeAtomic(path.join(DATA, "bull_board_log", path.basename(f)), fs.readFileSync(f, "utf8"));
}

const elapsed = (performance.now() - t0) / 1000;
console.log(
  `bull-board timing: files=${files.length} layout=${splitLayout ? "split" : "legacy"} universe=${board.universe} qualified=${board.qualified} ` +
    `failed=${failed} read+summary=${(readMs / 1000).toFixed(2)}s per_file=${files.length ? (readMs / files.length).toFixed(2) : 0}ms ` +
    `elapsed=${elapsed.toFixed(2)}s`,
);
