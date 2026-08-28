# 個股頁 browser annotation — Design QA（2026-08-28）

## 狀態：正式站通過

- 視覺真相：`C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\exec-731ce944-fae2-471d-bab4-ed6d2e2f0a94.png`（853×1844）。
- 本輪正式站畫面：`C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\stock-ui-c26ea04-top-clean.png`（1280×820 Codex 視窗擷取；內含正式站 responsive viewport）。
- 前輪同頁深／淺色與基本資料基準：`stock-ui-55beda9-dark-top.png`、`stock-ui-55beda9-light-top.png`、`stock-ui-55beda9-basic.png`（均 390×844）。
- 正式站：`https://radar.techtrever.com/stock?id=3376`，程式 commit `c26ea04`；DOM／互動驗收以 390×844（實際 client width 375px）執行，另驗 844×390 landscape。
- 正規化：參考圖為 853×1844 高密度設計稿；實作以 390×844 CSS viewport 判讀，不把 Codex／瀏覽器 chrome、捲軸保留的 15px 或擷取縮放當成版面差異。

## Findings

- 無 P0／P1／P2。使用者標註的行情摘要已位於預設收合 Decision Header 右側；兩者 `y=141.64`，左右 `x=14 / 226.19`。行情含資料日、量、額、昨收、開盤、最高、最低。
- 重複 compact 公司概況列已移除，正式 DOM `stock-overview=0`；基本資料仍由 44px 一級 tab 直接進入。
- 題材已集中成 compact chips／rows。3376 顯示「電子零件元件、模具沖壓、樞紐」，不再逐筆顯示「資料未提供／狀態未提供／分類日／來源更新」。
- 題材來源只有有效絕對 `http://`／`https://` URL 才可點；`fubon` 這類來源識別字改為純文字，不生成壞相對連結。合法來源仍保留 44px touch target、focus ring、aria-label 與 title。
- 390×844 DOM 為 `innerWidth=390 / clientWidth=375 / scrollWidth=375`，無水平 overflow；844×390 landscape 為 `clientWidth=829 / scrollWidth=829`，左右欄仍同高起點且無 overflow。
- Decision 展開後右側行情 `x=226.19` 不位移，再次收合正常；基本資料 tab `aria-selected=true`，公司資料／題材／庫藏股三個 heading 仍在。
- 字型、字級、色彩、圓角、邊框、Lucide icon 與紅漲綠跌沿用既有 tokens；本輪沒有新增圖片資產。深／淺色基準已於前輪正式站驗收，本輪只調版面與來源 URL guard，未改 theme token。
- 參考圖與本輪正式站畫面已在同一視覺輸入比較；使用者要求移除的概況列屬刻意覆寫，其餘首屏層級、左右行情與資訊密度沒有可執行的 P0／P1／P2 差異。重要細節另以 DOM 量測，不需額外 focused crop。

## 驗證

- `npx tsc --noEmit`：通過。
- `git diff --check`：通過（僅 Windows CRLF normalization warning）。
- GitHub Actions `deploy`：commit `40001fd` 與 `c26ea04` 的 Next build／Cloudflare Pages deploy 均通過。
- Terra High：實作與 URL guard 修正；Luna High：兩次唯讀 review 均 APPROVE、無 blocker。
- 獨立 `verify-mobile-stock.mjs` 未直接執行：專案 `web` 未安裝獨立 Playwright；已用使用者選定的已登入 in-app browser 執行等價正式站 DOM／點擊／responsive 驗收。verifier 已覆蓋左右欄、行情欄位、無概況列、題材缺值與絕對 HTTP(S) 來源契約。

final result: passed
