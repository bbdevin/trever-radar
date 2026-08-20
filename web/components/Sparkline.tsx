/** 迷你走勢:有 open = 當日分時(相對開盤、平盤虛線);否則近 30 日收盤。紅漲綠跌依台股慣例。 */
export default function Sparkline({
  data,
  id,
  open,
}: {
  data: number[];
  id: string;
  open?: number;
}) {
  if (!data || data.length < 2) {
    return <span className="text-[11px] text-muted-foreground">走勢累積中</span>;
  }
  const w = 200;
  const h = 34;
  const isDay = open != null && Number.isFinite(open);
  const min = Math.min(...data, ...(isDay ? [open as number] : []));
  const max = Math.max(...data, ...(isDay ? [open as number] : []));
  const pt = (v: number, i: number) => {
    const x = (i / (data.length - 1)) * w;
    const norm = max === min ? 0.5 : (v - min) / (max - min);
    const y = h - 3 - norm * (h - 6);
    return [x, y] as const;
  };
  const pts = data.map((v, i) => pt(v, i).map((n) => n.toFixed(1)).join(",")).join(" ");
  const last = data[data.length - 1];
  const baseline = isDay ? (open as number) : data[0];
  const up = last >= baseline;
  const color = up ? "var(--up)" : "var(--down)";
  const gid = `sg-${id}`;
  const openY = isDay ? pt(open as number, 0)[1] : 0;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={`0,${h} ${pts} ${w},${h}`} fill={`url(#${gid})`} stroke="none" />
      {isDay && (
        <line
          x1="0"
          x2={w}
          y1={openY}
          y2={openY}
          stroke="var(--line)"
          strokeWidth="1"
          strokeDasharray="3 3"
          vectorEffect="non-scaling-stroke"
        />
      )}
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth="1.6"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
