"use client";

import { useEffect, useState } from "react";
import { Activity, Radio, AlertTriangle, Zap, Clock } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { useSession } from "@/lib/useSession";
import { cn } from "@/lib/utils";

interface IntradaySignal {
  id: number;
  stock_id: string;
  stock_name: string;
  signal_type: string;
  signal_desc: string;
  price: number;
  volume: number;
  created_at: string;
}

export default function IntradayPanel() {
  const { session } = useSession();
  const [signals, setSignals] = useState<IntradaySignal[]>([]);
  const [workerOnline, setWorkerOnline] = useState(false);
  const [lastHeartbeat, setLastHeartbeat] = useState<string | null>(null);
  
  useEffect(() => {
    if (!session) return;
    
    // Fetch initial signals
    supabase.from("intraday_signals").select("*").order("created_at", { ascending: false }).limit(20)
      .then(({ data }) => {
        if (data) setSignals(data);
      });
      
    // Fetch initial heartbeat
    supabase.from("worker_heartbeat").select("*").eq("id", 1).single()
      .then(({ data }) => {
        if (data) {
          checkHeartbeat(data.last_active_at, data.status);
        }
      });
      
    // Subscribe to signals
    const channel = supabase.channel("intraday_channel")
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "intraday_signals" }, (payload) => {
        setSignals(prev => [payload.new as IntradaySignal, ...prev].slice(0, 50));
      })
      .on("postgres_changes", { event: "*", schema: "public", table: "worker_heartbeat" }, (payload) => {
        const row = payload.new as any;
        if (row) checkHeartbeat(row.last_active_at, row.status);
      })
      .subscribe();
      
    return () => {
      supabase.removeChannel(channel);
    };
  }, [session]);
  
  const checkHeartbeat = (last_active: string, status: string) => {
    setLastHeartbeat(last_active);
    if (status === "offline") {
      setWorkerOnline(false);
      return;
    }
    const diff = new Date().getTime() - new Date(last_active).getTime();
    // If heartbeat is older than 2 minutes, consider it offline
    setWorkerOnline(diff < 120000);
  };
  
  // Timer to re-check heartbeat age
  useEffect(() => {
    const timer = setInterval(() => {
      if (lastHeartbeat) checkHeartbeat(lastHeartbeat, "online"); // We assume it was online, just checking time diff
    }, 30000);
    return () => clearInterval(timer);
  }, [lastHeartbeat]);

  // Check if we are in intraday hours (08:50 - 13:40 Taiwan time)
  const [inHours, setInHours] = useState(false);
  useEffect(() => {
    const checkTime = () => {
      const now = new Date();
      const twTime = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Taipei" }));
      const h = twTime.getHours();
      const m = twTime.getMinutes();
      const mins = h * 60 + m;
      setInHours(mins >= 530 && mins <= 820);
    };
    checkTime();
    const timer = setInterval(checkTime, 60000);
    return () => clearInterval(timer);
  }, []);

  // 面板永遠渲染:登入即可見(不限盤中時段),未登入亦顯示外殼與登入提示。
  return (
    <div className="mb-6 overflow-hidden rounded-[var(--r-lg)] border bg-card/50 shadow-sm backdrop-blur">
      <div className="flex items-center justify-between border-b bg-muted/40 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-bold text-foreground">盤中訊號雷達 (Armed 監控)</h2>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {!inHours ? (
            // 非交易時段顯示中性狀態,不用紅色 offline 嚇人
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <Clock className="h-3.5 w-3.5" />
              非交易時段
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <Radio className={cn("h-3.5 w-3.5", workerOnline ? "text-up animate-pulse" : "text-muted-foreground")} />
              {workerOnline ? "引擎連線中" : "引擎離線"}
            </span>
          )}
        </div>
      </div>

      <div className="max-h-[300px] overflow-y-auto p-2">
        {!session ? (
          <div className="px-4 py-3 text-center text-sm text-muted-foreground">
            登入後才能看到盤中即時訊號推播
          </div>
        ) : signals.length === 0 ? (
          // 無訊號空狀態:精簡單行,依時段/連線區分文案(不留 300px 空白)
          <div className="flex items-center justify-center gap-2 px-4 py-3 text-center text-sm text-muted-foreground">
            <Clock className="h-4 w-4 shrink-0 opacity-40" />
            {!inHours
              ? "非交易時段,worker 於平日 08:50 啟動"
              : workerOnline
                ? "尚無訊號,持續監控中…"
                : "worker 離線,盤中訊號暫停"}
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {signals.map((s) => {
              const isTriggered = s.signal_type === "I-4";
              return (
                <div key={s.id} className={cn("flex items-center justify-between rounded-md px-3 py-2 text-sm transition-colors duration-300", 
                  isTriggered ? "bg-up/10 shadow-sm" : "bg-background hover:bg-muted/50")}>
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {new Date(s.created_at).toLocaleTimeString("zh-TW", { timeZone: "Asia/Taipei", hour12: false })}
                    </span>
                    <span className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold",
                      isTriggered ? "bg-up/15 text-up" : "bg-primary/10 text-primary")}>
                      {isTriggered ? <Zap className="h-3 w-3 fill-current" /> : <AlertTriangle className="h-3 w-3" />}
                      {s.signal_type}
                    </span>
                    <span className="font-bold">{s.stock_name}</span>
                    <span className="hidden text-xs text-muted-foreground sm:inline">{s.stock_id}</span>
                  </div>
                  <div className="flex items-center gap-3 text-right">
                    <span className="text-xs text-muted-foreground">{s.signal_desc}</span>
                    <span className="min-w-[48px] font-mono font-medium text-up">{s.price.toFixed(2)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
