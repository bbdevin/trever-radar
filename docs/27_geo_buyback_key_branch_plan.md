# 27 地緣券商 + 庫藏股分點 + 追蹤分點同買 → 口袋名單(2026-07-12 規劃)

> **2026-08-27 規劃治理更新**：本檔既有 G0–G4 歷史規劃與已完成 G1/G2/G4 實作備註仍保留；公司地址／題材 freshness／集團／庫藏股 KB1／關鍵分點 E2 的最新分期、契約與人工確認門檻，改以 [`docs/37_company_theme_group_buyback_branch_plan.md`](37_company_theme_group_buyback_branch_plan.md) 為準。KB2 明確不實作。

> **2026-09-04 更名記錄**:本檔原本把口袋 badge `K1_KEY_BUY`(「有在追蹤或高可信度分點買超」)與「關鍵分點」這個詞混用,而「關鍵分點」在本專案已經是另一件事的專屬名稱——**per-stock、依價格分位判定的常低買高賣**(見 `docs/04` §4、`docs/13`、`branch_stock_pctile_counts` / `BranchPctilePanel.tsx`)。這件事目前**只有一個不下斷言的證據面板**,尚未有任何徽章使用「關鍵分點」這個名字,因為標籤再現率只有 1.6–5.4%,且決定該面板是否留下的樣本外檢定電池尚未在還原價上重跑(見 `docs/STATUS.md`)。
>
> 為了讓「口袋 badge = 有量的追蹤買超」和「關鍵分點 = 低買高賣」這兩件不相干的事不再共用一個名字,badge 已更名:`K1_KEY_BUY` → `T1_TRACKED_BUY`,UI 標籤「關鍵分點」→「追蹤分點」(呼應 `tracked_branches` 表與 `BranchTrackView.tsx` 既有的「追蹤分點」用語)。**「關鍵分點」自此是保留名稱,目前產品中沒有任何東西使用它**;下文歷史小節(§2「K1_KEY_BUY 關鍵分點同買」等)保留原文供沿革參考,實際程式碼/wire 欄位以本更新為準。

> 使用者需求原話:地緣=「公司在高雄、都是高雄(甚至同區)的券商分點在買」;要整理出哪些股票有地緣買/地緣賣,疊加「題材熱門」「追蹤分點(如富邦新店/凱基信義)同買」等多重理由,呈現成**口袋名單**;另要顯示**庫藏股是哪個分點在執行**。
> 本檔把 docs/13 一直卡在「人工名單」的地緣/追蹤分點改為**演算法判定**(人工名單降級為種子/補充)。實作依 docs/17 流程;所有新訊號遵守 docs/20 解耦原則——**只產生 tag/badge,不進綜合分**(Shadow,待 Phase 3 績效證據後再議加權)。

## 1. 資料層(三個新來源,全免費官方)

| 資料 | 來源(G0 需實測端點與欄位) | 更新頻率 | 新表 |
|---|---|---|---|
| 公司地址(縣市/行政區) | TWSE OpenAPI `t187ap03_L` 上市基本資料 + TPEx 對應(上櫃) | 週 | `company_profiles(stock_id, address, city, district)` |
| 券商分公司地址 | TWSE/證期局公開「證券商總、分公司基本資料」(含代號、名稱、地址) | 月 | `broker_branch_geo(broker_id, branch_name, city, district, address)` |
| 庫藏股買回公告/執行 | MOPS `t35sc09` 官方 redirect→舊站 HTML（出表日） | 手動、未排程 | `buybacks(plan_id, stock_id, board_date, start_date, end_date, planned_shares, executed_shares, …)` |

**關鍵匹配問題(G0 驗收重點)**:我方 `branch_trades` 有 `broker_id`(BHID)與 `branch_name`(如「凱基-三多」)——與官方分公司資料的代號/名稱做映射,回報**匹配率**;匹配不到的分點列清單人工補對照。

## 2. 演算法(門檻皆 V1 起始值,待績效校準)

### G1_GEO_BUY 地緣買(G2_GEO_SELL 鏡像)
前置正規化:公司與分點地址 → 縣市 + 行政區。
- **地緣圈定義**:非雙北公司 = 同縣市;**雙北公司 = 同行政區**(台北是金融中心,全國資金都經過,放寬到縣市會全是噪音)。
- **排除集**:券商總公司分點(全國性資金)、外資系分點(美商高盛等,無地緣性)、可維護的噪音分點小名單(如知名網路下單聚集點)。
- **觸發(近 20 交易日窗)**:①地緣圈內 ≥2 家不同券商的分點出現在買超前15;②地緣淨買合計 ≥ 期間成交量 0.5% 或 ≥ 期間前15大總淨買 25%;③至少一家地緣分點連買 ≥3 日。三者皆滿足 → tag。
- **強度**:weak/strong 依(家數 × 佔比)分兩級;badge 帶「N 家地緣分點/佔量 x%」人話理由。

### KB_BUYBACK 庫藏股(只保留可核驗事實)
- `KB1_BUYBACK_WINDOW`(**事實**):只在 MOPS `completed_flag=N` 且 `start_date ≤ as_of ≤ end_date`（含邊界）標示「庫藏股買回期間」。`Y`＋合法期間=completed、逾期 N=expired，其餘=unknown；不以公告日或分點資料推測。
- `KB2_BUYBACK_BRANCH`：**不實作／從 backlog 移除**。公開分點資料不足以證實「某分點就是公司庫藏股執行分點」，不得以淨買超反推成 UI 事實或疑似執行分點；最新 E1/E2 分期見 `docs/37`。

### K1_KEY_BUY 關鍵分點同買
- **關鍵分點集合** = `tracked_branches` 手動種子(富邦-新店、凱基-信義等,docs/13 §2a 已有)∪ `branch_rankings.rank_score ≥ 70`(演算法可信度,**已建成**——「常低買高賣」正是可信度分數的買點分位+勝率構成)。
- 觸發:近 5 日任一關鍵分點淨買 ≥ 該股成交量 0.3% 或 ≥ 500 張(取寬);badge 列出分點名(最多 3 個)。

### H1_HOT_THEME 題材熱門
- 股票所屬題材位於當日資金流入榜(`vs20 ≥ 1.15`)前 10 → tag,badge 帶題材名。重用既有 themes 資料,零新抓取。

### 口袋名單(reason stacking)
- **Reason families**:GEO / TRACKED(2026-09-04 前為 KEY,見上方更名記錄)/ BUYBACK / THEME / ARMED(既有)/ CONC(集中度躍升,既有)——每 family 至多計一次。
- `pocket_score = 30·GEO + 30·TRACKED + 15·BUYBACK + 15·THEME + 10·(ARMED∨CONC)`——**僅供口袋名單排序,不進 daily_scores.final**(解耦鐵律)。
- **入榜**:≥2 個不同 family → 口袋名單;全部 badge 疊加顯示 + 每個 badge 的人話理由(docs 原則:不能只有分數)。

## 3. UI(沿用既有版式,不新開一級路由)

- 首頁狀態池群新增「**口袋名單**」tab(與 Armed/Triggered 並列):卡片 = 既有 StockCard + **reason badges 列**(地緣buy 藍綠系?——用既有 token 決定;追蹤分點=星;庫藏股=盾;題材=火;最多顯示 4 個 +N);排序 pocket_score。
- 個股頁「訊號摘要」區(F3 已建)併入這些 tag 的人話理由。
- /branch 分點追蹤視角:分點列若屬「追蹤分點」或「地緣分點(對某股)」補小徽章。
- 誠實限制常標:分點≠單一人;地緣為統計推測;**KB2 已作廢且不顯示**。

## 4. 工作包

| WP | 內容 | 依賴 | 估時 |
|---|---|---|---|
| G0 PoC | 三個資料端點實測(欄位/頻率/授權)、分點名稱↔官方分公司**匹配率報告**、雙北噪音統計 | 無,**隨時可做** | 半天 |
| G1 資料層 | ✅ **完成 2026-08-20**:`company_profiles` + `broker_branch_geo` + `import-geo`(週一 14:10);庫藏股無 OpenAPI,**buybacks 延後**不阻塞 GEO | G0 | 1 天 |
| G2 地緣+關鍵+題材演算法 | ✅ **完成 2026-08-20**:`pipeline/radar/pocket.py` 純函式 + export `pocket_tags`/`lists.pocket`(不進 `daily_scores.final`);G4 才做首頁 tab | G1;**地緣涵蓋度依賴每日分點池廣度**(500 檔池偏熱門股;docs/26 WP-M2 全市場池後中小型股地緣才完整——先做可用,標注涵蓋限制) | 1.5 天 |
| G3a 庫藏股來源與 KB1 | ✅ 2026-08-27：官方 MOPS `ajax_t35sc09` redirect→ephemeral `mopsov` HTML；加性 schema／atomic import／point-in-time export／KB1／個股事實區與 fixture tests。**`import-buybacks` 與排程未執行；16:58 `export-json`／data Worker deploy 已發布既有快照，未更新庫藏股官方來源資料** | 只接受 1–366 日 bounded date range；任一市場／欄位／出表日失敗零資料寫入 | code 完成 |
| G3b KB2 | `KB2_BUYBACK_BRANCH`（疑似執行分點） | **不實作**；不得新增 code/schema/export/UI | — |
| G3c 關鍵分點 E2 | `branch × stock` point-in-time **獨立** buy／sell episode 分位與 buy 後價格描述；不做交易獲利歸因，buy→sell 配對另案 | ✅ **唯讀 shadow CLI／JSON contract 完成（2026-08-27）**；buy→sell 配對規則／coverage 未定；未跑正式 DB、未接 UI、未定門檻；schema／歷史回算仍待人工確認，見 `docs/37` §7 | shadow contract 完成 |
| G4 口袋名單 UI | ✅ **完成 2026-08-20**:首頁「口袋」tab + StockCard/個股頁 badges + `/branch` 關鍵分點徽章;零新色票。GEO 資料仍等回補結束後 `import-geo` | G2(G3 可後補) | 1.5 天 |

## 5. 優先序建議

- **G0 隨時可跑**(純調查,不動管線)。
- G1-G4 建議排在:VPS 回灌穩定之後;與 docs/26(7a)關係——**不互斥可先行**,但地緣涵蓋度在全市場每日池(26 WP-M2)之後才完整,badge 需標「目前僅涵蓋每日評分池」。
- 具體位置由使用者定(STATUS 併入時預設放 7a 之前或之後皆可)。

## G0 調查結果(2026-07-12 已完成 ✅,零 DB 寫入)

### 端點狀態

| 資料 | 端點 | 結果 |
|---|---|---|
| 上市公司地址 | `https://openapi.twse.com.tw/v1/opendata/t187ap03_L` | ✅ 1,089 筆,`住址` 欄存在(2330=新竹科學園區力行六路8號) |
| 上櫃公司地址 | `https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O` | ✅ 891 筆,`Address` 欄存在;合計 1,980 ≈ 全市場 |
| 券商分公司 | `https://openapi.twse.com.tw/v1/opendata/OpenData_BRK02` | ✅ 812 筆:證券商代號/名稱/地址/電話;**名稱格式即「統一-三多」,與我方 branch_name 同慣例** |
| 券商總公司 | `https://openapi.twse.com.tw/v1/brokerService/brokerList` | ✅ 64 筆(Code/Name/Address) |
| 庫藏股 | TWSE OpenAPI **無端點** | ⚠️ 待深挖:候選 = MOPS 查詢頁(POST/HTML)或 data.gov.tw 資料集;KB 工作包 +0.5 天前置 |

### 關鍵發現(G1 設計依據)

1. **MoneyDJ 的 `broker_id`(BHID)是母券商層級代碼**(如 9A00=永豐金全體),**不是**分公司代碼 → 分點級匹配走**名稱正規化 join**(去空白/全形、台↔臺),BHID 僅用於券商層級歸戶。
2. **實測匹配率(2476,2026-07-09 前15大買+賣 30 列)**:名稱匹配 22/30;未匹配 8 個**全部是總公司/外資**(美林/摩根士丹利/瑞銀/摩根大通/康和/新光/元大/永豐金總部)——即**分公司級 22/22 = 100%**,且總公司/外資自然落入 brokerList → **排除集有現成資料基礎,不用人工維護大名單**。
3. **地緣假設當場驗證**:2476 鉅祥(高雄公司)當日前 15 大即含玉山-左營、華南永昌-鳳山、永豐金-高雄 3 家高雄分點。
4. 正規化注意:①官方名稱偶有內嵌空白(「合庫- 台中」);②地址台/臺混用;③**科學園區地址不含縣市**(新竹科學園區…)→ G1 需園區→縣市小對照表;④2330 類權值股前15大以外資總部為主,地緣訊號天然稀薄(符合預期,演算法主戰場是中小型股)。

### G1 設計修訂(依 G0)

- `broker_branch_geo` 以**正規化名稱**為 join key(唯一性 G1 驗證,同名衝突列出人工裁決);總公司/外資自動歸入排除集。
- `company_profiles` 匯入時做縣市/行政區抽取 + 園區對照 + 台臺正規化;抽取失敗者標 null(fail-safe:不判地緣)。
- 庫藏股資料源深挖為 G1 first task(找不到穩定免費源則 KB1/KB2 延後,不阻塞 GEO/KEY/THEME)。

## G2 實作備註(2026-08-20)

- **Shadow**:`pocket_tags` / `pocket_score` / `lists.pocket` 只在 export;不寫 `daily_scores`、不改 `final`。
- **涵蓋**:地緣/追蹤只用已抓到的前 15 大分點(每日評分池);`radar.json.pocket_note` 標明。抽不到縣市或雙北缺行政區 → 不判地緣。
- **強度 V1**:`strong` = ≥3 家地緣券商且(佔量 ≥1% 或佔前 15 淨買/賣 ≥40%),否則 `weak`。
- **口袋入榜**:≥2 個 family(GEO/TRACKED/THEME/ARMED/CONC;BUYBACK 待 G3),`pocket_score` 權重見 §2,最多 40 檔。

## G4 實作備註(2026-08-20)

- 首頁狀態池「口袋」tab 讀 `lists.pocket`(已按 pocket_score 排序);可切分數/題材分組,與綜合榜同一套卡片牆。
- badges 走既有 `ReasonPill` token:`G1`/`G2`/`T1`(2026-09-04 前為 `K1`)=籌碼青+圖釘/星,`H1`=權證琥珀+火。卡片最多 4 個 +N;個股頁 F3 顯示人話全文。
- `/branch` 排行卡:`rank_score ≥ 70` 或 `source=manual` 標「追蹤」(2026-09-04 前標「關鍵」)。**未做**「地緣分點對某股」徽章(排行 JSON 沒有個股對照,避免另開 export)。
- 空榜教育文案用 `pocket_note`;誠實限制:統計推測、分點≠單一人、目前僅每日評分池。

## G3a E1 實作備註(2026-08-27)

- 官方請求契約：POST `https://mops.twse.com.tw/mops/api/redirectToOld`，`apiName=ajax_t35sc09`，參數 `TYPEK=sii|otc`、ROC `d1/d2`、`RD=1`、`encodeURIComponent=1`、`step=1`、`firstin=1`、`off=1`；redirect 與短效 HTML GET 都帶 browser User-Agent、`Referer=https://mops.twse.com.tw/mops/web/t35sc09`。只允許官方 HTTPS `mops.twse.com.tw`／`mopsov.twse.com.tw` redirect URL。406、缺 URL、網路／JSON、非官方 URL、無有效表、欄數漂移或無法取出 `出表日`（也相容 `出表日期`）均 fail closed。
- HTML 只用 Python stdlib `html.parser`；多個 `hasBorder` table／重複表頭會去重，但任一可識別資料列欄數漂移即拒絕。正式 20 欄固定為序號、代號、名稱、董事會日、目的、金額上限、預定股數、價格下／上限、起／訖日、完成 flag、KB1 link（忽略）、已執行／取消或轉讓股數、執行率、執行金額、均價、已發行股數占比、未完成原因。民國日期轉 ISO；空白／nbsp／`--` 不補 0。MOPS 沒有 `announce_date`，程式與 JSON 不捏造該欄位。
- 單位固定：股數=股、金額=元、價格=元/股、百分比=百分點。計畫 ID 以 market、公司、董事會日、期間、預定股數、價格與目的做 deterministic SHA-256，可保留同股多次計畫。
- `python -m radar import-buybacks --as-of YYYY-MM-DD --days 365` 是**人工手動 CLI**，`--days` 限 1–366（實際相差最多 365 日）；上市、上櫃都成功且有效後才在同一 transaction upsert。任一市場失敗只寫 `import_logs` error，既有 `buybacks` 零變動。
- 個股 JSON 僅輸出 export 資料日當下 active plan，且 `report_date` 與 `source_updated_at` 都必須不晚於資料日；舊 DB／舊 JSON 缺 `buyback` 安全 fallback。個股頁只呈現狀態、期間、預定／已執行股數、價區、目的、MOPS／出表日，不稱「執行分點」。
- **`import-buybacks` 未執行、未排程、未改 workflow/secrets；16:58 `export-json`／data Worker deploy 已發布既有快照，未更新庫藏股官方來源資料。**

## VPS 待辦:import-geo 等回補結束(2026-08-20 使用者確認)

分點回補(`backfill-branches`)與權證分點回補(`backfill-warrant-branches`)還在跑時,**不要**手動 `python -m radar import-geo`。

- `import-geo` 只寫 `company_profiles` / `broker_branch_geo`,不會覆蓋回補進度。
- 但仍與回補搶同一份 `radar.db` 寫鎖,有 `database is locked` 風險。
- 回補結束後再跑(然後 `export-json` + `wrangler deploy`);或不手動,等下週一 14:10 `daily-market.sh` 自動 `import-geo`。

## 6. Reviewer 必查

1. 所有新 tag 是否 Shadow(不進 final/tech_score/branch_score)?
2. KB2 是否維持**完全不實作**（不得只靠「疑似」字樣包裝推測）?地緣是否標統計推測?
3. 雙北是否用行政區級判定 + 排除集是否落實?
4. 新 importer 是否遵守禮貌抓取與 import_logs 記錄慣例?不動 WAL/workflow 續存鏈?
5. 匹配不到官方地址的分點是否 fail-safe(不判地緣,而非誤判)?
