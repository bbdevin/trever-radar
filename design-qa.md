# 個股頁身份列與行情摘要 — Design QA（2026-08-31）

## 狀態：正式站通過（HEAD `8603f3a`）

- 視覺來源：`C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\exec-731ce944-fae2-471d-bab4-ed6d2e2f0a94.png`（853×1844）。來源與實作已在同一 comparison input 比較；後續使用者 annotation 及 `052e0e0`…`8603f3a` commits 是對該舊來源的明確覆寫。
- 最終深色實作：`C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\stock-ui-8603f3a-dark-top.png`（375×812）。基本資料完整畫面：同目錄 `stock-ui-8603f3a-basic-full.png`。
- 正式站：`https://radar.techtrever.com/stock?id=3376`；`8603f3a` 的 GitHub Actions `deploy` 已成功。驗收 viewport 為 in-app browser 390×844，內容區 `clientWidth=375`。參考圖與實作沒有做像素縮放疊圖；來源 device scale factor 未提供，因此以相同資訊層級的可見比較、375px CSS 內容寬與 DOM 尺寸共同判讀。

## 最終驗收

- 整頁 `clientWidth=375 / scrollWidth=375`；`stock-context-grid=347 / 347`、header `202 / 202`、price `154 / 154`、market `135 / 135`，無水平 overflow、無文字裁切。
- 身份列分離代號與完整名稱；44×44 Watchlist 位於右上。價格保留名稱下方；行情摘要去框，觀察價／失效價移到其下方。持平或缺昨收的開高低是中性色且**不顯示** `▲`／`▼` 前綴；有方向時才同時用 glyph 與紅／綠語意色。
- Decision 為固定完整顯示，無收合 button；四個 pills 全數可見。targets 不在 Decision 區，而在右側行情摘要下方。
- 個股一級 tabs 為 8 個：K線／籌碼日報／三大法人／資券／大戶／基本資料／技術／權證。基本資料已驗證地址、股務、官方來源、3 個題材與庫藏股的誠實空態。
- 首頁一級 tabs 為 10 個：綜合／策略／未發動／已發動／資券／市場掃描／追高風險／失效／口袋／權證。
- 已驗證無 console error。密度以 375px CSS 內容寬、而非來源圖的 853px 寬及瀏覽器 chrome 高度判讀；互動驗收以本輪固定 Decision 與 tab 可達性為準。

### 五項 fidelity 檢核

- **Typography**：沿用現有字體與 type scale；代號／名稱、價格、Decision、行情數字層級可辨，沒有省略或裁字。
- **Spacing / layout**：沿用既有 4／8px rhythm、44px touch target 與圓角；首屏左右欄、Decision、tab 與基本資料在 375px 內容寬無 overflow。
- **Colors / tokens**：沿用既有 surface／border／text tokens；上漲紅、下跌綠搭配方向 glyph，不以顏色作唯一訊號。這輪只重驗深色正式站，不宣稱重新驗收淺色。
- **Images / assets**：沒有新增或替換圖片資產；品牌 logo 與既有 Lucide icons 均保留，未用文字或臨時圖形冒充資產。
- **Copy / content**：身份、完整 Decision pills、行情欄位、觀察／失效價、8／10 tabs 與基本資料內容均與目前契約一致；缺資料維持誠實空態。

## 比較歷程（保留）

1. `53b24f4`／`987ebeb`／`9698def`／`f323f95` 是早期 header 收斂與 overflow 修正的歷史基準，不再是最終畫面規格。
2. `052e0e0`：分離代號／名稱、Watchlist 移右上、行情去框。
3. `3f2d046` 的暫時展開版已由 `3be8fac` 覆寫：價格回到名稱下方，Decision 改為固定展開且無收合 button。
4. `3989a74`：觀察／失效價移至右側行情下方，平盤／缺昨收不再顯示 dash glyph。
5. `8603f3a`：首頁 tab 順序完成最終調整。

## 驗證

- 已登入 in-app browser：390×844／client 375、各指定 DOM 寬度、固定 Decision、8 個個股 tabs、10 個首頁 tabs、基本資料完整內容與 console 均通過。
- 專案未安裝獨立 Playwright；未宣稱其執行結果。本輪採使用者指定的已登入 in-app browser 做正式站驗收。
- `npx tsc --noEmit`、`node --check scripts/verify-mobile-stock.mjs`、`git diff --check`：本次文件更新後均通過。

## Open questions

- 無阻塞問題。淺色模式未在 `8603f3a` 重新做完整正式站 QA；本輪沒有改前端程式或色彩 token，故不把它冒稱為本輪驗收項。

final result: passed
