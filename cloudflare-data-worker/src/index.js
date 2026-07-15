// trever-radar-data worker(docs/31 §3.2,v3 Workers 靜態資產模式)
// 職責:radar.techtrever.com/data/*(與影子驗證用 /data-preview/*)→ 回應隨 deploy 上傳的靜態 JSON 資產。
// 資料更新 = VPS 於 export-json 後 `npx wrangler deploy`(資產內容 hash 去重,只傳變動檔)。
// Phase 1 不做身分驗證——Cloudflare Access 在更前面擋(docs/31 WP-B7 之前不得改動此假設)。
// DB 快照不在本 worker 資產內(備份只走 Google Drive,docs/31 §4),路徑上實體搆不到。

// 榜單/總覽必須即時;其餘(個股 K 線等大檔)允許短快取
const NO_STORE = new Set(["radar.json", "meta.json"]);
const CACHE_TTL_SECONDS = 300;

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("method not allowed", { status: 405 });
    }

    const url = new URL(request.url);
    const m = url.pathname.match(/^\/(data|data-preview)\/(.+)$/);
    if (!m) return new Response("not found", { status: 404 });

    // 資產路徑安全:URL 正規化已處理 "..",此檢查為縱深防禦
    if (m[2].includes("..") || m[2].includes("//") || m[2].includes("\\")) {
      return new Response("bad request", { status: 400 });
    }

    // /data/x 與 /data-preview/x 都映射到資產根的 /x
    // (影子期正式站 /data 仍由舊鏈供應,本 worker 只掛 preview 路由,無需 prefix 區隔)
    const assetReq = new Request(new URL(`/${m[2]}`, url.origin), {
      method: request.method,
      headers: request.headers, // 帶原 if-none-match,資產層自行回 304
    });
    const resp = await env.ASSETS.fetch(assetReq);
    if (resp.status === 404) return new Response("not found", { status: 404 });

    const headers = new Headers(resp.headers);
    const basename = m[2].split("/").pop();
    headers.set(
      "cache-control",
      NO_STORE.has(basename) ? "no-store" : `public, max-age=${CACHE_TTL_SECONDS}`,
    );
    return new Response(resp.body, { status: resp.status, headers });
  },
};
