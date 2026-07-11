# 19 UI/UX 規範(前端改版必讀)

> **日後任何前端頁面新增/改版,動手前必讀本檔 + `docs/07_frontend_pages.md` 對應章節,並逐步讓既有頁面對齊本規範**(不強制一次性重構,但新改的區塊必須合規)。
> 若任務涉及首頁/個股/分點/自選的資訊架構、功能合併或閱讀順序,再讀 `docs/25_ui_information_architecture_plan.md`;本檔管視覺/互動規則,`docs/25` 管任務流與頁面層級。

## 1. 設計系統現況(不可翻案的既定事實)

- **OLED 深色為預設主題**。所有語意色 token 定義在 `web/app/globals.css`:shadcn 語意 token(`--background`/`--card`/`--muted` 等,dark 區塊為預設值)+ 品牌延伸 token(`--ink-2`、`--line`、`--border-strong`、`--up`、`--down`、`--warn`、`--r-lg` 等)。**不引入新配色**,新元件一律引用既有 token。
- **紅漲綠跌**(台股慣例,不可反轉成美股配色):`text-up` / `text-down`(對應 `--up: #e66767`、`--down: #0ca30c`);KChart 動態 innerHTML 用 bare class `.up`/`.down`。
- **技術棧**:Tailwind CSS v4 + shadcn/ui(底層 `@base-ui/react`),既有元件慣用 arbitrary value 引 token(如 `text-[color:var(--ink-2)]`)。
- **數字一律 `.num`**(Manrope,`font-variant-numeric: tabular-nums`):價格、金額、百分比、張數都要,否則跳動時寬度抖動。
- **圖示一律 `lucide-react`**(stroke 1.8),**不用 emoji**;品牌 logo mark 例外(手刻 SVG,見 `web/components/Icons.tsx`)。
- 進場動畫慣例:`animate-[fadeUp_0.35s_ease_backwards]`(keyframe 在 globals.css);全域已有 `prefers-reduced-motion: reduce` 一刀切關閉動畫。

## 2. 本專案採用的 ui-ux-pro-max 關鍵規則

1. **對比**:內文文字對背景 ≥ 4.5:1(muted 文字只用於輔助資訊,不承載關鍵數字)。
2. **觸控目標 ≥ 44px**:可點列/按鈕 `min-h-11`;視覺小的 icon 按鈕用外擴 hit area(如 `h-11 w-11` + 負 margin)。
3. **條圖/橫條與文字分欄不重疊**:條的寬度只能在自己的「條軌」容器內縮放,數值文字放獨立 grid 欄位,永不被條侵入(2026-07 資金流向面板踩過的雷)。
4. **動畫 150–300ms、只用 `transform`/`opacity`**(條長變化用 `scaleX`,不用 `width`);必須 respect `prefers-reduced-motion`(全站已全域處理,勿用 JS 動畫繞過)。
5. **色彩不作唯一訊號**:漲跌/流入流出除了紅綠,必帶 +/-、↑/↓ 或文字(如 vs20 徽章寫「量能+96%」)。
6. **行動優先**:斷點 375 / 768 / 1024 / 1440;手機單欄堆疊時,DOM 順序 = 視覺閱讀順序(不用 `order-*` hack,無障礙 reading order 才正確)。
7. **下鑽必有返回/收合路徑**:展開面板要有明確關閉按鈕(X)+ 再點一次原列可收合;`aria-expanded` 標注狀態。
8. **文字截斷**:固定欄寬的名稱用 `truncate` + `title` 屬性保留全文。
9. **游標與回饋**:可點元素 `cursor-pointer` + hover 底色(`hover:bg-secondary`);選中態用 `bg-secondary` + inset ring(`shadow-[inset_0_0_0_1px_var(--border-strong)]`)。
10. **空狀態要有教育性**(承 docs/07 §6):說明「為什麼是空的」而非只顯示無資料;載入中優先骨架屏而非 spinner。
11. **SVG 不用 emoji**(同上 lucide 規則);資料日期標注(「分點資料:7/4」)避免誤以為即時。

## 3. 對齊策略

- 新頁面/新元件:直接照本檔實作。
- 改既有頁面:順手把**被改到的區塊**對齊本檔(觸控高度、truncate、動畫屬性…),不擴大改動範圍。
- 與 `docs/07_frontend_pages.md` 衝突時:資訊架構以 07 為準,視覺/互動細節以本檔為準。
