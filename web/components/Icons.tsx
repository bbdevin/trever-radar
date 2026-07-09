import { Activity, ArrowLeft, Compass, Flame, Star, TrendingDown, TrendingUp, Zap } from "lucide-react";

/** 圖示集:品牌 logo mark 手刻保留,其餘統一走 lucide-react(stroke 1.8,與品牌線寬一致)。 */
type P = { size?: number; className?: string };

export const IconRadar = ({ size = 20, className }: P) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.8}
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
  >
    <circle cx="12" cy="12" r="9" opacity="0.35" />
    <circle cx="12" cy="12" r="5" opacity="0.55" />
    <circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" />
    <path d="M12 12 L18.5 5.8" />
    <path d="M18.5 5.8 A9 9 0 0 1 21 12" opacity="0.9" />
  </svg>
);

export const IconPulse = ({ size = 20, className }: P) => (
  <Activity size={size} className={className} strokeWidth={1.8} />
);

export const IconCompass = ({ size = 20, className }: P) => (
  <Compass size={size} className={className} strokeWidth={1.8} />
);

export const IconStar = ({ size = 20, className }: P) => (
  <Star size={size} className={className} strokeWidth={1.8} />
);

export const IconFlame = ({ size = 16, className }: P) => (
  <Flame size={size} className={className} strokeWidth={1.8} />
);

export const IconZap = ({ size = 16, className }: P) => (
  <Zap size={size} className={className} strokeWidth={1.8} />
);

export const IconTrend = ({ size = 16, className }: P) => (
  <TrendingUp size={size} className={className} strokeWidth={1.8} />
);

export const IconTrendDown = ({ size = 16, className }: P) => (
  <TrendingDown size={size} className={className} strokeWidth={1.8} />
);

export const IconArrowLeft = ({ size = 18, className }: P) => (
  <ArrowLeft size={size} className={className} strokeWidth={1.8} />
);
