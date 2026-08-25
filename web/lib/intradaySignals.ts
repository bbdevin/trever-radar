/** 盤中訊號 I-1～I-4 人話對照（docs/24 §2.2；色非唯一訊號，必帶文字標籤） */

export type IntradaySignalType = "I-1" | "I-2" | "I-3" | "I-4" | string;

export type SignalMeta = {
  code: string;
  label: string;
  meaning: string;
  rule: string;
  breakout: boolean;
  /** 標籤色家族（對齊 docs/19 ReasonPill token，零新色票） */
  family: "chips" | "tech" | "warrant" | "breakout";
};

export const SIGNAL_META: Record<string, SignalMeta> = {
  "I-1": {
    code: "I-1",
    label: "大單",
    meaning: "出現單筆大額成交",
    rule: "單筆成交金額 ≥ 500 萬",
    breakout: false,
    family: "chips",
  },
  "I-2": {
    code: "I-2",
    label: "爆量",
    meaning: "量能明顯高於今日時間進度",
    rule: "累積量 ≥ 依開盤至今折算日均量的 2 倍（開盤滿 5 分才判）",
    breakout: false,
    family: "warrant",
  },
  "I-3": {
    code: "I-3",
    label: "急拉",
    meaning: "短時間價格急升",
    rule: "近 5 分鐘相對窗內最低價漲幅 ≥ 2%",
    breakout: false,
    family: "tech",
  },
  "I-4": {
    code: "I-4",
    label: "發動",
    meaning: "股價突破觀察價",
    rule: "現價 ≥ 盤後觀察價（watch price）",
    breakout: true,
    family: "breakout",
  },
};

export const SIGNAL_PILL: Record<SignalMeta["family"], string> = {
  chips: "bg-[color:var(--accent-2)]/12 text-[color:var(--accent-2)]",
  tech: "bg-primary/12 text-primary",
  warrant: "bg-warn/12 text-warn",
  breakout: "bg-up/15 text-up",
};

/** Fugle 基本用戶免費 WS 上限（與 worker FUGLE_WS_MAX_SUBSCRIBE 預設一致） */
export const DEFAULT_MONITOR_CAP = 5;

/** 台股 ETF 代號：00 開頭（0050／00878／00679B…）。對齊 pipeline classify / worker。 */
export function isEtfStockId(sid: string): boolean {
  return String(sid).trim().toUpperCase().startsWith("00");
}

/** 監控訊號：新 → 舊（created_at desc） */
export function sortSignalsNewestFirst<T extends { created_at: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => {
    const tb = Date.parse(b.created_at) || 0;
    const ta = Date.parse(a.created_at) || 0;
    if (tb !== ta) return tb - ta;
    return (Number((b as { id?: number }).id) || 0) - (Number((a as { id?: number }).id) || 0);
  });
}

/** 台北時間：今日顯示 HH:mm:ss，跨日顯示 MM/DD HH:mm */
export function formatSignalTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const ymd = `${get("year")}-${get("month")}-${get("day")}`;
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const hm = `${get("hour")}:${get("minute")}:${get("second")}`;
  if (ymd === today) return hm;
  return `${get("month")}/${get("day")} ${get("hour")}:${get("minute")}`;
}

export function signalMeta(type: IntradaySignalType): SignalMeta {
  return (
    SIGNAL_META[type] ?? {
      code: String(type),
      label: String(type),
      meaning: "盤中監控訊號",
      rule: "見系統規則",
      breakout: false,
      family: "tech",
    }
  );
}

/** 把數字改成 億／千萬／百萬／萬（適讀） */
export function humanizeTwdAmount(raw: string | number): string {
  let n: number | null = null;
  if (typeof raw === "number" && Number.isFinite(raw)) {
    n = raw;
  } else {
    const s = String(raw).replace(/,/g, "").trim();
    const yi = /^([\d.]+)\s*億$/.exec(s);
    const qw = /^([\d.]+)\s*千萬$/.exec(s);
    const bw = /^([\d.]+)\s*百萬$/.exec(s);
    const wan = /^([\d.]+)\s*萬$/.exec(s);
    if (yi) n = parseFloat(yi[1]) * 1e8;
    else if (qw) n = parseFloat(qw[1]) * 1e7;
    else if (bw) n = parseFloat(bw[1]) * 1e6;
    else if (wan) n = parseFloat(wan[1]) * 1e4;
    else if (/^\d+(\.\d+)?$/.test(s)) n = parseFloat(s);
  }
  if (n == null || !Number.isFinite(n) || n <= 0) return String(raw);

  const fmt = (v: number, unit: string) => {
    const t = v >= 10 ? v.toFixed(0) : v.toFixed(1);
    return `${t.replace(/\.0$/, "")}${unit}`;
  };
  if (n >= 1e8) return fmt(n / 1e8, "億");
  if (n >= 1e7) return fmt(n / 1e7, "千萬");
  if (n >= 1e6) return fmt(n / 1e6, "百萬");
  if (n >= 1e4) return fmt(n / 1e4, "萬");
  return `${Math.round(n)}元`;
}

/** 訊號描述裡的「單筆大單 1000萬」→「單筆大單 1千萬」 */
export function humanizeSignalDesc(desc: string): string {
  return desc.replace(/單筆大單\s*([\d,.]+)\s*萬/g, (_, wan) => {
    const n = parseFloat(String(wan).replace(/,/g, "")) * 1e4;
    return `單筆大單 ${humanizeTwdAmount(n)}`;
  });
}

export function parsePoolSource(desc: string | null | undefined): "armed" | "watchlist" | "both" | null {
  if (!desc) return null;
  if (desc.includes("來源:雙池") || desc.includes("來源：雙池")) return "both";
  if (desc.includes("來源:自選") || desc.includes("來源：自選")) return "watchlist";
  if (desc.includes("來源:未發動") || desc.includes("來源：未發動")) return "armed";
  return null;
}

export function poolSourceLabel(pool: "armed" | "watchlist" | "both" | null): string | null {
  if (pool === "armed") return "未發動";
  if (pool === "watchlist") return "自選";
  if (pool === "both") return "未發動+自選";
  return null;
}
