# cloudflare-data-worker — `/data/*` 資料層(docs/31 §3.2,v3 Workers 靜態資產)

把 `radar.techtrever.com/data/*` 的請求交給本 worker,回應「隨 deploy 上傳的靜態 JSON 資產」。
資料更新 = VPS 跑完 export-json 後 `npx wrangler deploy`(數十秒生效),與網站部署(Pages)徹底解耦。
**全程免費且無需綁信用卡**(2026-07-15 v3 定案:R2 因啟用需綁卡而不採用)。

## 邊界(不得破壞)

- **2026-08-19 WP-B7:本 worker 必須驗身分**,未通過一律 401/403,不得回 JSON。通過條件二擇一:
  1. `X-Radar-Service-Key` 對上 wrangler secret `RADAR_SERVICE_KEY`(盤中 worker;優先於 JWT)
  2. `Authorization: Bearer <Supabase JWT>`,且 `app_profiles.status = approved`
- **JWT 驗證(2026-10-04 docs/44 P1,`src/auth.js`;資安審查通過,待使用者核准,未上線)**:
  - 只收 **ES256**(alg 釘死;none/HS256/RS256 一律 401),以 Supabase JWKS
    (`${SUPABASE_URL}/auth/v1/.well-known/jwks.json`)**本地驗簽**,不再呼叫 `/auth/v1/user`。
    **沒有 HS256 fallback;Worker 不持有 service_role key。**
  - 每個請求都驗:token ≤ 8KB、三段 base64url、`kid`、`typ` 缺或 JWT、`exp`(無寬限)、
    `iat`/`nbf` ≤ 現在 +60 秒、`iss` = `${SUPABASE_URL}/auth/v1`、`aud` 含 `authenticated`、
    `role = authenticated`、`sub` 為 UUID、64 位元組 r‖s 簽章。`is_anonymous = true` → 403。
  - `app_profiles` 仍用**使用者自己的 JWT 經 RLS** 讀(URL/headers 與舊版相同),結果以 `sub` 快取。
  - fail closed:JWKS 抓不到且記憶體內沒有任何金鑰 → 503;REST 連線失敗 → 503;絕不放行。
  - 不得記錄 token(測試鎖住 `src/` 無 `console.*`)。
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

```bash
# 假 / 過期 / alg 不對的 JWT → 必須 401(不是 200、不是 503)
curl -sS -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.x" \
  https://radar.techtrever.com/data/radar.json

# JWKS 必須有 EC P-256 / ES256 金鑰,且使用者 access token header 的 kid 在其中
curl -sS https://eroycvbgfitvyulfbbnw.supabase.co/auth/v1/.well-known/jwks.json
```

無痕開站應為站內 Google 登入。任何一測變成未認證可讀 JSON → 立刻回報,屬資料裸奔。

### 本機單元測試(不打網路、不 deploy)

```bash
cd cloudflare-data-worker
node --test test/auth.test.mjs test/worker.test.mjs   # Node ≥20.19/22.12(.js ESM 自動偵測)
```

自簽 P-256 token + stub fetch + 假時鐘;涵蓋 alg 混淆、竄改、claims、kid 重抓節流、
並發去重(20 請求 → JWKS 1 次、REST 1 次)、撤銷延遲、負快取、fail closed、快取上限、路由/標頭迴歸。
`MODULE_TYPELESS_PACKAGE_JSON` 警告可忽略(package.json 刻意不動)。

## 平台限制(現況遠低於上限)

單檔 25MB(現最大個股 JSON ~0.5MB)、資產 2 萬檔(現 ~1,000+)、免費 10 萬 req/日(≤10 人)。

## 快取策略

`radar.json`/`meta.json` = `private, no-store`;其餘檔案 `private, max-age=60`。
身分相關回應不可進共享快取。調整常數在 `src/index.js` 頂部。

### 驗證快取與撤銷延遲(isolate 記憶體,常數在 `src/auth.js` 頂部;改動需資安審查)

| 快取 | 內容 | TTL | 影響 |
|---|---|---|---|
| JWKS | kid → CryptoKey | 10 分(fetch 另帶邊緣快取:只有 2xx 快取 600 秒,錯誤回應不快取) | 未知 kid 每 60 秒最多強制重抓一次;網路錯誤/非 2xx/無法解析且有舊金鑰 → 沿用舊金鑰,60 秒後再試;完全沒有金鑰 → 503,10 秒後再試;2xx 且 `keys` 陣列內沒有可用 EC 金鑰 → 舊金鑰一併作廢(503) |
| profile | `sub` → approved / denied | 5 分 | **撤銷(改 rejected/pending)最長 5 分生效**;核准同理最長 5 分 |
| profile 失敗 | `sub` → REST 非 2xx | 45 秒 | 期間該使用者 401 |
| 上限 | profile 快取 1000 筆 | — | 超過淘汰最舊 |

- token 本身每次都驗:過期立即 401,不受 profile 快取影響。
- **登出 / Supabase 撤銷 session 不會讓已發出的 access token 立刻失效**(不再問 `/auth/v1/user`),
  最長到該 token `exp`(Supabase 預設 1 小時)。要立即擋人 → 把 `app_profiles.status` 改掉(≤5 分)。
- 輪替 JWKS 金鑰:先在 Supabase 建 standby key,**standby 存在 ≥30 分後**才切成 current
  (邊緣快取 10 分 + isolate 10 分 + 餘裕),否則切換後新 token 可能短暫 401。
- **金鑰外洩緊急撤銷**:Supabase 撤掉金鑰後,最長約 30 分才傳到 Worker(JWKS 持續抓取失敗時更久,
  因為會沿用舊金鑰)。要立即擋人 → 同時把相關使用者的 `app_profiles.status` 改掉(≤5 分生效)。
  注意外洩的簽章金鑰可偽造**任何**已核准使用者的 `sub`,所以真正的金鑰外洩要把**全部** approved
  暫時改掉(全站暫停)才擋得住,等 JWKS 撤銷生效後再改回。
- 同一 isolate 同時多個請求:JWKS 只抓一次、同一 `sub` 的 REST 只查一次(共用 promise,交給 `ctx.waitUntil`)。
