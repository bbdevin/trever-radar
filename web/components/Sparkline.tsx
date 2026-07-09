/** 近 30 日收盤迷你走勢:面積漸層 + 線(紅漲綠跌依首尾) */
export default function Sparkline({ data, id }: { data: number[]; id: string }) {
  if (!data || data.length < 2) {
    return <span className="text-[11px] text-muted-foreground">走勢累積中</span>;
  }
  const w = 200;
  const h = 34;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const pt = (v: number, i: number) => {
    const x = (i / (data.length - 1)) * w;
    const norm = max === min ? 0.5 : (v - min) / (max - min);
    const y = h - 3 - norm * (h - 6);
    return [x, y] as const;
  };
  const pts = data.map((v, i) => pt(v, i).map((n) => n.toFixed(1)).join(",")).join(" ");
  const up = data[data.length - 1] >= data[0];
  const color = up ? "var(--up)" : "var(--down)";
  const gid = `sg-${id}`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={up ? "#e66767" : "#0ca30c"} stopOpacity="0.28" />
          <stop offset="100%" stopColor={up ? "#e66767" : "#0ca30c"} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={`0,${h} ${pts} ${w},${h}`} fill={`url(#${gid})`} stroke="none" />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
