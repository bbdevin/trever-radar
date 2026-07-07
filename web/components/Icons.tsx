/** 極簡 SVG 圖示集(lucide 風格,stroke 1.8)。不用 emoji 當圖示。 */
type P = { size?: number; className?: string };

const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
});

export const IconRadar = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="9" opacity="0.35" />
    <circle cx="12" cy="12" r="5" opacity="0.55" />
    <circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" />
    <path d="M12 12 L18.5 5.8" />
    <path d="M18.5 5.8 A9 9 0 0 1 21 12" opacity="0.9" />
  </svg>
);

export const IconPulse = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M3 12h4l2.5-6 4 12 2.5-6H21" />
  </svg>
);

export const IconCompass = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="9" />
    <path d="M15.5 8.5 13.5 13.5 8.5 15.5 10.5 10.5z" />
  </svg>
);

export const IconStar = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.9-5.2-2.8-5.2 2.8 1-5.9L3.5 9.7l5.9-.9z" />
  </svg>
);

export const IconFlame = ({ size = 16, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M12 3c1 3-3 4.5-3 8a3 3 0 0 0 6 0c0-1.2-.5-2-.5-2s3 1.5 3 5a5.5 5.5 0 0 1-11 0c0-5 4.5-7 5.5-11z" />
  </svg>
);

export const IconZap = ({ size = 16, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M13 2 4.5 13.5H11L9.5 22 19 10h-6.5z" />
  </svg>
);

export const IconTrend = ({ size = 16, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M3 17l6-6 4 4 8-8" />
    <path d="M15 7h6v6" />
  </svg>
);

export const IconArrowLeft = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M19 12H5" />
    <path d="M12 19l-7-7 7-7" />
  </svg>
);
