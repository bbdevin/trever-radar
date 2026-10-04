// 執行: node --test --experimental-strip-types web/lib/bullBoardBuild.test.ts
//
// web/scripts/build-bull-board.mjs 的冒煙測試:對暫存目錄裡自造的 fixture 實際跑一次建置器
// (舊格式 JSON 混在裡面),輸出可解析、母體 ≥1、紀錄檔每跑一次多一行、異地副本與紀錄相同。
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = path.join(here, "..", "scripts", "build-bull-board.mjs");
const DAY = "2026-09-08";

function candles(n: number, lastDay: string) {
  const end = Date.parse(`${lastDay}T00:00:00Z`);
  return Array.from({ length: n }, (_, i) => {
    const c = 50 + i * 0.5;
    const t = new Date(end - (n - 1 - i) * 86400_000).toISOString().slice(0, 10);
    return { t, o: c - 0.2, h: c + 0.5, l: c - 0.6, c, v: 2000 + i * 20, amt: c * 2e6, af: 1 };
  });
}

function fixture(dir: string) {
  fs.mkdirSync(path.join(dir, "stocks"), { recursive: true });
  const radar = {
    data_date: DAY,
    generated_at: `${DAY}T22:00:00+08:00`,
    freshness: { insti: { date: DAY, stale: false }, branch: { date: DAY, stale: false }, margin: { date: "2026-09-07", stale: true } },
    stocks: [{ id: "1111", name: "多方甲", market: "twse", industry: "電子", close: 89.5, chg_pct: 0.56, turnover: 5e8, scores: { final: 55 }, state: "armed" }],
  };
  fs.writeFileSync(path.join(dir, "radar.json"), JSON.stringify(radar));
  // 三條 rank 4 的多方(分點、法人、技術),入榜
  fs.writeFileSync(
    path.join(dir, "stocks", "1111.json"),
    JSON.stringify({
      id: "1111", name: "多方甲", market: "twse", candles: candles(80, DAY), scores: { final: 55 },
      reasons: [], raw_reasons: [
        { code: "B1_BRANCH_STREAK", text: "主力分點連 3 日買超" },
        { code: "I_TRUST_BUY", text: "投信買超 800 張" },
        { code: "T2_20D_HIGH", text: "創20日新高" },
      ],
      risks: [], technical: null, branches: [], warrant: null, warrant_history: [], active_warrants: [],
    }),
  );
  // 舊格式(缺大部分鍵)、在母體內
  fs.writeFileSync(
    path.join(dir, "stocks", "2222.json"),
    JSON.stringify({ id: "2222", name: "舊格式", market: "tpex", candles: candles(5, DAY), scores: { final: 40 }, reasons: ["某理由"], risks: ["外資連5日賣超"], technical: null }),
  );
  // 沒有評分 → 不在母體
  fs.writeFileSync(path.join(dir, "stocks", "3333.json"), JSON.stringify({ id: "3333", name: "無評分", market: "twse", candles: candles(30, DAY), scores: null, reasons: [], risks: [], technical: null }));
}

test("建置器對自造 fixture 跑兩次:輸出可解析、紀錄多一行、異地副本一致", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bull-board-"));
  try {
    const data = path.join(root, "data");
    const log = path.join(root, "log");
    fixture(data);
    const run = () =>
      execFileSync(process.execPath, ["--experimental-strip-types", "--no-warnings", SCRIPT, "--data", data, "--log", log], { encoding: "utf8" });
    const out1 = run();
    assert.match(out1, /bull-board timing: files=3 universe=2 qualified=1 /);
    const board = JSON.parse(fs.readFileSync(path.join(data, "bull_board.json"), "utf8"));
    assert.equal(board.version, "bull-board-v1");
    assert.equal(board.universe, 2);
    assert.equal(board.qualified, 1);
    assert.equal(board.log_from, DAY);
    assert.equal(board.entries[0].id, "1111");
    assert.equal(board.entries[0].name, "多方甲");
    assert.equal(board.entries[0].state, "armed");
    assert.ok(board.entries[0].bull_key_n >= 3);
    assert.match(board.generated_at, /\+08:00$/);
    assert.ok(!fs.existsSync(path.join(data, "bull_board.json.tmp")));

    const months = fs.readdirSync(log);
    assert.equal(months.length, 1);
    const logFile = path.join(log, months[0]);
    const lines1 = fs.readFileSync(logFile, "utf8").trim().split("\n");
    assert.equal(lines1.length, 1);
    const rec = JSON.parse(lines1[0]);
    assert.deepEqual(rec.universe_ids, ["1111", "2222"]);
    assert.equal(rec.entries[0].id, "1111");

    run();
    const lines2 = fs.readFileSync(logFile, "utf8").trim().split("\n");
    assert.equal(lines2.length, 2);
    assert.equal(fs.readFileSync(path.join(data, "bull_board_log", months[0]), "utf8"), fs.readFileSync(logFile, "utf8"));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
