# 個股頁身份列與行情摘要 — Design QA（2026-08-28）

## 狀態：正式站通過

- 視覺真相：`C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\exec-731ce944-fae2-471d-bab4-ed6d2e2f0a94.png`（853×1844）；本輪另以使用者 browser annotation 明確覆寫身份列為「第一列代號＋名稱、第二列現價＋漲跌點數（漲跌幅），自選星號與第一列同高」。
- 第一輪正式站畫面：`C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\stock-ui-53b24f4-dark-top.png`（375×812）。
- 最終正式站深色畫面：`C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\stock-ui-f323f95-dark-top.png`（375×812）。
- 最終正式站淺色畫面：`C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\stock-ui-f323f95-light-top-clean.png`（375×812）。
- 正式站：`https://radar.techtrever.com/stock?id=3376`，程式 commit `f323f95`；browser viewport 390×844，瀏覽器捲軸後實際內容 `clientWidth=375`，擷取為 375×812；深／淺色、Decision 展開／收合均實測。
- 正規化：參考圖為高密度設計稿，實作以相同首屏內容區與 375px CSS 寬度判讀；不把瀏覽器 chrome、15px 捲軸或來源圖高度差當成版面差異。

## Findings

- 無待處理 P0／P1／P2。最終身份列第一列為 `3376 新日興`，第二列為 `217▲7(+3.33%)`，第三列保留 `上市 · 電子工業`；44×44 自選星號與第一列 `y=59` 同高。身份欄已置於 44px 返回鍵右側，不再貼齊頁面左緣。
- 最終報價列 `clientWidth=106 / scrollWidth=106`，名稱列 `96 / 96`、市場產業列 `106 / 106`，沒有截斷或水平溢位。漲跌同時使用 `▲／▼／—` 與紅／綠／中性色，不以顏色作唯一訊號。
- 行情摘要固定在首屏右側，`x=226.19 / y=73 / width=134.81`，與身份區同一垂直帶；資料日、量、額、昨收、開盤、最高、最低均保留。開高低以方向 glyph 加語意色呈現，資訊層級在深／淺色皆清楚。
- Decision Header 左側完整顯示 `認購權證成交3,005萬,為20日均值4.9倍`，`clientHeight=scrollHeight=80`；展開後右側行情仍維持 `x=226.19 / y=73`，不位移、不裁字。
- 整頁 `innerWidth=390 / clientWidth=375 / scrollWidth=375`，無頁面水平 overflow；既有八個一級 tabs、基本資料、題材與權證內容未因首屏調整回歸。
- 字型與字級沿用既有字體與 type scale；間距遵循既有 4/8px rhythm；圓角、邊框、表面色與紅漲綠跌皆使用既有 tokens。沒有新增圖片資產，品牌圖示與 Lucide icon 未被替換。
- 參考圖、第一輪與最終正式站畫面已放在同一比較輸入檢視。首屏文字與對齊可直接辨識，並以 DOM 尺寸補足精確驗證，因此不需要額外 focused crop。

## 比較歷程

1. `53b24f4`：首輪把 Decision 與行情左右並列，但短名稱顯示為 `新日…`，屬 P2 身份辨識退化；`987ebeb` 改為完整名稱。
2. `9698def`：依最新 annotation 改為兩列身份資訊與同列星號，但全形括號令 375px 內容寬下的報價列 `scrollWidth > clientWidth`，屬 P2 responsive overflow。
3. `f323f95`：改用半形括號並收斂數字列間距，保留現價與漲跌的視覺層級；最終 `stock-price` 為 `106 / 106`，P2 已解除。

## 驗證

- `npx tsc --noEmit`：通過。
- `git diff --check`：通過。
- GitHub Actions `deploy`：commit `f323f95` 的 Next build／Cloudflare Pages deploy 通過（run `33151643889`）。
- 正式站互動：Decision 展開／收合、深／淺色、390×844 responsive、頁面水平 overflow 均通過。
- Terra High：實作與 responsive 修正；Luna High：唯讀 review APPROVE、無 blocker。
- 獨立 `verify-mobile-stock.mjs` 未直接執行：專案 `web` 未安裝獨立 Playwright；已使用使用者選定的已登入 in-app browser 執行等價正式站 DOM／互動／responsive 驗收。verifier 契約已同步最新兩列格式與 overflow 檢查。

final result: passed
