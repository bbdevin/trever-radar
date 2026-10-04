/**
 * 口袋標籤人話全文的顯示期轉場(原本在 components/PocketBadges.tsx;多方榜建置器在 Node 上
 * 也要用同一個轉換,所以搬到不 import 任何東西的 lib 檔)。
 *
 * 舊 payload 的人話全文仍寫著改名前的「關鍵分點同買：」。
 *
 * META 的雙讀只修好 compact 模式的徽章字樣;個股頁是 compact=false、渲染的是
 * 伺服器產生的 t.text,tooltip 也是,所以在下一次 VPS export 之前(程式碼走
 * Pages 幾分鐘就上,JSON 要等當天的匯出輪)會出現徽章寫「追蹤分點」、展開卻寫
 * 「關鍵分點同買」的矛盾。這次改名的整個重點就是那三個字不該再指這個東西,
 * 讓它在畫面上多留幾小時等於沒改。
 *
 * 只改顯示,不碰資料:僅對 legacy code 生效,且只換開頭那一段前綴,分點名稱
 * 原樣保留。新 payload 走 T1 分支,這段完全不執行——和 PocketBadges META 裡的 K1 條目同時
 * 可以刪掉。
 */
import type { PocketTag } from "./types.ts";

const LEGACY_TEXT_PREFIX = "關鍵分點同買";
const CURRENT_TEXT_PREFIX = "追蹤分點同買";

export function pocketDisplayText(t: Pick<PocketTag, "code" | "text">): string {
  if (t.code === "K1_KEY_BUY" && t.text.startsWith(LEGACY_TEXT_PREFIX)) {
    return CURRENT_TEXT_PREFIX + t.text.slice(LEGACY_TEXT_PREFIX.length);
  }
  return t.text;
}
