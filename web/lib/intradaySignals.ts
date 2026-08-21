/** 盤中訊號 I-1～I-4 人話對照（docs/24 §2.2；色非唯一訊號，必帶文字標籤） */

export type IntradaySignalType = "I-1" | "I-2" | "I-3" | "I-4" | string;

export type SignalMeta = {
  code: string;
  /** 短標籤，列表掃讀用 */
  label: string;
  /** 一句人話：發生了什麼 */
  meaning: string;
  /** 門檻白話 */
  rule: string;
  /** 是否視為「發動」級 */
  breakout: boolean;
};

export const SIGNAL_META: Record<string, SignalMeta> = {
  "I-1": {
    code: "I-1",
    label: "大單",
    meaning: "出現單筆大額成交",
    rule: "單筆成交金額 ≥ 500 萬",
    breakout: false,
  },
  "I-2": {
    code: "I-2",
    label: "爆量",
    meaning: "量能明顯高於今日時間進度",
    rule: "累積量 ≥ 依開盤至今折算日均量的 2 倍（開盤滿 5 分才判）",
    breakout: false,
  },
  "I-3": {
    code: "I-3",
    label: "急拉",
    meaning: "短時間價格急升",
    rule: "近 5 分鐘相對窗內最低價漲幅 ≥ 2%",
    breakout: false,
  },
  "I-4": {
    code: "I-4",
    label: "發動",
    meaning: "股價突破觀察價",
    rule: "現價 ≥ 盤後觀察價（watch price）",
    breakout: true,
  },
};

export function signalMeta(type: IntradaySignalType): SignalMeta {
  return (
    SIGNAL_META[type] ?? {
      code: String(type),
      label: String(type),
      meaning: "盤中監控訊號",
      rule: "見系統規則",
      breakout: false,
    }
  );
}

/** 從 signal_desc 解析 worker 附加的來源標記 */
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
