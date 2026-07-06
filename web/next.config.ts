import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 零伺服器原則:純靜態輸出,部署到 Cloudflare Pages / Vercel 免費層
  output: "export",
};

export default nextConfig;
