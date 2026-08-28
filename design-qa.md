# 個股首屏 UI — Design QA（2026-08-28）

## 狀態：正式站通過

- 視覺真相：`C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\exec-731ce944-fae2-471d-bab4-ed6d2e2f0a94.png`（853×1844）。
- 正式站深色首屏：`C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\stock-ui-55beda9-dark-top.png`（390×844）。
- 正式站淺色首屏：`C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\stock-ui-55beda9-light-top.png`（390×844）。
- 正式站基本資料：`C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\stock-ui-55beda9-basic.png`（390×844）。
- 比對方式：同一個視覺輸入同時檢視參考圖與正式站深色首屏；正式站網址為 `https://radar.techtrever.com/stock?id=3376`，commit `55beda9`。

## Findings

- 無 P0／P1／P2。名稱與價格／漲跌同行，長名稱使用截斷、價格區不換行；正式 DOM 量測 `rowOverflow=false`、頁面無水平 overflow、初次載入 `scrollY=0`。
- Decision Header 改為預設收合，保留大分數與第一條判讀；展開／再次收合均可用，收合後第一條判讀仍在。這比前一版預設展開更接近參考圖的首屏資訊密度。
- 行情摘要由六張小卡整併為一張 `dl`；公司概況為單列。參考圖右欄行情在 390px 改為下方卡片，是窄螢幕的既定 responsive 差異。
- 參考圖的 bottom sheet 已依使用者覆寫為「基本資料」一級 tab，位於「技術」左側；實際觸控概況後 `scrollY=0`、selected=`基本資料`，可見公司資料／題材／庫藏股三個 heading。
- 活躍題材只接受 `eligible && status=active && heat_date=quoteDate`，最多 2+N。本次 3376 正式資料沒有符合條件的當日項目，因此不渲染題材 chips，沒有以舊題材補畫面。
- 深色與淺色均沿用既有 tokens、Lucide icon、台股紅漲綠跌及 44px touch target；淺色首屏重新載入後無 overlay、無水平 overflow。使用者原本的深色偏好已恢復。
- 手機分頁置中曾發現 `scrollIntoView` 會讓初次載入垂直偏移 189px；已改為只調 tablist 的水平 `scrollLeft`，正式站複驗 `scrollY=0`。

## 驗證

- `npx tsc --noEmit`：通過。
- GitHub Actions `deploy`：commit `55beda9` 的 Next build 與 Cloudflare Pages deploy 通過。
- `git diff --check`：通過。
- Luna High 唯讀 review：APPROVE，無 blocker。
- 獨立 `verify-mobile-stock.mjs`：已固定 375×812，覆蓋頁首、同列、重疊／溢位、順序、Decision 展開／收合、概況跳轉與 BasicInfo；工作站未安裝獨立 `playwright`，故本輪未直接執行此腳本，改以已登入正式站做等價 DOM／觸控／深淺色驗收。

final result: passed
