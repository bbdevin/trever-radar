// 執行: node --test --experimental-strip-types web/lib/bullBoardBuild.test.ts
//
// web/scripts/build-bull-board.mjs 的冒煙測試:對暫存目錄裡自造的 fixture 實際跑一次建置器
// (舊格式 JSON 混在裡面),輸出可解析、母體 ≥1、相同重建不追加(名單變了/新日/壞行才追加)、
// 異地副本與紀錄相同;以及 scripts/dedupe-bull-board-log.mjs 壓縮既有重複行。
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

function fixture(dir: string, DAY = "2026-09-08") {
  fs.mkdirSync(path.join(dir, "stocks"), { recursive: true });
  const radar = {
    data_date: DAY,
    generated_at: `${DAY}T22:00:00+08:00`,
    freshness: { insti: { date: DAY, stale: false }, branch: { date: DAY, stale: false }, margin: { date: "2026-09-07", stale: true } },
    themes: [{ name: "散熱", vs20: 1.4 }, { name: "AI", vs20: 2.2 }],
    stocks: [{ id: "1111", name: "多方甲", market: "twse", industry: "電子", themes: ["冷門", "散熱", "AI"], close: 89.5, chg_pct: 0.56, turnover: 5e8, scores: { final: 55 }, state: "armed" }],
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

test("建置器對自造 fixture 跑兩次:輸出可解析、相同重建不追加、異地副本一致", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bull-board-"));
  try {
    const data = path.join(root, "data");
    const log = path.join(root, "log");
    fixture(data);
    const run = () =>
      execFileSync(process.execPath, ["--experimental-strip-types", "--no-warnings", SCRIPT, "--data", data, "--log", log], { encoding: "utf8" });
    const out1 = run();
    assert.match(out1, /bull-board timing: files=3 layout=legacy universe=2 qualified=1 /);
    const board = JSON.parse(fs.readFileSync(path.join(data, "bull_board.json"), "utf8"));
    assert.equal(board.version, "bull-board-v1");
    assert.equal(board.universe, 2);
    assert.equal(board.qualified, 1);
    assert.equal(board.log_from, DAY);
    assert.equal(board.entries[0].id, "1111");
    assert.equal(board.entries[0].name, "多方甲");
    assert.equal(board.entries[0].state, "armed");
    // 族群檢視用(只影響顯示):今日在榜題材中最熱的那個
    assert.deepEqual(board.entries[0].theme, { name: "AI", vs20: 2.2 });
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

    // 名單沒變的重建:只差 generated_at → 不追加
    const out2 = run();
    assert.match(out2, /bull-board log: unchanged, skipped/);
    const lines2 = fs.readFileSync(logFile, "utf8").trim().split("\n");
    assert.equal(lines2.length, 1);
    assert.equal(fs.readFileSync(path.join(data, "bull_board_log", months[0]), "utf8"), fs.readFileSync(logFile, "utf8"));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

/** 每個測試一個暫存根目錄;回傳跑建置器的函式與當月紀錄檔路徑。 */
function withBuilder(fn: (h: { data: string; run: () => string; logLines: () => string[]; logFile: () => string }) => void) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bull-board-"));
  const data = path.join(root, "data");
  const log = path.join(root, "log");
  const logFile = () => path.join(log, fs.readdirSync(log).filter((f) => f.endsWith(".jsonl"))[0]);
  try {
    fn({
      data,
      run: () => execFileSync(process.execPath, ["--experimental-strip-types", "--no-warnings", SCRIPT, "--data", data, "--log", log], { encoding: "utf8" }),
      logLines: () => fs.readFileSync(logFile(), "utf8").split("\n").filter((l) => l.trim()),
      logFile,
    });
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

/** 把 fixture 的 stocks/*.json 改寫成拆檔佈局(core/chips/hist),舊單一檔刪掉。 */
function toSplitLayout(data: string, cut = "2026-09-01") {
  const stockDir = path.join(data, "stocks");
  for (const d of ["core", "chips", "hist"]) fs.mkdirSync(path.join(stockDir, d), { recursive: true });
  for (const f of fs.readdirSync(stockDir).filter((n) => n.endsWith(".json"))) {
    const full = JSON.parse(fs.readFileSync(path.join(stockDir, f), "utf8"));
    const chips: Record<string, unknown> = { version: 1, id: full.id };
    const core: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(full)) {
      if (["branch_history", "branch_pctile_counts", "branch_tags", "branch_pnl_est"].includes(k)) chips[k] = v;
      else core[k] = v;
    }
    const idx = full.candles.findIndex((c: { t: string }) => c.t >= cut);
    let hist = null;
    if (idx > 0) {
      hist = { version: 1, id: full.id, cut, bars: idx, candles: full.candles.slice(0, idx) };
      core.candles = full.candles.slice(idx);
      fs.writeFileSync(path.join(stockDir, "hist", `${full.id}.deadbeef.json`), JSON.stringify(hist));
    }
    core.parts = {
      version: 1,
      hist: hist ? { file: `hist/${full.id}.deadbeef.json`, bars: hist.bars, cut, first: hist.candles[0].t } : null,
      chips: { file: `chips/${full.id}.json`, keys: Object.keys(chips).filter((k) => k !== "version" && k !== "id") },
    };
    fs.writeFileSync(path.join(stockDir, "core", f), JSON.stringify(core));
    fs.writeFileSync(path.join(stockDir, "chips", f), JSON.stringify(chips));
    fs.rmSync(path.join(stockDir, f));
  }
}

test("拆檔佈局(docs/44 P1):建置器讀 core+chips+hist 接回,bull_board.json 與舊佈局相同", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bull-board-split-"));
  try {
    const env = { ...process.env, BULL_BOARD_NOW: "2026-09-08T14:00:00Z" };
    const run = (data: string, log: string) =>
      execFileSync(process.execPath, ["--experimental-strip-types", "--no-warnings", SCRIPT, "--data", data, "--log", log], { encoding: "utf8", env });
    const a = path.join(root, "legacy");
    const b = path.join(root, "split");
    fixture(a);
    fixture(b);
    toSplitLayout(b);
    assert.ok(!fs.existsSync(path.join(b, "stocks", "1111.json")));
    assert.ok(fs.existsSync(path.join(b, "stocks", "hist", "1111.deadbeef.json")));
    const outA = run(a, path.join(root, "logA"));
    const outB = run(b, path.join(root, "logB"));
    assert.match(outA, /layout=legacy/);
    assert.match(outB, /files=3 layout=split universe=2 qualified=1 /);
    const boardA = fs.readFileSync(path.join(a, "bull_board.json"), "utf8");
    const boardB = fs.readFileSync(path.join(b, "bull_board.json"), "utf8");
    assert.equal(boardB, boardA);
    assert.ok(JSON.parse(boardA).qualified === 1);

    // hist 檔不見了(並行 export 剛換雜湊)→ 警告並略過該檔、不中斷。即使旁邊殘留舊單一檔
    // stocks/1111.json(2026-10-07 起 export 不再更新它)也**不**拿來頂替。
    const c = path.join(root, "split-hist-missing");
    fixture(c);
    toSplitLayout(c);
    fs.rmSync(path.join(c, "stocks", "hist", "1111.deadbeef.json"));
    const outC = run(c, path.join(root, "logC"));
    assert.match(outC, /layout=split universe=1 qualified=0 failed=1/); // 警告走 stderr
    assert.ok(fs.existsSync(path.join(c, "bull_board.json")));
    fs.writeFileSync(path.join(c, "stocks", "1111.json"), fs.readFileSync(path.join(a, "stocks", "1111.json")));
    const outD = run(c, path.join(root, "logD"));
    assert.match(outD, /layout=split universe=1 qualified=0 failed=1/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("名單變了(例:晚間分點到齊)→ 同一 data_date 照樣追加,保留當日演變", () => {
  withBuilder(({ data, run, logLines }) => {
    fixture(data);
    run();
    // 舊格式那檔改成也入榜:名單變了
    const p = path.join(data, "stocks", "2222.json");
    const s = JSON.parse(fs.readFileSync(p, "utf8"));
    s.raw_reasons = [
      { code: "B1_BRANCH_STREAK", text: "主力分點連 3 日買超" },
      { code: "I_TRUST_BUY", text: "投信買超 800 張" },
      { code: "T2_20D_HIGH", text: "創20日新高" },
    ];
    fs.writeFileSync(p, JSON.stringify(s));
    const out = run();
    assert.doesNotMatch(out, /unchanged, skipped/);
    const lines = logLines().map((l) => JSON.parse(l));
    assert.equal(lines.length, 2);
    assert.equal(lines[0].data_date, DAY);
    assert.equal(lines[1].data_date, DAY);
    assert.notDeepEqual(lines[0].entries, lines[1].entries);
  });
});

test("新的資料日 → 追加", () => {
  withBuilder(({ data, run, logLines }) => {
    fixture(data);
    run();
    fixture(data, "2026-09-09");
    run();
    assert.deepEqual(logLines().map((l) => JSON.parse(l).data_date), [DAY, "2026-09-09"]);
  });
});

test("最後一行壞掉(截斷、沒有換行)→ 照樣追加,而且新行自成一行", () => {
  withBuilder(({ data, run, logLines, logFile }) => {
    fixture(data);
    run();
    fs.appendFileSync(logFile(), '{"version":"bull-board-v1","data_da');
    const out = run();
    assert.doesNotMatch(out, /unchanged, skipped/);
    const lines = logLines();
    assert.equal(lines.length, 3);
    assert.throws(() => JSON.parse(lines[1]));
    assert.equal(JSON.parse(lines[2]).data_date, DAY);
  });
});

test("跨月:10/30 建置、11/02 名單沒變再建 → exit 0、不追加、不建 11 月檔、副本照樣更新", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bull-board-month-"));
  try {
    const data = path.join(root, "data");
    const log = path.join(root, "log");
    fixture(data, "2026-10-30");
    const runAt = (now: string) =>
      execFileSync(process.execPath, ["--experimental-strip-types", "--no-warnings", SCRIPT, "--data", data, "--log", log], {
        encoding: "utf8",
        env: { ...process.env, BULL_BOARD_NOW: now },
      });
    runAt("2026-10-30T14:00:00Z"); // 台北 22:00
    assert.deepEqual(fs.readdirSync(log), ["2026-10.jsonl"]);
    fs.rmSync(path.join(data, "bull_board_log"), { recursive: true });
    const out = runAt("2026-11-02T02:00:00Z"); // 台北 11/02 10:00,execFileSync 非 0 會丟例外
    assert.match(out, /bull-board log: unchanged, skipped/);
    assert.deepEqual(fs.readdirSync(log), ["2026-10.jsonl"]);
    assert.equal(fs.readFileSync(path.join(log, "2026-10.jsonl"), "utf8").trim().split("\n").length, 1);
    assert.deepEqual(fs.readdirSync(path.join(data, "bull_board_log")), ["2026-10.jsonl"]);
    // 名單變了的跨月重建 → 寫進當月(11 月)檔,兩個月檔都有副本
    const p = path.join(data, "stocks", "1111.json");
    const s = JSON.parse(fs.readFileSync(p, "utf8"));
    s.raw_reasons = s.raw_reasons.slice(0, 2);
    fs.writeFileSync(p, JSON.stringify(s));
    assert.doesNotMatch(runAt("2026-11-02T03:00:00Z"), /unchanged, skipped/);
    assert.deepEqual(fs.readdirSync(log).sort(), ["2026-10.jsonl", "2026-11.jsonl"]);
    assert.deepEqual(fs.readdirSync(path.join(data, "bull_board_log")).sort(), ["2026-10.jsonl", "2026-11.jsonl"]);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("壓縮工具:預設 dry-run 不動檔;--write 每段相同行留第一行,A→B→A 三行都留", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bull-board-dedupe-"));
  try {
    const DEDUPE = path.join(here, "..", "scripts", "dedupe-bull-board-log.mjs");
    const rec = (date: string, gen: string, ids: string[]) =>
      JSON.stringify({ version: "bull-board-v1", data_date: date, generated_at: gen, radar_generated_at: gen, universe: 2, qualified: ids.length, universe_ids: ["1", "2"], entries: ids.map((id) => ({ id })) });
    const lines = [
      rec("2026-10-01", "T1", ["1"]),
      rec("2026-10-01", "T2", ["1"]), // 與上一行相同 → 刪
      rec("2026-10-01", "T3", ["1", "2"]), // 名單變了 → 留
      rec("2026-10-01", "T4", ["1"]), // 又變回 A,但不同於同日上一行 → 留
      rec("2026-10-02", "T5", ["2"]),
      rec("2026-10-02", "T6", ["2"]), // 刪
      rec("2026-10-02", "T7", ["2"]), // 刪
      "{corrupt",
      rec("2026-10-02", "T8", ["2"]), // 壞行之後 → 留
    ];
    const file = path.join(root, "2026-10.jsonl");
    const original = `${lines.join("\n")}\n`;
    fs.writeFileSync(file, original);
    const dedupe = (...extra: string[]) =>
      execFileSync(process.execPath, ["--experimental-strip-types", "--no-warnings", DEDUPE, file, ...extra], { encoding: "utf8" });

    assert.match(dedupe(), /dedupe dry-run: .* lines=9 kept=6 dropped=3 corrupt=1/);
    assert.equal(fs.readFileSync(file, "utf8"), original);

    // --write 沒有 --locked → 拒絕,不動檔
    assert.throws(() => dedupe("--write"), /requires --locked/);
    assert.equal(fs.readFileSync(file, "utf8"), original);

    assert.match(dedupe("--write", "--locked"), /dedupe write: .* kept=6 dropped=3/);
    const kept = fs.readFileSync(file, "utf8").split("\n").filter((l) => l.trim());
    assert.deepEqual(kept, [lines[0], lines[2], lines[3], lines[4], "{corrupt", lines[8]]);
    assert.ok(!fs.existsSync(`${file}.tmp`));
    // 再跑一次:無可刪
    assert.match(dedupe("--write", "--locked"), /dropped=0/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
