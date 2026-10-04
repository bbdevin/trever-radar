# 48 — 首頁「多方榜」:選股規則凍結與「上榜隔天」事前登記(bull-board-v1)

> **地位**:§1 是上線中的選股規則(凍結,版本字串 `bull-board-v1`);§2–§6 是事前登記。效力只來自時間順序:本文件 commit 時,**沒有任何人把任何一版多方榜(或其候選規則)與之後的股價 JOIN 過**。§6 逐項揭露凍結前已看過的東西。
>
> **凍結規則**:同 `docs/38` §0、`docs/40` 開頭。本文件 commit 之後,§1 與 §2–§4 的每一個數字、每一條規則、`web/lib/bullBear.ts` 的 rank 表任何一格,都不得在資料可見後修改;要改只能開 v2(版本字串 `bull-board-v2`),而 v2 只能用 **v2 commit 之後才出現的市場日**。
>
> **決策紀錄**:Claude Fable 規劃、使用者 2026-10-04 核准(取代首頁「綜合」分頁)。綜合榜(final ≥ 65)在 54 個評分日只有 8 天真的上榜(各 1 檔)、近 30 日 25 天空;盤中假上榜後消失;65 門檻在資料齊全時幾乎碰不到;改門檻/列出未達門檻已於 09-24 否決。所以整個分頁換掉,不動 65。
>
> **先講清楚**:多方榜**只是排序已發生的事實**——依「今日影響最大的多方事實」的條數排列。它不是預測,畫面上**沒有**任何往後表現的數字。往後表現要等 §2–§5 的檢定通過(SHIP)才會以**次數**顯示;在那之前畫面只寫「名單自 MM/DD 起每日留存;往後表現須累積 60 個交易日並通過事前登記的檢定,才會以次數顯示。」

## 1. 選股規則(凍結;`web/lib/bullBoard.ts`,版本 `bull-board-v1`)

- **母體 U(t)**:`stocks/{id}.json` 的 `scores != null`(評分池,約 740 檔)**且** `candles` 最後一根的日期 == `radar.json` 的 `data_date`。
- **事實**:與個股頁「多空」分頁**同一次呼叫**——`web/lib/bullBearFromStock.ts summaryFromStockJson(data, muted)`(個股頁也呼叫它,畫面逐字不變)。建置器的 `muted` 恆為空集合(全站共用名單的覆寫只在瀏覽器端)。
- **K_bull** = `summary.bull` 中 `section ∈ {tech, chips}`、`rank ≥ 4`、**沒有** `date`/`dataDate`(不是滯後資料)的項。**K_bear** 同理取 `summary.bear`。
- **排除 E** = `summary.bear` 中 `section ∈ {tech, chips}`、`rank == 5`、沒有滯後的項。**E 非空 → 不入榜**。壓力段(`levels`)不計入 K、也不排除。
- **入榜**:`|K_bull| ≥ 3` 且 `E = ∅`。
- **排序**(payload 不輸出名次):`|K_bull|` 多 → `K_bull` 的不同 `source` 數多 → `|K_bear|` 少 → `turnover` 大 → `id` 字典序。**上限 40 檔,不湊數**(不足 40 就是不足)。
- **卡片內容**(只影響顯示,不影響入榜):多方取 `K_bull` 依 `compareKey`(與「重點」同一個比較)前 3 條;空方取 `topOfSide(summary, "bear")` 一條;段計數取 `sections[sec].bull/bear.length`。
- rank 表(`backendRank`、`web/lib/facts/catalogue.ts` 各 code 的 rank)屬於本規則的一部分:**改任何一格 = 改規則 = v2**。新增事實 code(新 rank 的格子)同樣是 v2。

### 1.1 計算路徑與資料契約

- `web/scripts/build-bull-board.mjs`(Node 22+,`--experimental-strip-types`,跑同一份 TS,**不移植 Python**):讀 `radar.json` → 逐檔讀 `stocks/*.json`(一次一檔)→ `summaryFromStockJson` → `buildBullBoard`(純函式)→ 原子寫 `bull_board.json`(`.tmp` → rename)→ 追加一行到 `data/bull_board_log/YYYY-MM.jsonl`,並把當月檔複製到 `web/public/data/bull_board_log/YYYY-MM.jsonl`(使用者核准的異地副本)→ 印 `bull-board timing: files=… universe=… qualified=… elapsed=…s`。CLI:`--data <dir> --log <dir>`。
- `bull_board.json`:`{version:"bull-board-v1", data_date, generated_at, radar_generated_at, log_from, universe, qualified, min_bull_key:3, inputs:{insti:{date,stale}, branch:{…}, margin:{…}, holders_week}, entries:[{id,name,market,industry,close,chg_pct,turnover,final,state,bull_key_n,bear_key_n, bull:[{code,source,section,text,segments}]×≤3, bear:{code,source,section,risk,text,segments,date}|null, counts:{tech:{bull,bear},chips:{…},levels:{…}}}]}`。**不輸出** `rank`/`magnitude`/`score`/`position`(形狀鎖在 `bullBoard.test.ts`)。entries 的陣列順序就是 §1 的排序,畫面不顯示第 N 名。
- **族群欄位(2026-10-04 追加,只影響顯示,不屬 §1 凍結規則)**:entries 每項多一個選用鍵 `theme:{name,vs20}|null`。建置器以 `web/lib/themeGroups.ts hottestListedTheme(radar.stocks[].themes, radar.themes)` 算——與首頁「題材」排序(WP-H1)同一個最熱題材挑法,但只從今日題材資金流(`radar.themes`)上有的題材裡挑;一個都不在上面 = `null`。首頁「事實｜族群」切換的族群檢視(`groupBoardEntries`,純函式)依 `theme` → `industry` → 「其他」分組:族群依檔數多 → 族群內最前面那檔的原順序,「其他」最後;族群內維持 entries 原順序;標頭顯示檔數與「成交為20日均 X 倍」(題材取 `theme.vs20`、產業查 `radar.sectors`)。兩種檢視上方都有一列「多方集中」族群分布膠囊(`groupSummary`):同一個分組與順序取前 6 個有名字的族群,其餘(含「其他」)併成「其他」放最後;點膠囊切到族群檢視並捲到該組。缺 `theme` 鍵的舊 `bull_board.json` 由畫面從 `radar.json` 補查。**`theme` 不參與入榜、排序、40 上限,也不寫進紀錄行**(`bullBoard.test.ts` 鎖住:有無 theme,`selectBoard` 與 `boardLogLine` 結果相同)。
- **三態**:檔不存在/404 = 沒算過(「這一版還沒有多方榜…」);`qualified 0` 且 `entries []` = 算過、沒人入榜;非空 = 名單。不得把前兩者塌成同一句。
- **紀錄行**(`bull_board_log/*.jsonl`,一次建置一行):`{version, data_date, generated_at, radar_generated_at, universe, qualified, universe_ids:[…], entries:[{id,bull_key_n,bear_key_n,bull_codes:[…]}], excluded:[{id,bull_key_n,codes:[…]}], inputs}`。`excluded` = `|K_bull| ≥ 3` 但被 E 排除者。這是 §2 的唯一資料來源;建置器**只追加,不改寫**。
- **重複行(2026-10-04 釐清,讀法規則,在任何評估存在之前決定,不改 §1/§2 任何規則)**:同一 data_date 可有多行(每輪發布後都重建)。檢定只讀 §2 定義的紀錄版 r(t)——`data_date == t` 且 `generated_at` 早於 e(t) 09:00 的**最後一行**,也就是那天的最終名單;同日較早的行只是稽核軌跡(以及 §4 伴隨計數「14:05 那一版」),不進任何判準。建置器在追加前比對**同一 data_date 的最後一行**:去掉 `generated_at`/`radar_generated_at` 後 JSON 相同 → 不追加(印 `bull-board log: unchanged, skipped`);內容變了(例:17:30 分點到齊改了名單)照樣追加;最後一行壞掉(無法解析)→ 照樣追加(先補換行)。一段相同行只留**第一行**,它的 `generated_at` 最早,故 r(t) 選到的**內容**與全部保留時相同(評估中立)。既有月檔用 `web/scripts/dedupe-bull-board-log.mjs`(同一判定,`lib/bullBoardLog.ts`;預設 dry-run,`--write` 寫 `.tmp` 再 rename)一次性壓縮;這是維護、不是建置器改寫。鎖在 `web/lib/bullBoardBuild.test.ts`。
- 建置器失敗**不得擋 deploy**(VPS 以 warn-and-continue 接)。
- **VPS 接線(2026-10-04)**:`vps/scripts/lib.sh build_bull_board` 在主機上跑 `timeout ${BULL_BOARD_TIMEOUT_SECS:-600}s node --experimental-strip-types --no-warnings web/scripts/build-bull-board.mjs --data $REPO/web/public/data --log $REPO/data/bull_board_log`(VPS Node 22.23 實測 2,418 檔 33.5 s),log 一行 `step bull-board start … / done rc= elapsed=`;失敗/逾時只 `notify_warn`、永遠 return 0,首頁沿用上一版。每一支 export-json → deploy_data 的腳本都在 export-json **緊後**、deploy_data 之前裸呼叫(daily-market/tpex-quotes/insti/branches 兩模式/margin、safe-branch-stats、mid-backfill-publish、weekly-tdcc、monthly-directors、manual-catchup、backfill-margin、backfill-tdcc);沒匯出(`publish skipped: no change`)的輪就不建。`data/bull_board_log/` 列入 `.gitignore`。鎖在 `pipeline/tests/test_bull_board_vps_wiring.py`。

## 2. 名詞(事前登記)

- **市場交易日曆 D**:`daily_prices` 任一列存在的日期集合(同 `docs/39` §0、`docs/40` §0)。
- **紀錄版 r(t)**:對資料日 t,`bull_board_log` 中 `data_date == t`、`generated_at` 早於 **e(t) 的 09:00(台北)** 的**最後一行**。沒有這一行 → t 不產生任何事件,也不提供對照日(計數)。用 09:00 前最後一次成功建置,是因為那是讀者在 e(t) 開盤前最後看得到的名單。
- **進場日 e(t)**:D 中 t 之後第 1 個市場日。由日曆算,不由任何儲存欄位讀。
- **上榜日**:s ∈ r(t).entries。**事件**:s 的上榜日 t,若 D 上 t 的前一個市場日 s 不是上榜日(含前一日沒有紀錄版),t 是事件(連續上榜取首日)。
- **漲 ≥ 3%(hit)**:`100 × close(s, e) ≥ 103 × open(s, e)`;**跌 ≥ 3%(drop)**:`100 × close(s, e) ≤ 97 × open(s, e)`。原始價、同一列,十進位比較(同 `next_day_surge_battery._dec`)。不含 t 收盤到 e 開盤的跳空。畫面與文件一律寫「漲 ≥ 3%」。
- **as_of**:`max daily_prices.date`,由程式讀出,不由人挑。

## 3. 否決與對照

### 3.1 否決(per 事件、per 對照日;命中 → 不進分母、也不算未命中)

- **R1 不成熟或無列**:e(t) 不存在或 > as_of;(s, e) 沒有價格列;`open` 為 NULL 或 ≤ 0;`close` 為 NULL。
- **R2 停牌**:e 日 `volume` 為 0 或 NULL。
- **R3 鎖漲停開盤**:**不否決**(結構性未命中,兩臂同規則);只報告 `open(s, e) ≥ 1.095 × close(s, t)` 的事件數。

### 3.2 對照池(兩組,seed 0..9)

- **合格對照日 (s, d)**:s ∈ r(d).universe_ids、s ∉ r(d).entries、d 有紀錄版、(s, e(d)) 通過 R1–R2。
- **P_stock(同股、同半段)**:對每個 (s, 半段 h),s 在 h 有 k 個事件,就從 s 在 h 的合格對照日不放回抽 k 天。
- **P_date(同日、他股)**:對每個有 k_t 個事件的日子 t,從 r(t) 的 U 中未上榜的他股抽 k_t 個。
- `LOW_SAMPLE_SURVIVORS`、`PLACEBO_SEEDS`、`seed_result`、`PLACEBO_SIGMA_MULTIPLE`、`split_window` 一律從既有模組 import(`futures_volume_battery` / `branch_window_direction_battery`),不重寫;抽法同 `next_day_surge_battery.draw_matched`。任一鍵抽不滿 → **NOT EVALUABLE**,逐項列出。
- **對半**:評估期(第一個有紀錄版的資料日 → as_of)內的市場日依 `split_window` 慣例對半;事件與對照日依 t 歸半。

## 4. 檢定(全過才 SHIP)

- **A 檢定力**:`n ≥ 30` **且** `h ≥ 30`。不足 = UNDERPOWERED(無結果,不是否證)。
- **B 資訊性**:兩組對照 × 10 個 seed,每一個都要 `h − h_P ≥ 2·σ_P`,`σ_P = max(1, sqrt(n·p̂·(1 − p̂)))`、`p̂ = h_P / n`。20 個判準全過。
- **D 方向**:同一批抽樣,每組每 seed `(h − d) − (h_P − d_P) ≥ 2·σ_N`,`σ_N = max(1, sqrt(h_P + d_P − (h_P − d_P)² / n))`。20 個判準全過。
- **C 兩半**:每一半、每組、每 seed `h(半) − h_P(半) > 0`。40 個判準全過。
- 裁決:A、B、D、C 全過 → **SHIP**;其餘 **DO NOT SHIP**,理由依序取第一個成立者 `underpowered` → `not_evaluable` → `informativeness_failed` → `direction_failed` → `consistency_failed`。
- **伴隨計數(只報告,永遠不是判準、永遠不是補救)**:+5% / +7% 的漲跌次數;依 `|K_bull|` 分桶(3、4、5、≥6)的 events/hits/drops;14:05 那一版 vs 紀錄版的名單差異數;被 E 排除者(`excluded`)的 hits/drops;依月份;收盤對收盤(t 收盤 → e 收盤)的 ≥ 3% 次數;R3 代理數;各否決計數。

## 5. 執行、重跑與上線

- 實作唯讀 battery `pipeline/radar/compute/bull_board_battery.py`(**P3,本次不做**):第一次執行在紀錄起點之後累積滿 **60 個市場日**。上正式資料前交獨立驗證者挑錯,至少殺掉:e = t+2;e 讀儲存欄位;紀錄版取 09:00 之後的行;連續上榜不合併;對照池放進上榜股;D 改成 `h − d > 0`;任一 seed 過就過;C 放寬成 ≥ 0;as_of 可由人指定。
- UNDERPOWERED / NOT EVALUABLE → 自上次 as_of 起累積 ≥ 60 個新市場日才可重跑;B/C/D 不過是結果,收案,不重跑。
- **只有 SHIP 才上線**:`bull_board.json` 加 `next_day` 鍵(§4 的整數),畫面句由 `lib/` 純函式產出、逐字鎖住,含「這是次數,不是機率;不含開盤跳空,開盤即漲停算沒漲到;未扣手續費與交易稅;每檔股票沒有自己的數字。」在那之前,payload 與畫面**不得**出現任何往後表現的數字。
- 上線後每 60 個市場日以累計樣本重跑;B、C、D 任一不過 → 撤下顯示。

### 5.1 不允許的補救(在看到資料之後)

改 3 / 改開盤到收盤 / 改 e / 改事件合併 / 改紀錄版的 09:00 / 改母體 / 改 `|K_bull| ≥ 3`、rank ≥ 4、rank == 5 排除、section 範圍、40 上限 / 改 rank 表任一格 / 改 30、2σ、seed / 改 σ 寫法 / 依月份、產業或 |K_bull| 條件化 —— 都只能開 v2,並只用 v2 commit 之後的市場日。允許探索、允許寫進 STATUS,**不允許改變裁決**。

## 6. 凍結前已看過的東西(逐項揭露)

- `daily_scores.final` 的分布(54 個評分日、≥ 65 只有 8 天各 1 檔)與 VPS cron log(盤中假上榜的時序)。**沒有 JOIN 任何次日價格。**
- `docs/39` 第 1 次執行(2026-09-24)的綜合榜 +7% 彙總計數(n = 23);母體與條件都不同,不是本規則的輸入。
- 個股頁「多空」分頁(docs/46)上線後,使用者與 agent 在正式站看過若干個股的多空事實與其 K 線(非系統性)。這些是**個股頁**的畫面,當時沒有「多方榜」這個名單,也沒有任何人以 §1 的規則篩過股票再看之後的走勢。
- 本規則的實作只在本機舊 fixture(2026-07 的 JSON)上跑過建置器量測耗時與形狀,沒有對任何價格做 JOIN。
- **本文件 commit 之前不得 JOIN 紀錄與次日價格**;之後也只能由 §5 的 battery 做。

## 7. 沒被問到、但會讓結果不誠實的地方(事前承認)

- **群聚**:多頭日整批入榜,二項 σ 偏樂觀;P_date 吸收水準、C 擋集中、D 擋純波動,剩下的群聚仍在——這是要求 20 + 20 + 40 個判準全過的理由。
- **事實彼此相關**:K_bull 的條目不是獨立證據(同一次大量買超可能同時觸發分點與法人);本規則只「數條數」,不宣稱條數線性代表任何東西。
- **漲跌幅 10%**:開盤鎖漲停結構性未命中(R3)。
- **成本**:+3% 是毛額,未扣手續費與交易稅。
- **盤中版本**:14:05 等盤中建置的名單資料未到齊(法人、分點);紀錄版取 e 日 09:00 前最後一版,通常是晚間資料齊全那一版。差異只列伴隨計數。

## 8. 變更紀錄

- 2026-10-04:§1.1 加「重複行」讀法釐清——檢定只讀每個 data_date 的 r(t)(09:00 前最後一行,即當日最終名單),同日較早行僅為稽核軌跡;建置器跳過只差時間戳的相同重建、既有重複行可用壓縮工具移除(每段留第一行,r(t) 內容不變)。評估中立,§1–§4 規則未改,不需開 v2。
