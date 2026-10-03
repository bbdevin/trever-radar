"use client";

import { Suspense, useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { clearNavPending, isPageChangingClick, markNavPending } from "@/lib/navFeedback";

/** 新路由 commit(路徑或 query 變了)就收掉回饋;useSearchParams 在靜態輸出需包 Suspense。 */
function ClearOnRouteChange() {
  const pathname = usePathname();
  const search = useSearchParams().toString();
  useEffect(() => {
    clearNavPending();
  }, [pathname, search]);
  return null;
}

/**
 * 全站站內連結點擊 → 立刻顯示轉圈圈與頂部進度條(見 lib/navFeedback.ts)。
 * document 的捕獲階段監聽:表格列裡的 Link 會 stopPropagation(避免觸發列的 onClick),冒泡階段收不到;
 * 卡片內的 ★ 這類巢狀按鈕另外排除。router.push 的呼叫點(搜尋、表格列)自己呼叫 markNavPending。
 */
export default function NavFeedback() {
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const target = e.target as Element | null;
      const a = target?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!a || !isPageChangingClick(e, a)) return;
      const inner = target?.closest?.('button, [role="button"]');
      if (inner && a.contains(inner)) return;
      markNavPending(a);
    };
    // 從 bfcache 回來(整頁導覽後按返回)時不要留著轉圈圈。
    const onPageShow = () => clearNavPending();
    document.addEventListener("click", onClick, true);
    window.addEventListener("pageshow", onPageShow);
    return () => {
      document.removeEventListener("click", onClick, true);
      window.removeEventListener("pageshow", onPageShow);
    };
  }, []);

  return (
    <>
      <Suspense fallback={null}>
        <ClearOnRouteChange />
      </Suspense>
      <div aria-hidden className="nav-progress" />
      <div role="status" className="nav-chip">
        <span className="nav-spinner" aria-hidden />
        載入中
      </div>
    </>
  );
}
