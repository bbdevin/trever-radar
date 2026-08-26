# 搜尋歷史 ＋ 帳號綁定文字縮放

> 狀態：**程式已實作（2026-08-26）**；**Supabase SQL 已由使用者執行**（`docs/sql/20260826114421_create_user_ui_prefs.sql`）。  
> UI：ui-ux-pro-max＋`docs/19`（Lucide、無 emoji、現站品牌色）。

## 1. 功能

| 功能 | 行為 | 儲存 |
|---|---|---|
| 搜尋歷史 | 開搜尋框且關鍵字空白 → 最近代號；點選進個股；「清除歷史」 | Supabase `search_history`；**僅登入** |
| 文字縮放 | Header／大頭貼選單：標準 / 較大 / 最大 | 本機 + Supabase |
| 深淺色 | 預設**深色**；選單／登入頁可切 | 本機 + Supabase `theme` |

## 2. 字級代碼

| 代碼 | UI 文案 | 縮放 |
|---|---|---|
| `md` | 標準 | 1 |
| `lg` | 較大 | 1.125 |
| `xl` | 最大 | 1.25 |

實作：`html[data-font-scale]`＋`body { zoom }`（站上大量 px 字級需 zoom 才會變大）。

## 3. 前端

- `web/lib/userPrefs.tsx` — Provider
- `web/components/FontScaleToggle.tsx`
- `web/components/SearchBox.tsx` — 空態歷史
- `web/app/layout.tsx` — Provider＋Toggle

## 4. Confirmed Scope

- [x] SQL 稿＋本檔
- [x] UserPrefsProvider＋CSS
- [x] FontScaleToggle
- [x] SearchBox 歷史
- [x] **人工**：Supabase 執行 `20260826114421_create_user_ui_prefs.sql`（2026-08-26 使用者完成）
- [x] **修復**：選股後 `await pushSearch` 再導頁（避免請求被取消）；補 `GRANT`（見 `20260826114857_grant_user_ui_prefs.sql`）
- [x] **主題綁帳號**：`theme` 欄（預設 dark）；補跑 `20260826115525_add_user_ui_prefs_theme.sql`

## 5. 驗收

- A 搜兩檔 → 重開見歷史 → 清除後空；B 看不到 A 的歷史。
- A 設最大 → 重登仍最大；B 預設標準。
