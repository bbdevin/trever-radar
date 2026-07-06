import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Trever Radar — 台股籌碼雷達",
  description: "盤後找籌碼,盤中看發動。私人研究工具,非投資建議。",
  robots: { index: false, follow: false },
};

const NAV = [
  { label: "今日雷達", href: "/", active: true },
  { label: "盤中雷達", planned: "V2" },
  { label: "探索", planned: "V1" },
  { label: "個股", planned: "V1" },
  { label: "我的", planned: "V1" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-Hant">
      <body>
        <header className="site-header">
          <div className="container header-inner">
            <div>
              <div className="brand">
                Trever Radar<span className="dot">●</span>
              </div>
              <div className="tagline">盤後找籌碼,盤中看發動</div>
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
      </body>
    </html>
  );
}
