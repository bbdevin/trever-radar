import StockPageSkeleton from "@/components/StockPageSkeleton";

/**
 * 站內 client 導覽進個股頁時,路由一 commit 就先畫骨架(含轉圈圈),
 * 不必等個股頁 JS 與 RSC 到齊;舊頁面不會停在畫面上沒有回饋。
 */
export default function StockLoading() {
  return <StockPageSkeleton />;
}
