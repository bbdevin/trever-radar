import type { Metadata, Viewport } from "next";
import { Manrope } from "next/font/google";
import { Toaster } from "sonner";
import AuthButton from "@/components/AuthButton";
import AuthGate from "@/components/AuthGate";
import BottomNav from "@/components/BottomNav";
import DesktopNav from "@/components/DesktopNav";
import PwaProvider from "@/components/PwaProvider";
import SearchBox from "@/components/SearchBox";
import ThemeToggle from "@/components/ThemeToggle";
import FontScaleToggle from "@/components/FontScaleToggle";
import { WatchlistProvider } from "@/lib/watchlist";
import { UserPrefsProvider } from "@/lib/userPrefs";
import "./globals.css";

// 數字與拉丁字用 Manrope(build 時自託管);中文走系統字體堆疊
const manrope = Manrope({ subsets: ["latin"], weight: ["500", "600", "700", "800"], variable: "--font-num" });

export const metadata: Metadata = {
  title: "Trever Radar — 台股籌碼雷達",
  description: "盤後找籌碼,盤中看發動。私人研究工具,非投資建議。",
  robots: { index: false, follow: false },
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      { url: "/icons/favicon-32.png", sizes: "32x32", type: "image/png" },
      { url: "/icons/favicon-16.png", sizes: "16x16", type: "image/png" },
      { url: "/icons/trever-radar-mark.svg", type: "image/svg+xml" },
    ],
    apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
  appleWebApp: {
    capable: true,
    title: "Trever Radar",
    statusBarStyle: "black-translucent",
  },
};

export const viewport: Viewport = {
  themeColor: "#0d0d0d",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

// NAV config moved to DesktopNav component

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-Hant" className={`dark ${manrope.variable}`}>
      <body>
        {/* FOUC 防護:預設深色(html 已帶 .dark),僅在使用者曾選淺色時提前移除 dark。極小、無依賴、try/catch 包。 */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "(function(){try{if(localStorage.getItem('theme')==='light'){document.documentElement.classList.remove('dark')}var s=localStorage.getItem('font_scale');if(s==='md'||s==='lg'||s==='xl'){document.documentElement.dataset.fontScale=s;var z={md:'1',lg:'1.125',xl:'1.25'};if(document.body)document.body.style.zoom=z[s]||'1'}}catch(e){}})()",
          }}
        />
        <PwaProvider>
          <AuthGate>
            <UserPrefsProvider>
              <WatchlistProvider>
              <header className="sticky top-0 z-40 border-b border-border bg-background/78 pt-[env(safe-area-inset-top)] backdrop-blur-md backdrop-saturate-150">
                <div className="container flex h-[58px] items-center gap-5">
                  <a href="/" className="flex items-center gap-2.5 text-foreground">
                    <img
                      src="/icons/trever-radar-mark.svg"
                      alt=""
                      aria-hidden="true"
                      className="size-[34px] shrink-0 rounded-[10px] shadow-[0_2px_10px_rgba(57,135,229,0.35)]"
                    />
                    <span className="flex flex-col leading-tight">
                      <span className="text-[16.5px] font-extrabold tracking-tight">Trever Radar</span>
                      <em className="text-[11px] font-normal not-italic text-muted-foreground">盤後找籌碼,盤中看發動</em>
                    </span>
                  </a>
                  <div className="ml-auto flex items-center">
                    <SearchBox />
                    <FontScaleToggle />
                    <ThemeToggle />
                    <AuthButton />
                  </div>
                  <DesktopNav />
                </div>
              </header>
              <main className="container">{children}</main>
              <footer className="border-t border-border py-4 pb-[26px] text-[11.5px] text-muted-foreground max-md:mb-[calc(4.5rem+env(safe-area-inset-bottom))]">
                <div className="container">
                  本系統僅彙整公開市場資料供個人研究,非投資建議;訊號不保證獲利;投資人應自行判斷並承擔風險。資料來源:臺灣證券交易所、證券櫃檯買賣中心。
                </div>
              </footer>
              <BottomNav />
              </WatchlistProvider>
            </UserPrefsProvider>
          </AuthGate>
          <Toaster
            position="bottom-center"
            richColors
            offset={{ bottom: 24 }}
            mobileOffset={{ bottom: "calc(4.75rem + env(safe-area-inset-bottom))" }}
          />
        </PwaProvider>
      </body>
    </html>
  );
}
