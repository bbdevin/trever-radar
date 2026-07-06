/** 近 30 日收盤迷你走勢(SVG,紅漲綠跌依首尾比較) */
export default function Sparkline({ data }: { data: number[] }) {
  if (!data || data.length < 2) {
    return <span className="spark-empty">走勢累積中</span>;
  }
  const w = 120;
  const h = 30;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const pts = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w;
      const norm = max === min ? 0.5 : (v - min) / (max - min);
      const y = h - 2 - norm * (h - 4);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const up = data[data.length - 1] >= data[0];
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <polyline
        points={pts}
        fill="none"
        stroke={up ? "var(--up)" : "var(--down)"}
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}
