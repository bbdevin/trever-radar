"use client";

import { useEffect, useMemo, useState } from "react";
import { dataFetch } from "@/lib/dataFetch";

/**
 * 股名解析:先用呼叫端給的(首頁評分池 radar.stocks),缺的才去讀全市場
 * `stocks_index.json`(搜尋框用的同一份)。讀不到就照舊只有代號,不編一個名字。
 * 期貨名單與舉旗紀錄共用(舉旗的股票常不在評分池裡,2371、3045 曾只顯示代號)。
 */
export function useStockNames(
  nameById: ReadonlyMap<string, string>,
  stockIds: ReadonlyArray<string>,
): ReadonlyMap<string, string> {
  const [indexNames, setIndexNames] = useState<ReadonlyMap<string, string> | null>(null);
  const needsIndex = stockIds.some((id) => !nameById.get(id));
  useEffect(() => {
    if (!needsIndex || indexNames) return;
    let cancelled = false;
    dataFetch("/data/stocks_index.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((rows: unknown) => {
        if (cancelled || !Array.isArray(rows)) return;
        const m = new Map<string, string>();
        for (const row of rows) {
          if (Array.isArray(row) && typeof row[0] === "string" && typeof row[1] === "string") m.set(row[0], row[1]);
        }
        setIndexNames(m);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [needsIndex, indexNames]);
  return useMemo(() => {
    if (!indexNames) return nameById;
    const merged = new Map(indexNames);
    nameById.forEach((v, k) => merged.set(k, v));
    return merged;
  }, [nameById, indexNames]);
}
