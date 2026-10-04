/**
 * 一次性維護:壓縮 bull_board_log 月檔裡「同一 data_date、內容相同只差時間戳」的重複行(docs/48 §1.1)。
 * 判定與建置器的跳過規則相同(lib/bullBoardLog.ts dedupeLogText):每段相同行留第一行,
 * 所以 §2 紀錄版 r(t) 選到的內容不變。壞行原樣保留。
 *
 *   node --experimental-strip-types --no-warnings web/scripts/dedupe-bull-board-log.mjs <file.jsonl>... [--write]
 *
 * 預設 dry-run,只印計數;--write 才寫:先寫 <file>.tmp 再 rename。讀檔後若檔案大小/mtime 變了
 * (建置器剛好追加)就放棄該檔、exit 1,重跑即可。
 */
import fs from "node:fs";

import { dedupeLogText } from "../lib/bullBoardLog.ts";

const argv = process.argv.slice(2);
const write = argv.includes("--write");
const files = argv.filter((a) => !a.startsWith("--"));
if (!files.length) {
  console.error("usage: dedupe-bull-board-log.mjs <file.jsonl>... [--write]");
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
