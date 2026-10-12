# 51 權證分點：左買右賣、持有成本與帳面估算 `wpos-avgcost-v1`

> 版本：2026-10-12（Planner+Executor：Fable）。決策來源：使用者 2026-10-12「權證分點的 UI 我想要優化……分成左邊買超 右邊賣超……這個分點買的權證位置對應現股的平均價格多少……粗估現在賺多少……如果有一個大戶買了很多錢在這個股票的權證 如果現在賠很多 還沒賣 就代表我現在進場成本可以比他低……並優化手機畫面」；同日追加「大戶買進權證也幫我寫日期……兩三天進場也要寫」與「點進去該股票可以直接跳轉到該股票對應的分點權證詳細走勢那個頁籤」。
> 治理前提：`docs/37` §7 2026-10-03 反轉已允許**平均成本法估算**損益（`docs/42` `pnl-avgcost-v1`）；本文件沿用同一套方法與誠實文案，不宣稱帳戶損益、不稱勝率、不給方向。KB2（反推庫藏股執行分點）與本文件無關，維持不實作。
> 程式：`pipeline/radar/compute/warrant_position_est.py`（純函式）、`pipeline/radar/export/json_export.py::_export_warrant_branches`（串流接線）、`web/lib/warrantPositions.ts`、`web/lib/warrantDeepLink.ts`、`web/components/WarrantBranchPanel.tsx`、`web/components/WarrantSplitCard.tsx`、`web/components/WarrantHoldersList.tsx`、`web/app/branch/page.tsx`。測試：`pipeline/tests/test_warrant_position_est.py`、`pipeline/tests/test_warrant_branch_export.py`、`web/lib/warrantPositions.test.ts`、`web/lib/warrantDeepLink.test.ts`。

## 0. 狀態（2026-10-12）

| 項目 | 狀態 |
|---|---|
| MVP-1 左買右賣（個股權證分頁排行；/branch 依標的／依分點卡片） | ✅ 程式完成於分支 |
| MVP-2 每券商 × 標的 × 認購／認售 的仍持有／成本／換算現股均價／帳面估算／進場日 | ✅ 程式完成於分支（分片 `positions` 鍵） |
| MVP-3 全市場「仍持有(估)」篩選清單（`branches/warrant_positions.json` + /branch 第三檢視） | ✅ 程式完成於分支 |
| MVP-4 深連結 `?tab=warrant&branch=` | ✅ 程式完成於分支 |
| 正式 VPS 匯出與體積／耗時量測 | ⏳ 待合 main 後第一輪 export（§6） |
| Phase 2（履約價損益兩平、VWAP 成交價、首頁入口、跨股彙總） | 📝 未授權 |

## 1. 需求拆解與取捨

1. **左買右賣**：使用者要的是「買超一邊、賣超一邊」。三個地方都改：個股權證分頁兩張排行表並排；/branch「依標的」卡內券商列、「依分點」卡內標的列都拆成左欄買超、右欄賣超。
2. **「他的成本」**：分點資料只有張數，沒有成交價；只能用**當日權證收盤**當成交價（與既有「估金額＝張數 × 1000 × 當日收盤」同一把尺，畫面不會出現兩種金額）。把它換算成「現股位置」的最誠實作法是**記下每筆買超當天的現股收盤**並以買超金額加權（§2.3），而不是履約價反推——履約價反推需要 `exercise_ratio` 單位確認（§7）。
3. **「現在賺多少／賠多少」**：仍持有張數 × 最新權證收盤 − 仍持有成本，平均成本法（與 `docs/42` 相同，不另創 FIFO 口徑）。
4. **「篩出還沒賣、賠很多的大戶」**：全市場清單只列**仍持有成本 ≥ 500 萬**且**還有持有**的券商 × 標的，依帳面由差到好；發行商／同券商自家權證過半的列排除（造市／避險不是「大戶看法」）。文案只陳述事實：成本、帳面、進場日、現股相對換算均價的位置；不寫「成本比他低就該進場」。
5. **進場日**（追加）：平均成本法沒有先進先出，所以「仍持有的是哪幾天買的」定義為：每次賣超把**每一個買超日的剩餘張數等比例縮小**（§2.4）。≤ 3 天逐日列，更多列起訖與天數、點開展開。
6. **深連結**（追加）：`/stock?id=X&tab=warrant&branch=券商名`，沿用個股頁 `?tab=` 慣例；開權證分頁、換到含有這家券商的區間、選中它（K 線副圖＝它的逐日權證進出）、捲到切換列、底下就是它的持有估算卡與逐檔明細。不在資料裡 → 小提示、排行照常。

## 2. 指標定義（`wpos-avgcost-v1`）

輸入：`branch_trades`（權證代號為 6 碼、標的為 `stocks.type='stock'`、非指數）近 120 個交易日每列 `(券商, 權證, 日期, 淨張數)`，`warrant_daily.close`（當日權證收盤）、`daily_prices.close`（當日標的收盤）、`warrants.kind/maturity_date/name`。資料日 `as_of` = 分片的 `data_date`（不晚於報價日的最大權證分點日）。

### 2.1 一腿 = (券商, 權證)，平均成本法

- `net > 0`：`cost += net × close × 1000`、`pos += net`；同時 `under_num += 金額 × 當日標的收盤`、`under_cost += 金額`（標的收盤未知就不進這兩個累加）。
- `net < 0`：`sold = min(|net|, pos)`；`frac = sold / pos`；`realized += sold × close × 1000 − cost × frac`；`cost、under_num、under_cost` 各乘 `(1 − frac)`；`pos −= sold`；`|net| − sold` 記為「找不到對應的買超」（不放空）。
- 任一有交易的日子沒有權證收盤 → 整腿 `cost_unknown`，不列入任何估算（與 `docs/42` 同規則）；排行金額仍照既有契約以 1.0 計。

### 2.2 估值狀態

| 狀態 | 條件 | 進持有／成本 | 進帳面 |
|---|---|---|---|
| `valued` | 持有 > 0 且最後價存在 | ✓ | ✓ |
| `expired` | `maturity_date < as_of` | ✓ | ✗（到期後價值由結算決定，不假裝） |
| `no_price` | as_of 當日或之前 **5 個交易日內**沒有收盤 | ✓ | ✗ |
| `closed` | 持有 = 0 | ✗（只留已實現） | ✗ |
| `cost_unknown` | 交易日缺權證收盤 | ✗ | ✗ |

`unrealized = Σ(valued 的 pos × last × 1000) − Σ(valued 的 cost)`；`unrealized_pct = unrealized ÷ cost_valued × 100`（分母只用估得出值的成本，畫面有註記）。

### 2.3 換算現股均價

`avg_under = Σ(買超金額 × 當日標的收盤) ÷ Σ 買超金額`，賣超後等比例扣減所以不變。跨同標的多檔權證以**仍持有成本**加權合併。它是「買的那幾天現股在哪」，**不是**履約價算出的損益兩平點（文案鎖定 `WPOS_UNDER_NOTE`）。畫面同時給「現股 X，較換算均價低／高 y%」——只陳述位置。

### 2.4 進場日（仍持有部分）

每腿維護 `(日索引, 張數÷S, 金額÷S)` 三個平行串列與縮放因子 `S`：買超追加（同日合併），賣超只把 `S *= (1 − frac)`（O(1)，不逐筆改），出清清空、`S` 歸 1。跨權證依日期合併後**最大餘數法**取整：先各取 floor，餘數依小數部分由大到小（平手取較早的日子）各加 1，所以 `Σ 張數 = 仍持有張數（取整後）`；分不到 1 張的日子**併入**前一個有張數的日子（第一天就併入下一天），不丟；成本各自四捨五入後把差額補到最後一天，`Σ 成本 = 仍持有成本`（測試釘住：買 3+3 賣 3 → [2, 1]，不是 [2, 2]）。文案鎖定 `ENTRY_NOTE`：「進場日列的是仍持有的部分：平均成本法沒有先進先出，每次賣超把每個買超日的剩餘張數等比例縮小。」

### 2.5 認購／認售／牛熊

方向相反，永遠分開：每個 (券商, 標的) 輸出 `{call, put}` 兩塊（沒有那一邊就沒有鍵）。**牛熊證（bull/bear/bull_ext/bear_ext）不進持有估算、不進篩選清單**；逐日序列維持 main 的語意（只有認購進第 1 欄、認售進第 2 欄，牛熊是 0 但那一天仍有一列）——`test_bull_bear_rows_keep_main_daily_semantics_byte_for_byte` 把分片 `daily` 與 main 的查詢結果 `json.dumps` 逐位元比對。排行列第二行與篩選清單預設看認購，認售另切。

### 2.6 發行商／同券商

沿用 2026-10-02 的 `_warrant_issuer_group`（權證簡稱 2 字發行商）× `_branch_broker_group`（分點名的券商段）判定，2026-10-12 補**明確的別名表**（`json_export._ISSUER_TO_BROKER`、`_BRANCH_HEAD_ALIASES`、`_BRANCH_COUNTRY_PREFIX_RE`，測試 `test_issuer_alias_table`）：麥證→麥格理（分點「港商麥格理」）、法興→法國興業（「法商法國興業」）、匯豐→匯豐（「港商匯豐」）、國泰綜合→國泰、台北富邦→富邦，國別前綴（港商／法商／美商／英商／新加坡商／瑞士商／德商／荷商／日商／澳商／加商／韓商）先剝掉；解不出發行商 → 不算自家（不猜）。每塊 `self_cost`；篩選清單排除 `self_cost / cost ≥ 50%` 或「總公司席位且有任何自家持有」，排除筆數**每種各自**在 `excluded_self`，畫面摘要句說出來。

### 2.7 缺權證收盤的腿

任一交易日沒有權證收盤 → 整腿 `cost_unknown`：**連買超／賣超張數都不進該塊的總計**（否則卡上「買超 N 張」與持有對不起來），只計 `n_cost_unknown` 並在註記說「N 檔有交易日缺權證收盤價，整檔不列入估算」。

## 3. 畫面（手機優先，390px 驗證）

### 3.1 個股 → 權證 → 「權證分點進出」

- 排行：`買超最多｜賣超最多` 兩張表**左右並排**，手機也是兩欄（名稱截斷、滑鼠停留全名，代號欄只在桌機）；每列第二行「持有(估) 850萬 · −12.0%」（手機兩欄各約 165px 所以極短；認購優先，沒有認購持有才顯示認售；沒有持有不佔行）。桌機左欄由 17rem 加寬到 26rem。
- 選中券商後、K 線下方新增 **「券商 · 權證持有（估算）」卡**：認購／認售各一塊——`仍持有(估) N 張`、成本(估)、權證均價、換算現股均價、帳面估算（大字帶號 + %，估值）、「現股 X，較換算均價低 y%」、**進場日**（≤ 3 天逐日「進場 09/15 120 張 · …」，更多「09/02 起 共 8 天，最近 10/07」點開逐日：日期 · 張數 · 成本 · 當天現股）、買超／賣超對應／已實現／最後買超日、條件註記（到期、無價、部分估值、找不到對應的賣超、自家發行占比）、「怎麼算」收合、頁尾聲明。
- 手機順序：切換券商 → K 線 → 註記 → **持有估算卡** → 搜尋＋左右排行 → 逐檔明細。
- 深連結：`?tab=warrant&branch=` 由 `WarrantBranchPanel` 讀（§1.6）；區間順序 5日→30日→120日→2日→1日 找第一個含有它的。

### 3.2 /branch → 權證分點異動

- 「依標的」「依分點」卡片改用 `WarrantSplitCard`：標題列（淨額）＋左「買超」右「賣超」兩欄（各自合計），點一列在兩欄下方全寬展開逐檔權證（手機兩欄太窄放不下）；每列右側「›」直達個股權證分頁並選中該券商。
- 第三個檢視 **「仍持有(估)」**（`WarrantHoldersList`，點了才抓 `warrant_positions.json`）：認購／認售切換（各自一份清單）、帳面門檻（不限／−10％／−20％／−40％ 以下，預設 −20%）、排序（帳面 %／帳面金額／持有成本／最近買超）；每張卡：券商、標的（連結＝深連結）、帳面估算、仍持有張數、成本、換算現股均價、進場日一行、現股相對位置、未估值檔數、自家發行占比；摘要句「N 筆符合（檔內只保留帳面最差的前 400 / 共 M 筆…）；另有 X 筆自家發行占過半未列」（截斷訊息只在真的截掉時出現）；區間列在此檢視收起（固定看 120 日）。
- **網址狀態**（返回鍵不丟）：`/branch?tab=warrant&view=holders&wk=put&wpct=0&wsort=cost`——分頁、檢視與篩選用 `history.replaceState` 寫進 query（`lib/urlState.ts`；預設值不寫），掛載後讀回。
- 排行列第二行的百分比分母是估得出值的成本；只估到一部分時標「(部分)」。

### 3.3 文案守則

禁用：勝率 獲利 報酬 關鍵分點 大漲 噴 極品 機率 目標價 買進 賣出 看多 看空 將會 有效支撐 壓力沉重 做多 做空 建議 喊單 套牢（`warrantPositions.test.ts` 以字碼組字檢查，避免 `test_label_honesty.py` 掃到字面）。中性用語：「帳面估算 +X／−X」「估算成本」「仍持有(估)」「進場 MM/DD N 張」「找不到對應的買超」。

## 4. 篩選清單契約 `branches/warrant_positions.json`（v2）

```
{ version: 2, definitions_version: "wpos-avgcost-v1", data_date, window_from,
  min_cost: 5000000, max_rows_per_kind: 400,
  kinds: { call: Bucket, put: Bucket } }
Bucket = { rows: Row[], total, excluded_self }
  // rows = 門檻內（仍持有 > 0 且成本 ≥ 500 萬）帳面 % 由差到好的前 400 列（估不出值的排最後）；
  // total = 門檻內全部筆數；前端在 total > rows.length 時寫「檔內只保留前 N / 共 M 筆」。
Row = { branch_name, underlying_id, underlying_name, kind, lots, cost, n_held, n_unvalued, self_pct,
        cost_valued?, value?, unrealized?, unrealized_pct?, avg_under?, last_buy_date?, first_date?, buy_days?,
        under_last?, under_last_date? }
```

v1（認購認售混排、全體 `[:300]`）已作廢：一個 9 億的認售部位會被認購擠掉、估不出值的列會消失。前端 `normalizeScreening` 只收 v2。

分片 `warrant-stock-details/{id}.json` 新增可選鍵：

```
positions: { version, as_of, window_from, under_last?, under_last_date?,
             branches: { 券商: { call?: Agg, put?: Agg } } }
Agg = { lots, cost, buy_lots, sell_lots_attributed, sell_lots_unattributed, realized,
        n_warrants, n_held, n_expired, n_no_price, n_cost_unknown, self_cost,
        avg_under?, cost_valued?, value?, unrealized?, unrealized_pct?, last_buy_date?, first_date?,
        buy_days: [[date, lots, cost, under_close|null]],      // 最多 20 天（張數最大的），日期遞增
        buy_days_rest?: { n, lots, cost, first, last } }       // 第 21 天起併成一段；Σ(buy_days)+rest = 仍持有
```

（逐檔權證的 `warrants[]` 明細 2026-10-12 拿掉：前端沒讀、每塊多數百 B、正式機分片數萬塊。）`Row` 同樣帶 `buy_days` / `buy_days_rest?`。缺鍵 = 舊分片（前端不出現持有估算）；舊前端讀新分片不受影響（多出的鍵不讀）。前端：≤ 3 天且沒有其餘 → 逐日一行；否則「MM/DD 起 共 N 天，最近 MM/DD」（N 含其餘、起訖取兩邊）點開逐日，最後一列「其餘 N 天合計 X 張 · 成本 Y（起–訖）」。

## 5. 計算位置與成本

**前提（verifier 2026-10-12 於 VPS 實測）**：120 個交易日窗口（2026-04-17 起）有 **4,884,497** 列權證分點列；VPS 1.7 GB RAM（可用約 1.15 GB）＋1 GB swap，曾經 OOM。`warrants` 表 kind：call 94,828、put 10,802、bull 81、bear 89、bull_ext 59。第一版（088ef0a）的 Python 逐列串流在 1.15M 合成列上 +123 MB／+11 s（約 107 B/列），外推 490 萬列 ≈ +520 MB／+45 s，**不可接受**；重寫如下。

- **逐日序列**：維持 main 的 SQL `GROUP BY (券商, 標的, 日期)` 查詢（逐字相同），Python 只看分組後的列。
- **持有估算**：另一條查詢，**只取分片裡的 (標的, 券商)**（Python 端過濾；原本的 `TEMP TABLE _wpos_pairs` JOIN 已移除，見 §5.2）、只取 `kind IN ('call','put')`，`GROUP BY (標的, 券商, 權證, 日期)`（同腿同日的多列先合併）、`ORDER BY` 同序，用 DBAPI cursor 迭代 tuple。
- **串流處理**（`PositionStream.consume`，單一迴圈、區域變數、一列一次方法呼叫）：列依 (標的, 券商, 權證, 日期) 到來，所以一腿處理完就併進該 (標的, 券商) 的累計器、一組處理完就定稿、**換標的時整檔 `branches` 立刻 `json.dumps` 成一段字串**（dict 丟掉；分片寫檔時用佔位字串原文替換）。篩選摘要只留 scalar tuple（進場日等前 400 列定案後才從該檔字串解回）。進場日每塊最多 20 天（§2.4 cap）。常駐記憶體 = 每檔一段 JSON ＋ 摘要 tuple ＋ 一腿＋一組，**與列數無關**；賣超用縮放因子 O(1)。`under_close` 一份共用，只載分片裡的標的。
- 其他查詢：`warrant_daily` 近 5 日最後收盤、`warrants` 主檔——小表。
- 體積：分片每家券商約 300–600 B（含 `buy_days`，無逐檔明細），熱門標的 60 家 ≈ 20–40 KB；`warrant_positions.json` 每種 ≤ 400 列 ≈ 100–250 KB，點「仍持有(估)」才抓。
- **量測**：見 §5.1。

### 5.1 量測（2026-10-12，本機 Windows，`_export_warrant_branches` 整段，main `8bc317f` vs 本分支）

合成 DB：`tools/make_synthetic_branch_db.py --stocks 400 --days 130 --branches 40 --warrants-per-stock 50`（窗口內 5,099,247 列權證分點列、801 個分片）。兩種情境：

| 情境 | 進持有估算的列數 / 配對 | main 牆鐘 | 本分支牆鐘 | 差 | 持有估算段（`wpos:` log） | tracemalloc 峰值 main → 本分支 |
|---|---|---|---|---|---|---|
| **最壞**：所有 (券商, 標的) 都過 100 萬門檻（每腿天天有交易） | 4,719,036 列 / 15,730 對 | 109.9 s | 145.4 s | **+35.5 s** | 56.9 s（SQL 掃描＋GROUP BY ≈ 35 s，Python ≈ 18 s；輸出 JSON 34.9 MB） | 1,741.8 → 1,815.3 MiB（**+73.5 MiB**；砍重複扁平 `under_close`、`WarrantInfo` slots 之前是 +82.5） |
| **較接近正式**：1/7 的券商有量，其餘縮 100 倍 | 707,606 列 / 2,358 對 | 86.0 s | 96.0 s | **+10.0 s** | 15.5 s（輸出 JSON 5.2 MB） | 未量（輸出僅 5 MB 等級） |

- 第一版（088ef0a）在最壞情境外推是 +520 MB／+45–50 s；現在記憶體與列數無關（最壞情境留下的是 34.9 MB 輸出 JSON＋3.1 萬筆 scalar 摘要）。
- **記憶體達標（+73.5 MiB ≤ 80）、時間在最壞情境未達（+35.5 s > 15）**：+35.5 s 之中約 35 s 是第二次 SQL 掃描＋GROUP BY（與 main 自己的逐日 GROUP BY 同量級，是「多一條查詢」的固有成本，TEMP 表 JOIN 在所有配對都入選時剪不掉任何列）；Python 端 ≈ 18 s（4.7M 列，≈ 3.8 µs/列）。+73.5 MiB 之中 ~35 MB 是必須寫出的 JSON。較接近正式的情境兩者皆達標。
- 正式 VPS 預期落在兩者之間、偏「較接近正式」：4.88M 列裡只有分片配對的列會被 GROUP BY／送進 Python。上線後第一輪看 `radar-cron.log` 的 `wpos: rows= pairs= stocks= json_kib= summaries= secs=` 一行回填本表；若 `rows` 接近全部 4.9M 或 `secs` > 60，備案是把配對再縮到每檔各區間排行前 N 名（分片只對這些券商出 positions）。
- 時間量測皆未開 tracemalloc（開了會慢 3–5 倍：main 442 s、本分支 571–618 s）；峰值量測另跑一次開 tracemalloc。

### 5.2 正式機第一輪（2026-10-12 21:22 daily-margin）與修正

- `wpos: rows=2167728 pairs=8166 stocks=517 json_kib=7203 summaries=1843 secs=1306.2`：**持有估算段 21.8 分鐘**，整輪 export 21:22→21:59，佔鎖拖慢每一輪。
- 原因（VPS `EXPLAIN QUERY PLAN`）：加了 TEMP 配對表 JOIN 後，SQLite 改成 `SCAN branch_dim` → 逐券商走 `ix_branch_trades_raw_branch(branch_id, date)`——那是全市場（含現股）索引，5 GB 庫上大量隨機讀。合成 DB 小到全在快取裡，所以本機量不出來。
- 修正：拿掉 JOIN，回到與逐日序列同樣的計畫（`SCAN warrants` → `branch_trades_raw` 主鍵），Python 端以 `charted` 過濾。VPS 實測該查詢 **4,783,455 列 34.4 s**（全掃，未過濾）。下一輪看 `wpos:` 回填。

## 6. 待人類／上線後

1. 合 main → VPS 下一輪 export 自動產生 `positions` 與 `warrant_positions.json`；之前新前端讀舊分片只是沒有持有估算段。
2. 第一輪後看 `radar-cron.log` 的 `export timing: … warrant_shards=`（本次未另加計時鍵）與 `du -sh web/public/data/branches/warrant-stock-details`，回填 §5。
3. 抽 3 檔熱門標的對照：排行第二行「仍持有(估)」是否與逐檔明細相符；發行商總公司列是否被篩選清單排除。

## 7. Phase 2（未授權）

- **履約價損益兩平**：`strike ± avg_cost ÷ exercise_ratio`；先在 VPS 確認 `warrants.exercise_ratio` 單位（0.1 = 每張 100 股？）與缺值率，再決定是否顯示。
- **VWAP 成交價**：`warrant_daily.turnover ÷ volume` 取代收盤當成交價（更接近，但會與既有估金額不一致，需一併換）。
- 首頁入口（「仍持有(估)」前 N）、分點頁跨股彙總、更長窗口、手續費模型。
- 進場日展開列加當天權證收盤。
