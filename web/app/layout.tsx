import type { Metadata, Viewport } from "next";
import { Manrope } from "next/font/google";
import AuthButton from "@/components/AuthButton";
import BottomNav from "@/components/BottomNav";
import SearchBox from "@/components/SearchBox";
import { IconRadar } from "@/components/Icons";
import { WatchlistProvider } from "@/lib/watchlist";
import "./globals.css";

// 數字與拉丁字用 Manrope(build 時自託管);中文走系統字體堆疊
const manrope = Manrope({ subsets: ["latin"], weight: ["500", "600", "700", "800"], variable: "--font-num" });

export const metadata: Metadata = {
  title: "Trever Radar — 台股籌碼雷達",
  description: "盤後找籌碼,盤中看發動。私人研究工具,非投資建議。",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#0d0d0d",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

const NAV = [
  { label: "今日雷達", href: "/", active: true },
  { label: "分點排行", href: "/branch" },
  { label: "探索", href: "/explore" },
  { label: "自選", href: "/watchlist" },
  { label: "盤中雷達", planned: "V2" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-Hant" className={`dark ${manrope.variable}`}>
      <body>
        <WatchlistProvider>
          <header className="sticky top-0 z-40 border-b border-border bg-background/78 backdrop-blur-md backdrop-saturate-150">
            <div className="container flex h-[58px] items-center gap-5">
              <a href="/" className="flex items-center gap-2.5 text-foreground">
                <span
                  className="grid size-[34px] shrink-0 place-items-center rounded-[10px] text-white shadow-[0_2px_10px_rgba(57,135,229,0.35)]"
                  style={{ background: "var(--grad-accent)" }}
                >
                  <IconRadar size={22} />
                </span>
                <span className="flex flex-col leading-tight">
                  <span className="text-[16.5px] font-extrabold tracking-tight">Trever Radar</span>
                  <em className="text-[11px] font-normal not-italic text-muted-foreground">盤後找籌碼,盤中看發動</em>
                </span>
              </a>
              <div className="ml-auto flex items-center">
                <SearchBox />
                <AuthButton />
              </div>
              <nav className="hidden gap-0.5 md:flex">
                {NAV.map((n) =>
                  n.href ? (
                    <a
                      key={n.label}
                      href={n.href}
                      className="rounded-full bg-muted px-3.5 py-1.5 text-[13.5px] font-semibold text-foreground"
                    >
                      {n.label}
                    </a>
                  ) : (
                    <span
                      key={n.label}
                      className="cursor-default rounded-full px-3.5 py-1.5 text-[13.5px] text-muted-foreground"
                      title="開發中"
                    >
                      {n.label}
                      <small className="ml-1 rounded-[5px] border border-border px-1 text-[10px] text-muted-foreground">
                        {n.planned}
                      </small>
                    </span>
                  ),
                )}
              </nav>
            </div>
          </header>
          <main className="container">{children}</main>
          <footer className="border-t border-border py-4 pb-[26px] text-[11.5px] text-muted-foreground max-md:mb-16">
            <div className="container">
              本系統僅彙整公開市場資料供個人研究,非投資建議;訊號不保證獲利;投資人應自行判斷並承擔風險。資料來源:臺灣證券交易所、證券櫃檯買賣中心。
            </div>
          </footer>
          <BottomNav />
        </WatchlistProvider>
      </body>
    </html>
  );
}
