// trever-radar-data worker(docs/31 §3.2)
// 職責:radar.techtrever.com/data/*(與影子驗證用 /data-preview/*)→ 讀 R2 資料 bucket 回應。
// Phase 1 不做身分驗證——Cloudflare Access 在更前面擋(docs/31 §6 WP-B7 之前不得改動此假設)。
// 安全邊界:只綁 trever-radar-data(站台 JSON);DB 快照放獨立 bucket trever-radar-backup,
// 本 worker 無 binding、實體搆不到。

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

    let key;
    try {
      key = decodeURIComponent(m[2]);
    } catch {
      return new Response("bad request", { status: 400 });
    }
    // R2 key 是字面字串不會解析 "..",此檢查為縱深防禦
    if (key.includes("..") || key.includes("//") || key.startsWith("/") || key.includes("\\")) {
      return new Response("bad request", { status: 400 });
    }
    // WP-B2 影子驗證:/data-preview/* 讀 shadow/ prefix,cutover 後兩路徑並存也互不干擾
    if (m[1] === "data-preview") key = `shadow/${key}`;

    const obj = await env.DATA_BUCKET.get(key);
    if (!obj) return new Response("not found", { status: 404 });

    const headers = new Headers();
    obj.writeHttpMetadata(headers);
    headers.set("etag", obj.httpEtag);
    if (!headers.has("content-type")) {
      headers.set(
        "content-type",
        key.endsWith(".json") ? "application/json; charset=utf-8" : "application/octet-stream",
      );
    }
    const basename = key.split("/").pop();
    headers.set(
      "cache-control",
      NO_STORE.has(basename) ? "no-store" : `public, max-age=${CACHE_TTL_SECONDS}`,
    );

    if (request.headers.get("if-none-match") === obj.httpEtag) {
      return new Response(null, { status: 304, headers });
    }
    return new Response(request.method === "HEAD" ? null : obj.body, { headers });
  },
};
