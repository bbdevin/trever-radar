# 個股首屏 UI — Design QA（2026-08-28）

## 狀態：待視覺 QA／目前 blocked

本輪以 `C:\Users\user\.codex\generated_images\01a03d9a-24c3-79a3-9c9c-fdb3ce75cba6\exec-731ce944-fae2-471d-bab4-ed6d2e2f0a94.png` 為結構參考，已完成程式與手機 verifier 的檢查點調整，但**尚未取得本輪 375px 的實際深色／淺色截圖或執行 Playwright verifier**。因此本文件不把本輪視覺比較標成 passed。

## 本輪實作範圍

- 名稱與股價／漲跌在手機同一主列；代號、市場、產業與嚴格有效的活躍題材 2+N 位於下方。
- 首屏順序為 header → Decision Header → 單一卡片行情摘要 `dl` → 單列公司概況 → tabs。
- Decision 分數以獨立大面積 score block 呈現；第一條判讀即使收合仍可見，展開後既有理由、風險、口袋標籤與觀察／失效價仍保留。
- 行情由六個小卡收斂成單一卡片低邊框 `dl`；概況改為單列並會切至既有「基本資料」。
- tab 順序不變：K線／籌碼日報／三大法人／資券／大戶／基本資料／技術／權證；選中項會捲入手機 viewport。
- 基本資料仍是公司資料／題材／庫藏股連續三 section；地址、股務、官方來源、題材 lifecycle／來源、庫藏股 MOPS 事實與集團鑽取全保留。

## 待完成驗收

- [ ] 375px 深色：名稱／價格同列、活躍題材在產業下方、首屏順序及 Decision 層級。
- [ ] 375px 淺色：文字、琥珀 chips、漲跌語意與分隔線對比。
- [ ] 375px：無水平 overflow；概況點入基本資料；八個 tab 的 active 捲入。
- [ ] Decision 收合／展開：首要判讀留在收合態，完整內容仍可取得。
- [ ] 768px 以上：行情 `dl`、概況單列、header 與 tab 不破版。

## 阻塞原因

工作站沒有獨立 `playwright` 套件；`web/scripts/verify-mobile-stock.mjs` 已更新但尚不能在此直接執行。本輪不得以舊截圖或舊 QA 結果替代新的視覺驗收。
