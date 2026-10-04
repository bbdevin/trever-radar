// 執行: node --test --experimental-strip-types web/lib/facts/series.test.ts
//
// 還原 + 週/月重取樣(docs/46 v2 §2.8):部分週、週中假日、週一假日、跨年週、月桶、
// 分割前後還原後逐值相等、零量。
import assert from "node:assert/strict";
import { test } from "node:test";

import { resample } from "../resample.ts";
import type { Candle } from "../types.ts";
import { adjustCandles, allSeries, buildSeries } from "./series.ts";

const k = (t: string, c: number, v = 100, af = 1, o = c, h = c + 1, l = c - 1): Candle => ({ t, o, h, l, c, v, amt: c * v, af });

test("週K:週一為桶;部分週、週中假日、週一假日、跨年週", () => {
  const cs = [
    k("2025-12-29", 10), k("2025-12-30", 11), k("2025-12-31", 12), // 跨年週(週一 12/29)
    k("2026-01-02", 13), // 同一週的週五(1/1 假日)
    k("2026-01-06", 14), k("2026-01-07", 15), // 週一 1/5 假日 → 仍歸 1/5 那週
    k("2026-01-12", 16), k("2026-01-14", 17), // 週中假日
    k("2026-01-19", 18), // 進行中的部分週
  ];
  const w = resample(cs, "W");
  assert.deepEqual(w.map((b) => b.t), ["2026-01-02", "2026-01-07", "2026-01-14", "2026-01-19"]);
  assert.deepEqual(w.map((b) => [b.o, b.c, b.v]), [[10, 13, 400], [14, 15, 200], [16, 17, 200], [18, 18, 100]]);
  const S = buildSeries(cs, "W");
  assert.deepEqual(S.days, [4, 2, 2, 1]);
});

test("月K:日曆月為桶;零量照樣合併", () => {
  const cs = [k("2026-01-30", 10, 0), k("2026-02-02", 11, 50), k("2026-02-27", 12, 0), k("2026-03-02", 13, 7)];
  const m = resample(cs, "M");
  assert.deepEqual(m.map((b) => [b.t, b.v, b.h, b.l]), [["2026-01-30", 0, 11, 9], ["2026-02-27", 50, 13, 10], ["2026-03-02", 7, 14, 12]]);
  assert.deepEqual(buildSeries(cs, "M").days, [1, 2, 1]);
});

test("還原:價 × af/af_last、量 × af_last/af;1 拆 2 分割前後逐值相等", () => {
  // 分割前 af=0.5(價格是現在的 2 倍、股數一半),分割後 af=1
  const raw = [
    k("2026-03-02", 200, 100, 0.5), k("2026-03-03", 200, 100, 0.5),
    k("2026-03-04", 100, 200, 1, 100, 100.5, 99.5), k("2026-03-05", 100, 200, 1, 100, 100.5, 99.5),
  ];
  const adj = adjustCandles(raw);
  assert.deepEqual(adj.map((c) => c.c), [100, 100, 100, 100]);
  assert.deepEqual(adj.map((c) => c.v), [200, 200, 200, 200]);
  // 還原後再重取樣:分割那週的高低與量和「從頭就是這個股本」一樣
  const same = [k("2026-03-02", 100, 200), k("2026-03-03", 100, 200), k("2026-03-04", 100, 200), k("2026-03-05", 100, 200)];
  const a = buildSeries(adj, "W");
  const b = buildSeries(same.map((c) => ({ ...c, h: c.c + 0.5, l: c.c - 0.5 })), "W");
  assert.deepEqual([a.c, a.v], [b.c, b.v]);
  assert.deepEqual(a.h, [100.5]);
});

test("缺 K 棒、收盤缺值 → 空序列,不丟例外", () => {
  const s = allSeries(undefined);
  assert.equal(s.D.c.length, 0);
  assert.equal(s.W.c.length, 0);
  const odd = adjustCandles([{ ...k("2026-03-02", 100), c: null as unknown as number }, k("2026-03-03", 100)]);
  assert.equal(odd.length, 1);
});
