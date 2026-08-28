# 個股頁 browser annotation — Design QA（2026-08-28）

## 狀態：待正式站視覺 QA

本輪視覺目標是使用者在正式 3376 個股頁留下的三個 annotation，並延續既有參考圖 `C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\exec-731ce944-fae2-471d-bab4-ed6d2e2f0a94.png`：

1. 行情摘要移到首屏右側，與 Decision Header 左右並列。
2. 移除重複的 compact 公司概況列。
3. 多題材集中呈現；status、日期、來源等缺值欄位不渲染。

## 已完成程式契約

- 行情右欄含資料日、量、額、昨收、開盤、最高、最低；名稱／價格同行與 Decision 預設收合不變。
- 首屏不再有 `stock-overview`；基本資料仍由一級 tab 進入。
- 題材為 compact chips／rows；來源存在時題材名稱是 44px 連結，缺值不顯示 fallback 文案。
- `verify-mobile-stock.mjs` 已同步左右欄、行情欄位、無概況列、題材缺值收斂與來源 touch target。

## 待驗收

- [ ] 正式站 390×844 深色：左右欄不擠壓、資訊可掃讀、無水平 overflow。
- [ ] 正式站淺色：文字、邊框、紅綠語意與題材連結對比。
- [ ] Decision 展開／收合後右側行情定位穩定。
- [ ] 基本資料題材集中呈現，沒有重複「資料未提供／狀態未提供」。
- [ ] 參考圖與最新正式站截圖在同一視覺輸入比較，無 P0／P1／P2。

final result: blocked
