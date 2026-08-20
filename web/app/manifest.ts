import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Trever Radar — 台股籌碼雷達",
    short_name: "Trever Radar",
    description: "盤後找籌碼，盤中看發動。私人研究工具，非投資建議。",
    start_url: "/",
    display: "standalone",
    background_color: "#0d0d0d",
    theme_color: "#0d0d0d",
    orientation: "portrait",
    icons: [
      {
        src: "/icons/trever-radar-mark.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "any maskable",
      },
    ],
  };
}
