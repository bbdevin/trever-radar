# cloudflare-data-worker — `/data/*` 資料層(docs/31 §3.2,v3 Workers 靜態資產)

把 `radar.techtrever.com/data/*` 的請求交給本 worker,回應「隨 deploy 上傳的靜態 JSON 資產」。
資料更新 = VPS 跑完 export-json 後 `npx wrangler deploy`(數十秒生效),與網站部署(Pages)徹底解耦。
**全程免費且無需綁信用卡**(2026-07-15 v3 定案:R2 因啟用需綁卡而不採用)。

## 邊界(不得破壞)

- **Phase 1 本 worker 不做身分驗證**:門禁由 Cloudflare Access 負責(整站鎖,含 /data)。
  登入統一(Supabase JWT 白名單)是 docs/31 WP-B7 的事,需資安審查後另行實作。
- **DB 快照永不進資產**:資產目錄 = `web/public/data`(export-json 產物,只有 JSON);
  DB 備份只走 Google Drive(docs/31 §4),不得為了方便把 `.db`/`.db.gz` 放進資產目錄。
- `/data-preview/*` 是 WP-B2 影子驗證通道,與 `/data/*` 讀同一份資產;cutover 後保留無妨。

## 部署(VPS,每輪資料更新自動執行)

前置(一次性):
1. 【人工】Cloudflare Dashboard → My Profile → API Tokens → 建 token,權限只給
   **Account / Workers Scripts: Edit** + **Zone / Workers Routes: Edit(zone: techtrever.com)**。
   此 token 動不了 Pages/DNS/帳戶——資料與部署權限分離(docs/31 §5.1)。
2. VPS 裝 node LTS(僅為 wrangler,不 build 前端),`vps/.env` 填 `CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID`。

每輪(cron script 內,export-json 之後):

```bash
cd ~/trever-radar/cloudflare-data-worker
npx wrangler deploy   # 讀 ../web/public/data;內容 hash 去重,只上傳變動檔
```

首次 deploy 必須在「資產目錄有完整 export 產物」的機器上跑(= VPS),否則目錄不存在會失敗。

cutover(docs/31 WP-B3)時:解除 `wrangler.toml` 內 `/data/*` 路由的註解,再 deploy 一次。

## 驗收

```bash
# 影子期(WP-B2):
# 1) 未登入(無 Access session)必須被擋(302 到 Access 登入頁,不是 JSON):
curl -sI https://radar.techtrever.com/data-preview/radar.json | head -3
# 2) 瀏覽器登入 Access 後開同一網址,應看到 JSON 且 freshness 為 VPS 影子輪產出。

# cutover 後(WP-B3):同樣兩測換成 /data/radar.json;另驗 304:
curl -sI -H "Cookie: <Access session>" https://radar.techtrever.com/data/radar.json
# 第二次帶 If-None-Match 應回 304。
```

任何一測不符 → 停止切換,回報使用者(docs/31 §7 風險表 B0/B3 列)。

## 平台限制(現況遠低於上限)

單檔 25MB(現最大個股 JSON ~0.5MB)、資產 2 萬檔(現 ~1,000+)、免費 10 萬 req/日(≤10 人)。

## 快取策略

`radar.json`/`meta.json` = `no-store`(榜單必須即時);其餘檔案 `max-age=300`。
調整常數在 `src/index.js` 頂部。
