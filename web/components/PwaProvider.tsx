"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, Share, WifiOff, X } from "lucide-react";
import { toast } from "sonner";
import { isIosSafari, isStandaloneDisplay } from "@/lib/pwa";
import { cn } from "@/lib/utils";

const LS_INSTALL_DISMISS = "trever.pwa.installDismissed";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

export default function PwaProvider({ children }: { children: React.ReactNode }) {
  const [online, setOnline] = useState(true);
  const [installEvent, setInstallEvent] = useState<BeforeInstallPromptEvent | null>(null);
  const [showIosHint, setShowIosHint] = useState(false);
  const [standalone, setStandalone] = useState(false);

  const dismissed = useCallback(() => {
    try {
      return localStorage.getItem(LS_INSTALL_DISMISS) === "1";
    } catch {
      return false;
    }
  }, []);

  const dismissInstall = () => {
    try {
      localStorage.setItem(LS_INSTALL_DISMISS, "1");
    } catch {
      /* ignore */
    }
    setInstallEvent(null);
    setShowIosHint(false);
  };

  useEffect(() => {
    const applyStandalone = () => {
      const on = isStandaloneDisplay();
      setStandalone(on);
      document.documentElement.classList.toggle("standalone", on);
    };
    applyStandalone();
    const mq = window.matchMedia("(display-mode: standalone)");
    mq.addEventListener("change", applyStandalone);

    setOnline(navigator.onLine);
    const on = () => {
      setOnline(true);
      toast.info("已連線", {
        description: "重新整理以載入最新市場訊號（不會使用離線快取的行情）。",
        action: { label: "重新整理", onClick: () => window.location.reload() },
      });
    };
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);

    const onInstall = (e: Event) => {
      e.preventDefault();
      if (isStandaloneDisplay() || dismissed()) return;
      setInstallEvent(e as BeforeInstallPromptEvent);
    };
    window.addEventListener("beforeinstallprompt", onInstall);

    if (!isStandaloneDisplay() && isIosSafari() && !dismissed()) {
      setShowIosHint(true);
    }

    return () => {
      mq.removeEventListener("change", applyStandalone);
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
      window.removeEventListener("beforeinstallprompt", onInstall);
    };
  }, [dismissed]);

  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    let refreshing = false;
    const onController = () => {
      if (refreshing) return;
      refreshing = true;
      window.location.reload();
    };
    navigator.serviceWorker.addEventListener("controllerchange", onController);

    let cancelled = false;
    let onVis: (() => void) | undefined;
    navigator.serviceWorker
      .register("/sw.js", { updateViaCache: "none" })
      .then((reg) => {
        if (cancelled) return;
        const listen = (worker: ServiceWorker | null) => {
          if (!worker) return;
          worker.addEventListener("statechange", () => {
            if (worker.state === "installed" && navigator.serviceWorker.controller) {
              toast("有新版本可用", {
                id: "pwa-update",
                description: "更新的是介面與 App shell，不是市場訊號。",
                duration: Infinity,
                action: {
                  label: "重新載入",
                  onClick: () => worker.postMessage("SKIP_WAITING"),
                },
              });
            }
          });
        };
        listen(reg.installing);
        reg.addEventListener("updatefound", () => listen(reg.installing));
        onVis = () => {
          if (document.visibilityState === "visible") void reg.update();
        };
        document.addEventListener("visibilitychange", onVis);
      })
      .catch(() => {
        /* SW 失敗不擋站 */
      });

    return () => {
      cancelled = true;
      navigator.serviceWorker.removeEventListener("controllerchange", onController);
      if (onVis) document.removeEventListener("visibilitychange", onVis);
    };
  }, []);

  const installApp = async () => {
    if (!installEvent) return;
    await installEvent.prompt();
    try {
      await installEvent.userChoice;
    } catch {
      /* ignore */
    }
    dismissInstall();
  };

  const showInstall = !standalone && (installEvent !== null || showIosHint);

  return (
    <>
      {children}
      {!online && (
        <div
          role="status"
          className="fixed inset-x-0 z-50 flex items-start gap-2 border-b border-border bg-card px-3 py-2 text-[13px] text-foreground"
          style={{ top: "env(safe-area-inset-top)" }}
        >
          <WifiOff className="mt-0.5 size-4 shrink-0 text-[color:var(--warn)]" aria-hidden />
          <p>
            目前離線。市場訊號未更新，請連上網路後再查看。
            <span className="mt-0.5 block text-[12px] text-muted-foreground">不會顯示過期行情充當最新資料。</span>
          </p>
        </div>
      )}
      {showInstall && (
        <div
          className={cn(
            "fixed inset-x-0 z-50 mx-auto w-[min(calc(100%-1.5rem-env(safe-area-inset-left)-env(safe-area-inset-right)),420px)] rounded-[var(--r-md)] border border-border bg-card p-3 shadow-[var(--shadow-lift)]",
            "max-md:bottom-[calc(4.25rem+env(safe-area-inset-bottom))] md:bottom-5",
          )}
          role="dialog"
          aria-label="安裝 Trever Radar"
        >
          <div className="flex items-start gap-2.5">
            <img src="/icons/trever-radar-mark.svg" alt="" className="size-10 shrink-0 rounded-[10px]" />
            <div className="min-w-0 flex-1">
              <p className="text-[14px] font-semibold text-foreground">加到主畫面</p>
              {installEvent ? (
                <p className="mt-0.5 text-[12.5px] text-muted-foreground">安裝後可全螢幕開啟，行情仍走即時網路。</p>
              ) : (
                <p className="mt-0.5 text-[12.5px] text-muted-foreground">
                  在 Safari 點
                  <Share className="mx-0.5 inline size-3.5 align-text-bottom" aria-hidden />
                  分享，再選「加入主畫面」。
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={dismissInstall}
              className="-mr-1 -mt-1 grid size-11 shrink-0 place-items-center rounded-[10px] text-muted-foreground hover:text-foreground"
              aria-label="關閉"
            >
              <X className="size-4" />
            </button>
          </div>
          {installEvent && (
            <button
              type="button"
              onClick={() => void installApp()}
              className="mt-2 flex min-h-11 w-full cursor-pointer items-center justify-center gap-1.5 rounded-[10px] bg-primary text-[14px] font-semibold text-primary-foreground"
            >
              <Download className="size-4" aria-hidden />
              安裝 PWA
            </button>
          )}
        </div>
      )}
    </>
  );
}
