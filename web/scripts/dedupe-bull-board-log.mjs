/**
 * 一次性維護(docs/48 §1.1,不是建置器改寫):壓縮 bull_board_log 月檔裡「同一 data_date、內容相同只差
 * 時間戳」的重複行。判定與建置器的跳過規則相同(lib/bullBoardLog.ts dedupeLogText):每段相同行留第一行,
 * 所以 §2 紀錄版 r(t) 選到的內容不變。壞行原樣保留。逐檔處理:跨月的重複(11/01 重建 10/31)不處理。
 *
 *   dry-run:node --experimental-strip-types --no-warnings web/scripts/dedupe-bull-board-log.mjs <file.jsonl>...
 *   寫入:  flock -w 600 /tmp/radar-db.lock node --experimental-strip-types --no-warnings \
 *             web/scripts/dedupe-bull-board-log.mjs <file.jsonl>... --write --locked
 *
 * --write 必須同時給 --locked:建置器在各輪握著 /tmp/radar-db.lock 時追加紀錄,壓縮要在同一把鎖下跑,
 * 否則讀檔到 rename 之間的追加會遺失(--locked 只是宣告「我已在 flock 底下」,工具本身不取鎖)。
 * mid-backfill-publish 不握鎖、只在開頭看鎖是否被占用,所以 rename 前仍再比一次大小/mtime,變了就放棄。
 * 寫法:先寫 <file>.tmp 再 rename。web/public/data 的副本在下一次建置(或 deploy)時本就會由主本覆蓋。
 */
import fs from "node:fs";

import { dedupeLogText } from "../lib/bullBoardLog.ts";

const argv = process.argv.slice(2);
const write = argv.includes("--write");
const locked = argv.includes("--locked");
const files = argv.filter((a) => !a.startsWith("--"));
if (!files.length) {
  console.error("usage: dedupe-bull-board-log.mjs <file.jsonl>... [--write --locked]");
  process.exit(2);
}
if (write && !locked) {
  console.error("dedupe: --write requires --locked; run under `flock -w 600 /tmp/radar-db.lock ... --write --locked`");
  process.exit(2);
}

let rc = 0;
for (const file of files) {
  if (!fs.existsSync(file)) {
    console.error(`dedupe: ${file}: not found`);
    rc = 1;
    continue;
  }
  const before = fs.statSync(file);
  const r = dedupeLogText(fs.readFileSync(file, "utf8"));
  const mode = write ? "write" : "dry-run";
  console.log(`dedupe ${mode}: ${file} lines=${r.total} kept=${r.kept} dropped=${r.dropped} corrupt=${r.corrupt}`);
  if (!write || r.dropped === 0) continue;
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, r.text);
  // 緊接 rename 前再比一次;剩下的窗口只有這兩個系統呼叫之間。
  const now = fs.statSync(file);
  if (now.size !== before.size || now.mtimeMs !== before.mtimeMs) {
    fs.rmSync(tmp, { force: true });
    console.error(`dedupe: ${file} changed while compacting; aborted, rerun`);
    rc = 1;
    continue;
  }
  fs.renameSync(tmp, file);
}
process.exit(rc);
