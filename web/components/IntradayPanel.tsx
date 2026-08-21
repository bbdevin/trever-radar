"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Activity, AlertTriangle, Clock, Radio, ShieldCheck, Star, Zap } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { useSession } from "@/lib/useSession";
import { cn } from "@/lib/utils";
import {
  parsePoolSource,
  poolSourceLabel,
  signalMeta,
} from "@/lib/intradaySignals";

export interface IntradaySignal {
  id: number;
  stock_id: string;
  stock_name: string;
  signal_type: string;
  signal_desc: string;
  price: number;
  volume: number;
  created_at: string;
}

function useIntradayFeed(enabled: boolean) {
  const [signals, setSignals] = useState<IntradaySignal[]>([]);
  const [workerOnline, setWorkerOnline] = useState(false);
  const [lastHeartbeat, setLastHeartbeat] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const checkHeartbeat = (last_active: string, status: string) => {
    setLastHeartbeat(last_active);
    if (status === "offline") {
      setWorkerOnline(false);
      return;
    }
    const diff = Date.now() - new Date(last_active).getTime();
    setWorkerOnline(diff < 120_000);
  };

  useEffect(() => {
    if (!enabled) return;

    supabase
      .from("intraday_signals")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(40)
      .then(({ data }) => {
        if (data) setSignals(data as IntradaySignal[]);
        setLoaded(true);
      });

    supabase
      .from("worker_heartbeat")
      .select("*")
      .eq("id", 1)
      .single()
      .then(({ data }) => {
        if (data) checkHeartbeat(data.last_active_at, data.status);
      });

    const channel = supabase
      .channel("intraday_channel")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "intraday_signals" },
        (payload) => {
          setSignals((prev) => [payload.new as IntradaySignal, ...prev].slice(0, 60));
        },
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "worker_heartbeat" },
        (payload) => {
          const row = payload.new as { last_active_at?: string; status?: string } | null;
          if (row?.last_active_at) checkHeartbeat(row.last_active_at, row.status ?? "online");
        },
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [enabled]);

  useEffect(() => {
    const timer = setInterval(() => {
      if (lastHeartbeat) checkHeartbeat(lastHeartbeat, "online");
    }, 30_000);
    return () => clearInterval(timer);
  }, [lastHeartbeat]);

  return { signals, workerOnline, lastHeartbeat, loaded };
}

function useInHours() {
  const [inHours, setInHours] = useState(false);
  useEffect(() => {
    const checkTime = () => {
      const tw = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Taipei" }));
      const mins = tw.getHours() * 60 + tw.getMinutes();
      // 08:50–13:40
      setInHours(mins >= 530 && mins <= 820);
    };
    checkTime();
    const timer = setInterval(checkTime, 60_000);
    return () => clearInterval(timer);
  }, []);
  return inHours;
}

function StatusChip({ inHours, workerOnline }: { inHours: boolean; workerOnline: boolean }) {
  if (!inHours) {
    return (
      <span className="flex items-center gap-1.5 text-muted-foreground">
        <Clock className="h-3.5 w-3.5" />
        非交易時段
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5 text-muted-foreground">
      <Radio className={cn("h-3.5 w-3.5", workerOnline ? "animate-pulse text-up" : "")} />
      {workerOnline ? "即時連線中" : "引擎離線"}
    </span>
  );
}

function PoolBadge({ desc }: { desc: string }) {
  const pool = parsePoolSource(desc);
  const label = poolSourceLabel(pool);
  if (!label) return null;
  const Icon = pool === "watchlist" ? Star : ShieldCheck;
  return (
    <span
      className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground ring-1 ring-border"
      title="此檔列入監控的來源"
    >
      <Icon className="h-3 w-3" aria-hidden />
      {label}
    </span>
  );
}

function SignalRow({ s }: { s: IntradaySignal }) {
  const meta = signalMeta(s.signal_type);
  const isBreakout = meta.breakout;
  // 去掉 worker 附加的「 · 來源:…」方便閱讀（來源改用徽章）
  const cleanDesc = (s.signal_desc || "").replace(/\s*[·•]\s*來源[:：][^\s·•]+/g, "").trim();

  return (
    <a
      href={`/stock?id=${encodeURIComponent(s.stock_id)}`}
      className={cn(
        "flex min-h-11 cursor-pointer items-start justify-between gap-3 rounded-md px-3 py-2.5 text-sm transition-colors duration-200 hover:bg-secondary",
        isBreakout ? "bg-up/10 shadow-[inset_0_0_0_1px_color-mix(in_oklab,var(--up)_25%,transparent)]" : "bg-background",
      )}
    >
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="num font-mono text-[11px] text-muted-foreground">
            {new Date(s.created_at).toLocaleTimeString("zh-TW", {
              timeZone: "Asia/Taipei",
              hour12: false,
            })}
          </span>
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold",
              isBreakout ? "bg-up/15 text-up" : "bg-primary/10 text-primary",
            )}
            title={`${meta.code}：${meta.rule}`}
          >
            {isBreakout ? <Zap className="h-3 w-3 fill-current" /> : <AlertTriangle className="h-3 w-3" />}
            {meta.label}
            <span className="font-mono font-medium opacity-70">{meta.code}</span>
          </span>
          <PoolBadge desc={s.signal_desc} />
        </div>
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="font-bold text-foreground">{s.stock_name}</span>
          <span className="num text-xs text-muted-foreground">{s.stock_id}</span>
        </div>
        <p className="text-[12.5px] leading-snug text-foreground/90">
          <span className="text-muted-foreground">{meta.meaning} · </span>
          {cleanDesc || meta.rule}
        </p>
      </div>
      <div className="shrink-0 text-right">
        <div className="num min-w-[52px] font-medium text-up">{Number(s.price).toFixed(2)}</div>
      </div>
    </a>
  );
}

const LEGEND = ["I-1", "I-2", "I-3", "I-4"] as const;

/** 首頁精簡條 / 盤中頁完整版共用 */
export default function IntradayPanel({
  variant = "compact",
}: {
  variant?: "compact" | "full";
}) {
  const { session } = useSession();
  const inHours = useInHours();
  const { signals, workerOnline, loaded } = useIntradayFeed(!!session);
  const isFull = variant === "full";

  return (
    <div
      className={cn(
        "overflow-hidden rounded-[var(--r-lg)] border bg-card/50 shadow-sm backdrop-blur",
        isFull ? "mb-0" : "mb-6",
      )}
    >
      <div className="flex items-center justify-between gap-3 border-b bg-muted/40 px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <Activity className="h-4 w-4 shrink-0 text-primary" aria-hidden />
          <div className="min-w-0">
            <h2 className="text-sm font-bold text-foreground">
              {isFull ? "盤中訊號" : "盤中雷達"}
            </h2>
            {!isFull && (
              <p className="truncate text-[11px] text-muted-foreground">
                監控未發動 + 自選 · 有異動才推播
              </p>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-3 text-xs">
          <StatusChip inHours={inHours} workerOnline={workerOnline} />
          {!isFull && (
            <Link
              href="/intraday"
              className="cursor-pointer font-semibold text-primary transition-colors hover:underline"
            >
              完整頁
            </Link>
          )}
        </div>
      </div>

      {isFull && (
        <div className="border-b border-border px-4 py-3">
          <p className="mb-2 text-[12.5px] leading-relaxed text-muted-foreground">
            Worker 盤中訂閱「今日未發動」與「自選」聯集（上限約 40 檔）。符合門檻才寫入即時訊號；同檔同類型當日只推一次。訊號為觀察提醒，非下單建議。
          </p>
          <ul className="grid gap-2 sm:grid-cols-2">
            {LEGEND.map((code) => {
              const m = signalMeta(code);
              return (
                <li
                  key={code}
                  className="rounded-md bg-muted/40 px-3 py-2 text-[12px] leading-snug ring-1 ring-border"
                >
                  <div className="mb-0.5 flex items-center gap-1.5 font-semibold text-foreground">
                    <span className="font-mono text-[10px] text-muted-foreground">{m.code}</span>
                    {m.label}
                    <span className="font-normal text-muted-foreground">— {m.meaning}</span>
                  </div>
                  <div className="text-muted-foreground">{m.rule}</div>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div
        className={cn("overflow-y-auto p-2", isFull ? "max-h-[min(70vh,640px)]" : "max-h-[300px]")}
        aria-live="polite"
        aria-relevant="additions"
      >
        {!session ? (
          <div className="px-4 py-3 text-center text-sm text-muted-foreground">
            登入後才能看到盤中即時訊號推播
          </div>
        ) : !loaded ? (
          <div className="space-y-2 px-1 py-1" aria-busy="true">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-14 animate-pulse rounded-md bg-muted/60" />
            ))}
          </div>
        ) : signals.length === 0 ? (
          <div className="flex items-center justify-center gap-2 px-4 py-3 text-center text-sm text-muted-foreground">
            <Clock className="h-4 w-4 shrink-0 opacity-40" />
            {!inHours
              ? "非交易時段，worker 於平日 08:50 啟動"
              : workerOnline
                ? "尚無訊號——監控中，有大單／爆量／急拉／發動才會出現"
                : "worker 離線，盤中訊號暫停"}
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {signals.map((s) => (
              <SignalRow key={s.id} s={s} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
