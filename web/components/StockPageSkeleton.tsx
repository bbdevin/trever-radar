import { Skeleton } from "@/components/ui/skeleton";

/**
 * 個股頁載入骨架:換頁中(app/stock/loading.tsx)與個股資料下載中(StockView)共用同一個,
 * 兩段之間畫面不跳。K 線區中央的轉圈圈讓手機上一眼看得出「正在載入」。
 */
export default function StockPageSkeleton() {
  return (
    <div role="status" aria-label="載入中">
      <Skeleton className="my-4 h-[68px] rounded-[var(--r-md)]" />
      <div className="relative">
        <Skeleton className="h-[52vh] rounded-[var(--r-lg)]" />
        <span className="absolute inset-0 grid place-items-center">
          <span className="nav-spinner !size-8 !border-[3px]" aria-hidden />
        </span>
      </div>
    </div>
  );
}
