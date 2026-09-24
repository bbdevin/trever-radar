// 綜合榜的空狀態句子(2026-09-24)。
//
// 綜合榜在 49 個評分日裡有 40 天是空的,而「空」有兩個完全不同的意思:
//   withheld = true  → 分點/法人還沒到齊,export 刻意不排名(不知道)
//   withheld = false → 資料齊全,今天真的沒有任何一檔達門檻(知道沒有)
// 把兩者講成同一句,就是把「不知道」講成「知道沒有」。句子由這裡的純函式產出、
// 由 node --test 鎖住,因為這條規則講的是「不可以說什麼」,讀 JSX 驗不出來。
//
// 缺 meta(舊 payload + 新程式碼,部署路徑分開時一定會出現)→ 回 null,由呼叫端
// 沿用原本那句,不猜。
import type { ScoreListMeta } from "@/lib/types";

export function scoreListEmptyText(meta: ScoreListMeta | undefined | null): string | null {
  if (!meta) return null;
  if (meta.withheld && meta.scored === 0) {
    return "今日評分尚未產生,綜合榜暫不排名。";
  }
  if (meta.withheld) {
    return (
      `分點／法人資料尚未到齊,綜合榜暫不排名(今日評分 ${meta.scored} 檔中,` +
      `缺分點 ${meta.missing_branch} 檔、缺法人 ${meta.missing_inst} 檔)。` +
      "資料不齊時缺的分項會把權重讓給其他分項,分數偏高、不可比,所以寧可不排。"
    );
  }
  const best = meta.max_final === null ? "" : `,今日最高 ${meta.max_final} 分`;
  return (
    `資料已到齊,今日沒有任何一檔達 ${meta.min_final} 分${best}。` +
    "寧缺勿濫——沒有符合條件時不硬湊。"
  );
}
