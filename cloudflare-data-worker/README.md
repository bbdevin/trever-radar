# cloudflare-data-worker — `/data/*` R2 資料層(docs/31 §3.2)

把 `radar.techtrever.com/data/*` 的請求轉為讀取 R2 私有 bucket `trever-radar-data`,
讓資料更新「VPS 傳 R2 即生效」,與網站部署(Pages)徹底解耦。

## 邊界(不得破壞)

- **Phase 1 本 worker 不做身分驗證**:門禁由 Cloudflare Access 負責(整站鎖,含 /data)。
  登入統一(Supabase JWT 白名單)是 docs/31 WP-B7 的事,需資安審查後另行實作。
- **只綁 `trever-radar-data`**:DB 快照在獨立 bucket `trever-radar-backup`,本 worker 沒有
  binding,任何 path 都搆不到——不得為了方便把兩顆 bucket 合併或加綁。
- `/data-preview/*` 讀 bucket 內 `shadow/` prefix,是 WP-B2 影子驗證通道;cutover 後保留無妨。

## 部署(人工,一次)

前置:Cloudflare 帳號已建好兩顆 R2 私有 bucket(`trever-radar-data`、`trever-radar-backup`)。

```bash
cd cloudflare-data-worker
npx wrangler deploy        # 首次會引導瀏覽器登入 Cloudflare
```

cutover(docs/31 WP-B3)時:解除 `wrangler.toml` 內 `/data/*` 路由的註解,再 `npx wrangler deploy` 一次。

## 驗收

```bash
# 影子期(WP-B2):
# 1) 未登入(無 Access session)必須被擋(302 到 Access 登入頁,不是 JSON):
curl -sI https://radar.techtrever.com/data-preview/radar.json | head -3
# 2) 瀏覽器登入 Access 後開同一網址,應看到 JSON 且 freshness 為 VPS 影子輪產出。

# cutover 後(WP-B3):同樣兩測換成 /data/radar.json;另驗 ETag:
curl -sI -H "Cookie: <Access session>" https://radar.techtrever.com/data/radar.json
# 第二次帶 If-None-Match 應回 304。
```

任何一測不符 → 停止切換,回報使用者(docs/31 §7 風險表 B0/B3 列)。

## 快取策略

`radar.json`/`meta.json` = `no-store`(榜單必須即時);其餘檔案 `max-age=300`。
調整常數在 `src/index.js` 頂部。
