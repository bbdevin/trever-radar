# 22 Armed 狀態追蹤(2026-07-10 規劃定案;2026-08-20 Extended/Faded 程式落地)

> 本文件記錄使用者於 2026-07-10 確認納入待開發的產品方向:
> 用「雷達狀態」追蹤**籌碼/權證已進駐但股價尚未發動**與**已發動/強勢續追**,
> 取代再加第 14 策略或第 7 個近似榜單。
>
> **狀態(2026-08-20)**:
> - ✅ A1–A2 Armed/Triggered 已上線(export + 首頁 tab + 卡片徽章)
> - ✅ A3 一鍵加入今日 Armed(自選,見 docs/23 F1.3)
> - ✅ **Extended / Faded 同日近似**(export `derive_radar_state` + `lists.extended`/`lists.faded` + 首頁「追高風險」「失效」tab + 卡片徽章)。**正式站需等下次 VPS `export-json`** 才有新 list;前端已相容空陣列。
> - 延後:進駐天數精算(`armed_days`)、跨日狀態持久、門檻依績效校準
>
> 既有 Python + SQLite + 靜態 JSON + Next.js 架構不翻案。不新增策略 code、不抬綜合分。

> **S4 V2 邊界（2026-08-27）**：壓縮蓄勢／壓縮突破是既有 S4 策略家族的 phase tag，
> 不可視為 Armed/Triggered 來源；不得寫入 `lists.armed`、`lists.triggered` 或改動
> `derive_radar_state`。其 phase lists 僅存在於 `strategy_phases` additive JSON 契約。

## 1. 為什麼要做

現行中心是綜合分與多榜競賽(綜合/熱門/爆量/強勢/權證/13 策略)。
使用者真正要的是**狀態機追蹤**:

| 要盯的狀態 | 現有近似物 | 缺口 |
|---|---|---|
| 籌碼進駐、股價未動 | S12、B3 集中度 | 散在策略 tab,無統一「未發動池」 |
| 權證先動、標的未漲 | 04 §1 W3、權證榜 | 未組成可追蹤清單 |
| 權證分點異動 | `/branch` 權證大戶 | 證據弱(造市/避險),不得當確定「大戶」敘事 |
| 已強勢續追 | 「強勢」榜(當日漲幅) | 不是「由未發動轉發動」的延續狀態 |
| 持續盯 | `/watchlist` 手動 ★ | 不會因籌碼事件自動進池 |

**定案方向**:不做新評分權重、不開新路由帝國;重用既有 S12 / W3 / B3 / 權證倍數 /
`watch_price`/`stop_price`,在首頁與自選組成狀態視圖。

## 2. 狀態模型

```
Quiet（無訊號）
  → Armed（籌碼/權證進駐,價未動）     ← 最高價值,主追蹤池
  → Triggered（價量發動）             ← 由 Armed 轉強,取代純漲幅「強勢」主敘事
  → Extended（已漲一截,追高風險）
  → Faded（籌碼撤退或失效）
```

### 2.1 Armed(尚未發動)

滿足**任一**即可進池,並標來源徽章:

| 來源 | 條件(起始值,可校準) | 對齊既有規則 |
|---|---|---|
| `branch` | 買方集中度躍升(B3)且近 5 日漲幅偏低 | S12 / B3 |
| `warrant` | 認購金額倍數 ≥1.5 且標的當日漲幅 < 3%(且 5 日累漲門檻對齊 W3) | 04 W3 |
| `both` | 上兩者同時,或分點分 ≥60 且權證 W1≥2 | 04「類似先行卡位」組合 |

- **高亮優先**:`both` > `branch` > `warrant`(權證單來源假訊號較多)。
- **門檻偏好**:實作前由使用者再選偏嚴(`both` only)或偏寬(其一即可);預設建議偏寬進池、`both` 置頂。
- **必附風險文案**:免費分點前 15 大裁剪、權證可能為發行商造市/避險、隔日沖分點。

### 2.2 Triggered(已發動)

Armed 之後出現帶量突破 / 創 N 日新高(重用 T2),或當日強勢且分點/權證訊號仍在。
**主追蹤敘事**用「由 Armed 轉 Triggered」,不當日漲幅榜當唯一「強勢」定義。

### 2.3 Extended / Faded(2026-08-20 同日近似實作)

純函式:`pipeline/radar/export/json_export.py::derive_radar_state`(單元測試 `pipeline/tests/test_derive_radar_state.py`)。

- **Extended**:`sources` 仍在 + 有風險(`score_risks` 或 tech risks) + 已漲一截(`chg≥7%` 或 `chg5≥12%`,或突破態且 `chg≥5%`/`chg5≥10%`)→ `lists.extended` / 首頁「追高風險」。
- **Faded**:收盤 ≤ `stop_price` 時覆寫為 faded(含仍有 sources 的情況);或無 sources 但當日有評分且觸及失效價 → `lists.faded` / 首頁「失效」。
- **Quiet**:無 state(不另開 tab)。
- **誠實限制**:無跨日狀態表,故非「由 Armed 轉 Faded」的時間序列;進駐天數仍延後。

## 3. UI 最小方案(不新開一級路由)

1. **首頁主 tab「未發動」(Armed)**
2. **次 tab「已發動」(Triggered)**
3. **「追高風險」(Extended) / 「失效」(Faded)**(2026-08-20) — 接在已發動之後;空 list 時前端顯示 0 檔即可。
4. **`/watchlist` = 追蹤工作台** — 手動 ★ 保留;一鍵加入今日 Armed 已做。
5. **`/branch`** — 只做分點工作流;權證分點文案依 `docs/20` 降級為實驗。

**刻意不做**(本文件範圍內):

- 第 14 個策略 code、新綜合分權重、把權證分點納入 `final`
- 新一級導航頁、推播/LINE(無常駐伺服器)
- 地緣/關鍵分點五年擴容(另案)

## 4. 資料契約

原則:SQLite 真相不變;JSON 為產出物。優先在 export 層組狀態,避免大改 schema。

已產出:

- `radar.json` → `lists.armed` / `lists.triggered` / `lists.extended` / `lists.faded`
- 每檔:`state`(`armed`|`triggered`|`extended`|`faded`|null)、`sources[]`、既有 scores / warrant / watch·stop
- 重用:`daily_scores.reasons`(S12 等)、權證彙總倍數、T2、`stop_price`、risks
- **完整性／時效契約（A1 補強，2026-08-27）**：`lists.armed`／`triggered`／`extended`／`faded` 的每一個 ID 都必須存在於 `radar.stocks`（並保留既有 `spark` 等 payload）；不改既有榜單門檻或排序。`warrant_stock_daily` 逐檔取不晚於 quotes 日的最新列；非當日列仍可保留 warrant payload、權證榜排序與 freshness stale 標示，但不得成為當日 `sources` 或單獨產生 state；當日 branch 來源仍可獨立成立。全域 warrant freshness 保留既有 `date`／`stale`，若最新全域日期雖為今日但仍有逐檔舊列，`stale=true` 並 additive 輸出 `partial_stale`／`stale_stock_count`。任一 `chg_pct` 或 `chg5_pct` 缺值時 state 一律 fail closed（含 T2、risk、stop／faded），不以 0 代替。

禁止:為 Armed 新建會膨脹 DB 的歷史大表;禁止未授權改 workflow / 正式 DB。

## 5. 與其他文件的關係

| 文件 | 關係 |
|---|---|
| `docs/20` | B 方案 Phase 完成後的產品下一刀;不取代 B 方案 |
| `docs/21` | Access 已退役;門禁見 WP-B7 / `docs/31` |
| `docs/04` | Armed 條件對齊 W3 / B3;門檻仍是起始值 |
| `docs/07` / `19` | 前端規格與 UI 規範 |

## 6. 實作順序

| 順序 | 內容 | 狀態 |
|---|---|---|
| **A1** | export:`lists.armed` / 來源徽章 / 風險欄 | ✅ |
| **A2** | 首頁「未發動」「已發動」tab | ✅ |
| **A3** | 自選一鍵加入今日 Armed | ✅ |
| **A4** | Extended / Faded 同日近似 + UI | ✅ 2026-08-20(等 VPS export) |
| 延後 | 進駐天數精算、跨日自動失效清單、門檻依績效校準 | 📝 |

## 7. 成功標準

- 打開首頁能在一個池掃完「籌碼或權證進駐、價未動」標的,不必切 13 策略。
- `both` 來源可一眼辨識;權證單來源不宣稱「主力卡位」。
- 強勢追蹤主敘事是 Armed→Triggered;Extended/Faded 可從主池旁路掃讀。
- 未新增策略 code、未抬高綜合分、未新開一級路由、未納入 `final`。

## 8. 給 Executor 的固定起手式

1. 讀 `AGENTS.md`、`project-context.md`、`STATUS.md`、`docs/20`、本文件。
2. 改 export 狀態機時同步單元測試與前端 `ListKey`/`state` 型別。
3. 不在回補進行中對正式 `radar.db` 跑 export;程式可先合 main,等空檔再 deploy 資料。
