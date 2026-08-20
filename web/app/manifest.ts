import type { MetadataRoute } from "next";

export const dynamic = "force-static";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Trever Radar — 台股籌碼雷達",
    short_name: "Trever Radar",
    description: "盤後找籌碼，盤中看發動。私人研究工具，非投資建議。",
    id: "/",
    lang: "zh-Hant",
    start_url: "/",
    scope: "/",
    display: "standalone",
    display_override: ["standalone", "minimal-ui"],
    background_color: "#0d0d0d",
    theme_color: "#0d0d0d",
    orientation: "portrait",
    categories: ["finance"],
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/icon-maskable-192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
      { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
      { src: "/icons/trever-radar-mark.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
    ],
    shortcuts: [
      { name: "今日雷達", short_name: "雷達", url: "/" },
      { name: "分點研究", short_name: "分點", url: "/branch" },
      { name: "自選追蹤", short_name: "自選", url: "/watchlist" },
    ],
  };
}
