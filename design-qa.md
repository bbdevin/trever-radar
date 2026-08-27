# 個股「基本資料」UI — Design QA（2026-08-27）

## 比對目標與證據

- 視覺真相：`C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\exec-731ce944-fae2-471d-bab4-ed6d2e2f0a94.png`（853×1844 px）。
- 使用者覆寫：活躍題材改置於產業附近／下方，以較小文字與現有不同語意色呈現；原 mock 的公司資料／題材／庫藏股 bottom sheet 改為一級「基本資料」tab，置於「技術」左側，內容為單一連續三 section。
- 實作第一屏：`C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\stock-basic-mobile-top-final.png`（375×806 px）。
- 實作基本資料：`C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\stock-basic-mobile-tab-final.png`（375×806 px）。
- 同畫布比較：`C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\design-compare-stock-basic-final.png`（1210×838 px）。左為 mock 正規化至 390×838；中為 K 線第一屏；右為「基本資料」選中態。
- Browser viewport override：390×838 CSS px；實際頁面 client width 375 px（垂直 scrollbar 佔位），device scale factor 1；IAB 輸出 375×806 px。比較圖僅為同高視覺判讀，未把密度差誤判為版面差。
- 狀態：深色、股票 3376 新日興、2026-08-27、三個當日有效題材、庫藏股進行中；QA 假資料與登入旁路均已移除，未進版控。

## Findings

- 無 P0／P1／P2。
- 已確認字體與層級：正式碼維持既有 Manrope 數字／系統中文字體；名稱、價格、78 分、次要欄位層級清楚，小型活躍題材不搶價格與 Decision Header。
- 已確認間距與版面：公司資訊不再堆在名稱下方；390 px 無頁面水平溢位；一級 tab 以既有橫滑容器容納八項，點「基本資料」會捲到選中項；三 section 共用一張連續面板與分隔線，沒有 card-in-card 或內部分頁。
- 已確認顏色與 tokens：未新增色票；活躍題材使用既有 `--warn`，題材／公司 icon 使用既有 `--accent-2`，台股紅漲綠跌與深色對比不變；狀態皆有文字，不只靠顏色。
- 已確認影像與 icon：沿用既有 Trever Radar 品牌圖與 Lucide icon；沒有新增 raster placeholder、手刻 SVG、emoji、漸層或假資產。
- 已確認 copy／資料語意：名稱區只稱 `eligible + active + heat_date=quoteDate` 為「活躍題材」；題材 section 的每一筆分類以連續列保留 name/status、分類日、來源更新日與來源連結，缺值明示「資料未提供」。完整面板仍保留集團鑽取、MOPS 事實與舊 JSON 缺欄位說明。
- mock 中右側 OHLC 摘要與 bottom sheet 是未採用的視覺細節；前者不在本輪使用者要求，後者已被使用者明確改成「基本資料」一級 tab，屬意圖內差異而非 regression。

## 互動與回歸驗證

- `基本資料` tab：`aria-selected=true`，panel 具 `role=tabpanel`／`aria-label=基本資料`。
- 公司資料／題材／庫藏股三個 heading 均可見，沒有同名內部分頁；題材 section 可見「分類日」與「來源更新」，來源連結僅在資料帶有 `source` 時才出現，畫面文字為「查看來源」，完整 URL 保留在 href、title 與 aria-label。
- 頁面 `scrollWidth === clientWidth === 375`，無水平溢位。
- K 線與基本資料切換後內容正確；選中 tab 會捲入手機 viewport。
- Codex 內建瀏覽器乾淨來源（localhost:3001）console errors/warnings：0。
- `npx tsc --noEmit`：通過。
- 獨立 `verify-mobile-stock.mjs` 因工作站未安裝 `playwright` 套件未執行；它從 `iPhone 13` device descriptor 動態輸出 viewport，避免硬寫尺寸。等價的核心手機檢查已由內建瀏覽器實際執行。

## Comparison history

1. 第一輪用 URL query 暫時繞過本機登入，造成 QA harness 自身 hydration mismatch；這不是正式碼錯誤，但不接受為驗收證據。
2. 改為 build-time、僅本機的 QA 環境開關並換到乾淨 origin；重新捕捉後 console 為 0，390 px tab／面板／overflow 驗收通過。
3. 最終程式移除所有 QA 開關與假資料；只留下產品 UI、測試與本報告。

## Follow-up polish

- P3：一級 tab 已達八項，手機需橫滑；目前沿用既有隱藏 scrollbar 並在點擊時自動捲入。若未來再新增分頁，應先合併既有內容，不再擴張 tab 數。

final result: passed
