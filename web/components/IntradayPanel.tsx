"use client";

import { useEffect, useState } from "react";
import { Activity, AlertTriangle, Clock, Radio, ShieldCheck, Star, Zap } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { useSession } from "@/lib/useSession";
import { cn } from "@/lib/utils";
import {
  DEFAULT_MONITOR_CAP,
  humanizeSignalDesc,
  parsePoolSource,
  poolSourceLabel,
  SIGNAL_PILL,
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
  const [monitorUsed, setMonitorUsed] = useState<number | null>(null);
  const [monitorCap, setMonitorCap] = useState<number>(DEFAULT_MONITOR_CAP);
  const [loaded, setLoaded] = useState(false);

  const applyHeartbeat = (row: {
    last_active_at?: string;
    status?: string;
    monitor_used?: number | null;
    monitor_cap?: number | null;
  }) => {
    if (row.last_active_at) {
      setLastHeartbeat(row.last_active_at);
      if (row.status === "offline") setWorkerOnline(false);
      else setWorkerOnline(Date.now() - new Date(row.last_active_at).getTime() < 120_000);
    }
    if (typeof row.monitor_used === "number") setMonitorUsed(row.monitor_used);
    if (typeof row.monitor_cap === "number" && row.monitor_cap > 0) setMonitorCap(row.monitor_cap);
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
        if (data) applyHeartbeat(data as Parameters<typeof applyHeartbeat>[0]);
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
          const row = payload.new as Parameters<typeof applyHeartbeat>[0] | null;
          if (row) applyHeartbeat(row);
        },
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [enabled]);

  useEffect(() => {
    const timer = setInterval(() => {
      if (lastHeartbeat) {
        setWorkerOnline(Date.now() - new Date(lastHeartbeat).getTime() < 120_000);
      }
    }, 30_000);
    return () => clearInterval(timer);
  }, [lastHeartbeat]);

  return { signals, workerOnline, monitorUsed, monitorCap, loaded };
}

function useInHours() {
  const [inHours, setInHours] = useState(false);
  useEffect(() => {
    const checkTime = () => {
      const tw = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Taipei" }));
      const mins = tw.getHours() * 60 + tw.getMinutes();
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
      <span className="inline-flex items-center gap-1.5 rounded-md bg-muted/60 px-2 py-1 text-[11px] font-medium text-muted-foreground">
        <Clock className="h-3.5 w-3.5" aria-hidden />
        非交易時段
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-medium",
        workerOnline ? "bg-up/12 text-up" : "bg-muted/60 text-muted-foreground",
      )}
    >
      <Radio className={cn("h-3.5 w-3.5", workerOnline && "animate-pulse")} aria-hidden />
      {workerOnline ? "即時連線" : "引擎離線"}
    </span>
  );
}

function CapChip({ used, cap }: { used: number | null; cap: number }) {
  const u = used ?? 0;
  const full = used != null && u >= cap;
  const label = used == null ? `—/${cap}` : `${u}/${cap}`;
  return (
    <span
      className={cn(
        "num inline-flex items-center rounded-md px-2 py-1 text-[11px] font-bold tabular-nums",
        full ? "bg-warn/12 text-warn" : "bg-primary/12 text-primary",
      )}
      title="目前監控檔數 / Fugle 免費 WebSocket 上限"
    >
      監控 {label}
    </span>
  );
}

function PoolBadge({ desc }: { desc: string }) {
  const pool = parsePoolSource(desc);
  const label = poolSourceLabel(pool);
  if (!label) return null;
  const Icon = pool === "watchlist" ? Star : ShieldCheck;
  return (
    <span className="inline-flex items-center gap-0.5 rounded-md bg-muted/70 px-1.5 py-0.5 text-[10px] font-semibold text-foreground ring-1 ring-border">
      <Icon className="h-3 w-3" aria-hidden />
      {label}
    </span>
  );
}

function SignalRow({ s }: { s: IntradaySignal }) {
  const meta = signalMeta(s.signal_type);
  const isBreakout = meta.breakout;
  const rawDesc = (s.signal_desc || "").replace(/\s*[·•]\s*來源[:：][^\s·•]+/g, "").trim();
  const cleanDesc = humanizeSignalDesc(rawDesc);

  return (
    <a
      href={`/stock?id=${encodeURIComponent(s.stock_id)}`}
      className={cn(
        "flex min-h-11 cursor-pointer items-start justify-between gap-3 rounded-md px-3 py-2.5 text-sm transition-colors duration-200 hover:bg-secondary",
        isBreakout
          ? "bg-up/10 shadow-[inset_0_0_0_1px_color-mix(in_oklab,var(--up)_25%,transparent)]"
          : "bg-background",
      )}
    >
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="num font-mono text-[11px] text-muted-foreground">
            {new Date(s.created_at).toLocaleTimeString("zh-TW", {
              timeZone: "Asia/Taipei",
              hour12: false,
            })}
          </span>
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-bold",
              SIGNAL_PILL[meta.family],
            )}
            title={`${meta.code}：${meta.rule}`}
          >
            {isBreakout ? <Zap className="h-3 w-3 fill-current" /> : <AlertTriangle className="h-3 w-3" />}
            {meta.label}
            <span className="font-mono opacity-70">{meta.code}</span>
          </span>
          <PoolBadge desc={s.signal_desc} />
        </div>
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-bold text-foreground">{s.stock_name}</span>
          <span className="num text-xs text-muted-foreground">{s.stock_id}</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <span className={cn("rounded-md px-1.5 py-0.5 text-[11px] font-semibold", SIGNAL_PILL[meta.family])}>
            {meta.meaning}
          </span>
          {cleanDesc && (
            <span className="rounded-md bg-muted/70 px-1.5 py-0.5 text-[11px] font-medium text-foreground ring-1 ring-border">
              {cleanDesc}
            </span>
          )}
        </div>
      </div>
      <div className="shrink-0 text-right">
        <div className="num min-w-[52px] font-medium text-up">{Number(s.price).toFixed(2)}</div>
      </div>
    </a>
  );
}

const LEGEND = ["I-1", "I-2", "I-3", "I-4"] as const;

/** 盤中監控頁專用（首頁已不再嵌入） */
export default function IntradayPanel() {
  const { session } = useSession();
  const inHours = useInHours();
  const { signals, workerOnline, monitorUsed, monitorCap, loaded } = useIntradayFeed(!!session);

  return (
    <div className="overflow-hidden rounded-[var(--r-lg)] border bg-card/50 shadow-sm backdrop-blur">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/40 px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <Activity className="h-4 w-4 shrink-0 text-primary" aria-hidden />
          <h2 className="text-sm font-bold text-foreground">監控訊號</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <CapChip used={monitorUsed} cap={monitorCap} />
          <StatusChip inHours={inHours} workerOnline={workerOnline} />
        </div>
      </div>

      <div className="border-b border-border px-4 py-3">
        <p className="mb-3 text-[12.5px] leading-relaxed text-muted-foreground">
          監控「今日未發動」與「自選」聯集（排除 ETF）。Fugle 免費方案最多同時訂閱 {monitorCap}{" "}
          檔。符合門檻才推播；同檔同類型當日只推一次。訊號為觀察提醒，非下單建議。
        </p>
        <ul className="grid grid-cols-2 gap-2">
          {LEGEND.map((code) => {
            const m = signalMeta(code);
            return (
              <li
                key={code}
                className="rounded-md bg-muted/30 px-2.5 py-2 text-[12px] leading-snug ring-1 ring-border"
              >
                <div className="mb-1 flex flex-wrap items-center gap-1.5">
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-bold",
                      SIGNAL_PILL[m.family],
                    )}
                  >
                    {m.label}
                    <span className="font-mono opacity-70">{m.code}</span>
                  </span>
                  <span
                    className={cn(
                      "rounded-md px-1.5 py-0.5 text-[11px] font-semibold",
                      SIGNAL_PILL[m.family],
                    )}
                  >
                    {m.meaning}
                  </span>
                </div>
                <p className="text-[11px] text-muted-foreground">{m.rule}</p>
              </li>
            );
          })}
        </ul>
      </div>

      <div
        className="max-h-[min(70vh,640px)] overflow-y-auto p-2"
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
