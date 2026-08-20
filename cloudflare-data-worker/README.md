# cloudflare-data-worker — `/data/*` 資料層(docs/31 §3.2,v3 Workers 靜態資產)

把 `radar.techtrever.com/data/*` 的請求交給本 worker,回應「隨 deploy 上傳的靜態 JSON 資產」。
資料更新 = VPS 跑完 export-json 後 `npx wrangler deploy`(數十秒生效),與網站部署(Pages)徹底解耦。
**全程免費且無需綁信用卡**(2026-07-15 v3 定案:R2 因啟用需綁卡而不採用)。

## 邊界(不得破壞)

- **2026-08-19 WP-B7:本 worker 必須驗身分**,未通過一律 401/403,不得回 JSON。通過條件二擇一:
  1. `X-Radar-Service-Key` 對上 wrangler secret `RADAR_SERVICE_KEY`(盤中 worker)
  2. `Authorization: Bearer <Supabase JWT>`,且 `app_profiles.status = approved`
- **DB 快照永不進資產**:資產目錄 = `web/public/data`(export-json 產物,只有 JSON);
  DB 備份只走 Google Drive(docs/31 §4),不得為了方便把 `.db`/`.db.gz` 放進資產目錄。
- `/data-preview/*` 是 WP-B2 影子驗證通道,與 `/data/*` 讀同一份資產;cutover 後保留無妨,同樣要驗身分。
- **不要在本機 wrangler deploy**:本機 `web/public/data` 通常不完整,會覆蓋正式資產。只在 VPS 有完整 export 產物時 deploy。

## 一次性密鑰(先 secret、再 deploy)

Worker 程式上線後若還沒設 `RADAR_SERVICE_KEY`,盤中 worker 會立刻 401。順序必須是:

```bash
cd ~/trever-radar/cloudflare-data-worker
openssl rand -hex 32   # 複製輸出
npx wrangler secret put RADAR_SERVICE_KEY   # 貼上同一把
# 同一把寫進 ~/trever-radar/pipeline/intraday/.env 的 RADAR_SERVICE_KEY=
git pull   # 含本 worker 驗身分程式
npx wrangler deploy    # 必須在 web/public/data 已有完整 JSON 的 VPS 上
```

公開級 `SUPABASE_URL` / `SUPABASE_PUBLISHABLE_KEY` 已在 `wrangler.toml` `[vars]`(與前端相同,僅能配合 RLS)。

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

## 驗收(2026-08-20 Access 已關)

```bash
# 未登入 → 必須 401 JSON(login required),不是榜單、不是 302
curl -sS -D - -o - https://radar.techtrever.com/data/radar.json | head -15

# 帶 service key → 200
curl -sS -o /dev/null -w "%{http_code}\n" \
  -H "X-Radar-Service-Key: $RADAR_SERVICE_KEY" \
  https://radar.techtrever.com/data/radar.json
```

無痕開站應為站內 Google 登入。任何一測變成未認證可讀 JSON → 立刻回報,屬資料裸奔。

## 平台限制(現況遠低於上限)

單檔 25MB(現最大個股 JSON ~0.5MB)、資產 2 萬檔(現 ~1,000+)、免費 10 萬 req/日(≤10 人)。

## 快取策略

`radar.json`/`meta.json` = `private, no-store`;其餘檔案 `private, max-age=60`。
身分相關回應不可進共享快取。調整常數在 `src/index.js` 頂部。
