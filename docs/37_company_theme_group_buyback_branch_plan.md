# 37 公司資訊／題材／集團／庫藏股／關鍵分點整體規劃

> 版本：2026-08-27（S4 V2／Armed A1 後續）
> 本文件把本輪 Confirmed Scope 與實作狀態永久化，供下一個 Executor／Reviewer 接續。A／B／C／D 的程式契約已完成；**C 尚未在正式 VPS 執行 import/export**，E 仍為規劃，且本文件不授權正式資料回算、VPS migration 或部署。

## 0. Confirmed Scope 與現況

| 工作包 | 本輪決定 | 狀態／門檻 |
|---|---|---|
| A1 | Armed／Triggered／Extended／Faded 匯出契約補強：state ID 可由 `radar.stocks` 解析；stale warrant 不作今日 state source；缺 1 日或 5 日漲跌時 fail closed | **程式與測試完成**；未正式 DB 回算 |
| A2 | 對齊策略、首頁狀態、綜合分、strategy metadata 與績效勝率的定義 | **程式／契約與測試完成（2026-08-27）**；已對齊綜合榜同分排序，不調整 `final` 權重、分點績效排行 V2、schema 或正式回算 |
| B | 個股名稱下方增加公司地址與股務代理；以官方來源與 additive export contract 為準 | **程式／fixture／UI／typecheck／正式 build 完成（2026-08-27）**；正式 VPS `import-geo`／`export-json` 未執行 |
| C | 題材資料分為公司題材分類、近期熱度、有效／停用／過時狀態，顯示「近期可能相關題材」而非無證據的因果宣稱 | **程式／fixture／UI／typecheck／正式 build 完成（2026-08-27）**；正式 VPS import/export 未執行，不改綜合分 |
| D | 集團名稱可點入 `/group?id=`，顯示版本化的集團成員股票 | **程式／fixture／UI／typecheck／正式 build 完成（2026-08-27）**；正式 VPS export 未執行 |
| E1 | 庫藏股官方來源 PoC 與 **KB1 事實標籤** | 規劃中；來源穩定性需驗證 |
| E2 | `branch × stock` point-in-time 統計，建立可驗證的關鍵分點（低買、高賣／後續表現）描述 | 高風險規劃；需人工確認 schema／歷史回算 |

### 明確排除

- **KB2 `BUYBACK_BRANCH` 不實作**：無法由公開資料證實「某分點就是公司庫藏股執行分點」，不可用分點淨買超反推並在 UI 呈現為事實；`docs/27` 的舊 KB2 規劃以本文件為準作廢。
- E2 **不做交易獲利歸因**：分點×個股資料只能產生 point-in-time 的事件後價格結果與描述性統計，不能宣稱分點實際獲利、持倉成本或單一帳戶績效。
- 不因 B/C/D/E 調高 `daily_scores.final`、`tech_score`、`branch_score`，不另增第 14 策略；新資訊先維持 tag／badge／shadow。
- 不在本輪執行正式 `radar.db` 全市場重算、回灌、資料刪除／重建、VPS destructive 操作、workflow／secrets／DNS 變更或 force push。

## 1. 共通資料與契約原則

1. 所有來源欄位要帶 `source`、`source_updated_at`（或可判斷的資料日）與 freshness；抓不到或解析失敗就顯示未知，不猜測補值。
2. 匯出 JSON 的新增欄位採 additive、可選欄位與明確 null 語意；前端必須能處理舊快照，不能把缺值當 0 或當成「沒有」。
3. 理由文字必須能回到來源與計算窗；「近期熱門」與「可能題材」不是因果證明，UI 要標註資料日及統計推測。
4. 既有 `adj_factor`、VPS 單一寫者、`docs/20` 的策略／分數解耦原則不變。
5. 先以 fixture／shadow export 驗證，再由人類決定 migration、正式回算與部署；migration 後必須補 rollback／資料完整性檢查方案。

## 2. A2：策略、首頁狀態與勝率定義對齊

A2 是語意決策關卡，不是單純修 UI。Executor 先產出對照表與測試，不自行改規則。

### 2.1 必須對照的單一定義

| 層 | 要固定的問題 | 驗收方式 |
|---|---|---|
| 策略 | S1–S13 與 S4 V2 的 signal、phase、status（Active／Shadow／Retired）各自代表什麼 | `docs/04_signal_rules.md`、純函式與 strategy metadata 對照；golden fixtures |
| 首頁狀態 | Quiet／Armed／Triggered／Extended／Faded 的必要條件、優先順序、缺值行為與同日邊界 | `derive_radar_state` contract test；每一 state 至少一個正例與反例 |
| 綜合分 | `daily_scores.final` 的門檻與風險扣分是否仍是榜單篩選口徑 | 不改分數前先產現況報告；任何新權重需人類另確認 |
| 策略績效 | signal 日期、episode 去重、entry、forward horizon、成熟樣本與 win 的口徑 | 以完整交易日曆及 point-in-time fixture 重播，不使用未來資料 |
| 分點績效 | branch event、次日開盤 entry、5 日結果、成熟樣本與隔日沖標記的差異 | 明確分離 `events_count`／`matured_samples`，先 shadow diff |

### 2.2 勝率單一定義（A2，2026-08-27；不改統計公式）

- 策略勝率：每一個已去重且已成熟的 signal episode，以次一交易日可得的還原開盤作 entry；在指定 horizon 的還原收盤報酬 `> 0` 才算 win。未成熟事件進 events count，不進勝率分母。
- 分點勝率：每個分點×個股的進場事件，以次一交易日開盤作 entry，第 5 個有效交易日的還原收盤報酬 `> 0` 算 win；前 15 大分點裁剪與樣本不足必須在 UI 誠實標註。
- 這些是目前程式／文件的稽核基準，不是對外保證的「預測勝率」。若要採用成熟樣本門檻、隔日沖最低樣本或排行 V2，必須另開人工確認並更新 schema／回算計畫。

### 2.3 A2 本輪落地契約（2026-08-27）

- **綜合榜**：唯一來源是 `daily_scores.final`；只列 `final >= 65`（最多 40 筆 JSON 顯示窗），不足 15 筆保持實際數量。沒有「低分保底」或隱藏補位，也不改 `final` 權重與風險扣分。
- **S12**：`buy_concentration >= 15%`、有正的 `concentration_avg20` 且達其 `1.5×`，並維持原有 1／5 日漲幅限制。基期缺值或 `<=0` 不能證明躍升，一律 fail closed；只影響未來計算，未作正式 DB 回算。
- **首頁狀態**：Quiet = `state=null`；Armed／Triggered／Extended／Faded 仍完全由 `derive_radar_state` 的同日、缺 1／5 日報價 fail-closed 契約決定。策略（含 S4 V2 phase）不會成為 state 來源，沒有改動狀態門檻或優先序。
- **策略生命週期**：`strategy_meta[code]` 必含 `status / effective_date / rationale / decision_ref / version`。現行 S2、S5 = Retired；其餘 = Shadow；無 Active。Retired 不進主策略選擇器，僅在明確「歷史資料」展開區可讀；`strategies` 與 historical reason code 維持相容。缺少這個 additive metadata 的舊 JSON 必須顯示原本所有策略。
- **勝率**：策略 win = 已去重、已成熟 signal episode 的指定 horizon 還原報酬 `>0`；分點 win = branch×stock 進場事件、次一有效交易日還原開盤 entry、第五根有效交易日還原收盤報酬 `>0`。兩者均不是對外預測承諾；分點 `events_count / matured_samples` 與排行 V2 仍是另案 shadow／人工確認項。

## 3. B：公司地址與股務代理（個股詳細頁）

### 資料與來源 PoC

- 上市公司：TWSE `t187ap03_L`；上櫃公司：TPEx `mopsfin_t187ap03_O`。先確認地址欄位、更新頻率、代號覆蓋率與空值比例。
- 股務代理欄位需先從同一批官方公司基本資料／公開資訊來源驗證欄名與穩定性；若官方資料未提供，不以爬蟲猜測，改呈現「官方資料未提供」並記錄來源缺口。
- 建議 additive 欄位：`company_profiles.address / city / district / transfer_agent / source / source_updated_at`。正式 migration 前須檢查目前 schema 與既有 upsert 行為。

### Export／UI／測試

- 個股 JSON 增加可選 `company_profile`；名稱下方的 compact company information 顯示地址與股務代理，缺值顯示「資料未提供／待更新」，不佔用 Decision Header 的訊號層。
- 桌機與手機都維持單行截斷＋展開完整地址；不新增色票，沿用現有 token、icon、tooltip 與深色／淺色對比規則。
- 測試官方欄位 mapping、上市／上櫃、缺值、舊 JSON 相容、XSS／長地址截斷；前端加 static export／typecheck。

### 本輪實作紀錄（2026-08-27）

- `company_profiles` 採 additive 欄位：`industry_code`、`transfer_agent`、`transfer_agent_phone`、`transfer_agent_address`、`source`、`source_updated_at`；`init_db()` 對既有 SQLite 只補欄、不刪資料。**沒有對正式 VPS DB 執行此程式。**
- TWSE/TPEx provider 只解析已驗證官方欄位；空字串轉 `null`、產業碼維持字串前導 0、民國 `1150826` 正規化為 `2026-08-26`。
- 個股 JSON 增加可選 `industry` 與 `company_profile`；舊 snapshot 缺欄位時 UI 顯示「資料未提供」，不將缺值視為 0 或不存在。

## 4. C：題材完整化

### 定義

- `company_themes`（公司所屬分類）與 `theme_heat`（近期資金／漲跌／廣度）分開；沿用既有 `import-themes` 與首頁 `themes`，不把熱度倒灌成公司永久分類。
- 每個題材至少帶 `source`、`source_updated_at`、`status`（active／stale／retired）與資料日。過時分類只降級或標示，不直接刪除歷史。
- 「可能正在反映的題材」只能由題材關聯＋近期熱度門檻產生候選，例如資金流 `vs20`、上漲廣度與成交金額；文案使用「近期熱門／可能相關」，不可寫成「股價因該題材上漲」的確定因果。

### UI／驗收

- 個股頁顯示「公司題材」與「近期熱門題材」兩層；首頁熱力圖維持唯一主要入口，避免新增 `/explore` 平行路由。
- 題材卡片提供資料日、熱度構成與停用標籤；點入可看題材成分股，仍沿用現有 StockCard、ReasonPill 與語意色彩。
- fixture 覆蓋新鮮／過時／無熱度／多題材排序；確認 C 不改 `final`，舊快照可讀。

### 本輪實作紀錄（2026-08-27）

- `themes` 保留既有 `source`／`updated_at`，只增 `source_updated_at`／`data_date`／`status`；既有 SQLite 由 runtime additive migration 補欄，**未對正式 VPS DB 執行**。`status=null` 代表舊資料狀態未知，前端不得猜成 active。
- `import-themes` 先暫存所有分類；只有未使用 `--limit`、分類清單非空、每一分類皆成功且成員非空，才交易式寫入並標為 `active`。partial／empty／來源失敗／`--limit` 一律保留既有分類與成分、降為 `stale`；不根據來源缺列自動標 `retired`，既有 retired ID／成分也不因完整來源回應而自動復活。TTL 為 35 日，逾期資料保留並在 export 顯示 stale。
- `radar.json.themes` 保留既有欄位，additive 輸出 lifecycle／`heat_date`；同名題材 ID 的當日、歷史與產業子題材聚合一律以 `(name, stock_id[, date])` 去重。資料日晚於 quote 的 membership 仍保留在個股分類並顯示 stale，但完全排除當日熱度、子題材與 freshness 日期。每檔 JSON 新增 `company_themes` 與 `recent_theme_heat`；舊 DB 仍可輸出分類但 `status=null`，舊 JSON 缺欄位時 UI 明示「狀態未提供」。
- H1 門檻與 `pocket_score` 不變，但只接受 `status=active`、分類資料日不晚於報價日、且熱度日等於報價日的既有題材熱度候選。stale／retired／未知或未來資料均不產生新的 H1。
- 個股頁以既有 token 與 Lucide 呈現「公司題材」及「近期可能相關題材」；後者只在上述日期／狀態都成立時顯示，否則明示僅供分類參考。未新增主導航或路由。

## 5. D：集團股與可追溯 mapping

- **本階段版本控管邊界**：D 的集團成員 mapping 必須是 repo 內、可 code review 與可追溯版本的 YAML／JSON fixture（實作包先固定檔案路徑與格式）；`company_groups` 只是這份 versioned mapping／export contract 的概念名稱，**不是既有或本階段要新增的 DB table**。本階段不建 DB／schema migration、不寫入正式資料，亦不進首頁主導航或任何分數；未來僅能以個股頁 badge 的 `/group?id=` 深連結作為鑽取入口。
- 先建立來源 PoC：每一個集團 mapping 必須有 `group_id / group_name / stock_id / effective_from / effective_to / source / source_updated_at`；不確定或僅市場俗稱的關係標 `unverified`，不冒充官方關係。
- 建議以版本化 `company_groups`（或等價 additive JSON）承載成員，不把集團名稱硬編碼在前端；歷史日期要能避免把今日成員回寫到過去。
- 個股頁的集團 badge／連結導向 `/group?id=<group_id>`；集團頁只列當前有效成員、代號／名稱／今日摘要與資料日，成員仍可回個股頁。
- 先做 mapping fixture、無成員／一股多組／失效成員、路由 query 與 static export 測試；來源不穩定時只上線明確人工維護的 seed，不開放無證據的自動推斷。

### 本輪實作紀錄（2026-08-27）

- mapping 固定為 repo 內 `pipeline/radar/data/company_groups.json`（version 1），不建 DB table、不寫入分數或主導航。
- 只加入華新麗華集團官方頁可核驗 seed：anchor `1605`，成員 `2344`／`2492`／`5469`／`6116`；來源為 `https://www.walsin.com/about-us/who-we-are/subsidiaries-affiliates/`，`source_updated_at` 與 effective dates 為 `null`，`observed_at=2026-08-27`。未加入佳邦等未充分驗證項目。
- exporter 產出 additive `groups.json` 與每檔 `company_groups`；成員摘要直接由 `stocks + daily_prices` 的最新可用報價建立，非 radar pool。mapping validator 覆蓋未知股票、null 日期與無效有效期間；正式 VPS export 尚未執行。

## 6. E1：庫藏股（只做可證實的 KB1）

1. 先 PoC 公開資訊觀測站或可核驗官方資料：公告日、買回期間、預定張數、已執行張數、狀態、來源 URL／資料日與代號匹配率。
2. `KB1_BUYBACK_WINDOW` 只表示「公告買回區間內」這個可核驗事實；所有未能取得官方執行明細的欄位為 null。
3. Export 以 `buyback.status / start / end / planned_lots / executed_lots / source / source_updated_at` 為可選契約；UI 用「庫藏股公告／買回期間」呈現，不能顯示執行分點。
4. 來源不穩定、需要 CAPTCHA／登入或無法回溯資料日，就停在 PoC，不因想要完整化而使用非官方推測。
5. KB2 永不加入實作 backlog；任何 future agent 若看到舊文件的 KB2，必須以本文件與 `docs/27` 的不實作決議為準。

## 7. E2：關鍵分點與地緣券商完整化（shadow、非獲利歸因）

### 關鍵分點定義

- 種子來源可包含 `tracked_branches` 與已累積的 branch ranking，但「常低買高賣」必須由 point-in-time 事件驗證：買入事件的價格分位偏低，且在預先固定的後續窗出現可觀察賣出／價格結果。
- 統計至少分離：事件數、成熟事件數、低買比例、後續正報酬比例、賣出配對覆蓋率、資料涵蓋率；樣本不足顯示 unknown／insufficient，不補成 0。
- 不把分點視為單一人或單一帳戶，不計算「分點實際交易獲利」。`fwd_return` 是事件後價格結果，不是 branch P&L。

### 地緣券商

- 既有 `company_profiles` 與 `broker_branch_geo` 先維持 Shadow；雙北採行政區，其餘採同縣市，地址抽取失敗即不判定。前 15 大分點裁剪與目前每日評分池覆蓋率必須在 UI 標註。
- G1/G2 既有 tag 不進綜合分；完成全市場涵蓋前，不可把地緣 badge 解讀成全市場結論。

### Point-in-time 與高風險門檻

- 每個 as-of 日只能使用該日以前可取得的 branch、價格、地理 mapping 與 ranking；mapping 後來修正不能回寫歷史事件。
- 先做 shadow export／diff 報告，觀察排行漂移、樣本成熟度與缺資料比例；人類確認後才可設計 schema migration、全歷史回算與 VPS 正式資料更新。
- 測試 future-leak、交易日缺口、未成熟事件、分點缺列、地緣地址 null、跨券商同名與前 15 大截斷。

## 8. UI／UX 共通驗收（沿用 `ui-ux-pro-max` 規範）

- 不新增平行一級路由：公司資料、題材、集團、庫藏股先掛個股樞紐；集團只有必要的 `/group?id=` 鑽取。
- 沿用既有深色預設、台股紅漲綠跌、現有 semantic tokens、Manrope／數字欄、Lucide icon、響應式卡片與 accessible tooltip；不得以顏色作唯一狀態訊息。
- 每一個統計徽章都有資料日、來源／freshness 與可展開的人話理由；空狀態要解釋「資料不足」而不是暗示不存在。
- UI 只呈現已驗證的事實／shadow 標籤；「推測」「可能相關」「樣本不足」必須是可見文案。

## 9. 執行順序與人類確認點

1. **已完成**：A1 程式／測試與契約驗收；保留正式 DB 未回算狀態。
2. **已完成**：A2 策略／首頁／勝率對照、綜合榜嚴格門檻與同分排序、S12 基期 fail-closed、strategy lifecycle v1；未作正式 DB 回算。
3. **已完成**：B（官方公司欄位／additive import-export／個股 UI）、C（題材 lifecycle／H1 fail-closed／個股 UI）與 D（版本化華新麗華 mapping／groups export／鑽取 UI）程式、fixture、typecheck 與正式 build。**未執行正式 VPS import/export 或正式 DB 寫入**。
4. **E1**：庫藏股來源穩定性 PoC → KB1 contract → code／schema proposal；KB2 維持不實作。
5. **E2**：point-in-time shadow 統計與覆蓋率報告；人類確認後才進 schema／歷史回算。地緣既有 tag 可與 E2 分開驗證，不等待「全市場」才做資料品質報告。
6. 每一個實作包完成後更新 `handoff.md`、`docs/STATUS.md` 與本文件／對應規格，跑相關 tests、lint、typecheck，再依專案規則 commit／push；正式 DB／VPS／migration 另取人類明確確認。

## 10. 交接驗收清單

- [x] A2 程式契約／對照表與測試完成（2026-08-27）；正式 DB 回算、排行 V2／schema 與任何新門檻仍須另取人類確認。
- [x] B 官方地址與股務代理欄位、來源、空值語意與 additive contract（2026-08-27；typecheck／正式 build 通過；正式 VPS import/export 未執行）。
- [x] C 題材分類與近期熱度分層，過時題材可見且不進分數（2026-08-27；targeted／完整 pytest、typecheck、正式 build 通過；正式 VPS import/export 未執行）。
- [x] D 集團 mapping 有版本、來源與 `/group?id=` static export contract（2026-08-27；typecheck／正式 build 通過；正式 VPS export 未執行）。
- [ ] E1 只輸出可核驗 KB1；KB2 未出現在 code、schema、export、UI。
- [ ] E2 通過 point-in-time／future-leak／成熟樣本檢查，且文件明確沒有交易獲利歸因。
- [ ] 所有正式回算、schema migration、VPS 寫入與部署均有獨立人工確認紀錄。
