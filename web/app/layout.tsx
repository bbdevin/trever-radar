import type { Metadata, Viewport } from "next";
import { Manrope } from "next/font/google";
import AuthButton from "@/components/AuthButton";
import BottomNav from "@/components/BottomNav";
import SearchBox from "@/components/SearchBox";
import { IconRadar } from "@/components/Icons";
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
  { label: "盤中雷達", planned: "V2" },
  { label: "探索", planned: "近期" },
  { label: "自選", planned: "近期" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-Hant" className={manrope.variable}>
      <body>
        <header className="site-header">
          <div className="container header-inner">
            <a href="/" className="brand">
              <span className="brand-mark">
                <IconRadar size={22} />
              </span>
              <span className="brand-text">
                Trever Radar
                <em>盤後找籌碼,盤中看發動</em>
              </span>
            </a>
            <div className="header-actions">
              <SearchBox />
              <AuthButton />
            </div>
            <nav className="nav">
              {NAV.map((n) =>
                n.href ? (
                  <a key={n.label} href={n.href} className="active">
                    {n.label}
                  </a>
                ) : (
                  <span key={n.label} className="disabled" title="開發中">
                    {n.label}
                    <small>{n.planned}</small>
                  </span>
                ),
              )}
            </nav>
          </div>
        </header>
        <main className="container">{children}</main>
        <footer className="site-footer">
          <div className="container">
            本系統僅彙整公開市場資料供個人研究,非投資建議;訊號不保證獲利;投資人應自行判斷並承擔風險。資料來源:臺灣證券交易所、證券櫃檯買賣中心。
          </div>
        </footer>
        <BottomNav />
      </body>
    </html>
  );
}
