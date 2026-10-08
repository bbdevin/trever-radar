# 47 — 日更排程優化:輪詢到公布為止、有變動才上線

> 2026-10-04 定稿並實作(程式 + `crontab.example`)。**正式機 crontab 尚未套用**——要改的 7 行見
> `vps/scripts/crontab.proposed.diff`(高風險項,依 AGENTS.md 由人類核准後套用)。
> 腳本在**舊時刻**也正確:各輪的截止時刻寫在腳本裡,先 push 程式、後改 crontab 沒有空窗。
> 使用者原話:「如果能優化確保能抓到資料更新當然好」——每個來源一公布就上線,不浪費輪次。

## 1. 實測(12 個交易日的 `~/radar-cron.log`)

| 來源 | 舊排程 | 實測 | 問題 |
|---|---|---|---|
| 上市日K | 14:10 | 14:10 時 12/12 已到 | 週一同一輪先跑題材/地緣/產業別 45–55 分才 export |
| 上櫃日K | 15:00(14:10 必空) | 14:10 0/12、15:00 12/12 | 週一 14:10 輪拖過 15:00 → 15:00 輪 `flock -n` 失敗,**整輪上櫃靜默消失** |
| 上市法人 | 16:10 | 16:10 只 5/12(7/12 empty);17:40 12/12 | 7/12 天要等分點輪約 20:30 以後才上線(落後 3–5.7 小時) |
| 上櫃法人 | 16:10 | 12/12 | — |
| 分點 | 17:40 全量 + 22:00 | 17:40 覆蓋率常 33–56% → 扣留(最近 4 個交易日全扣);22:00 每天 100% | 17:40 白爬 41–62 分(6/12 天);22:00 每天重爬 2,672 檔 41–104 分,即使 17:40 已 86% |
| 資券 | 21:20 | 12/12 ok | 固定等到 21:20,TWSE ~21:00 就有 |
| 非交易平日(09-25、09-28) | 每輪照跑 | — | 每輪照樣 export+deploy、重爬分點:~3.5 小時鎖、~5,000 請求、零變化 |
| 夜間 PIT/分位 | 00:05 | 算好 | evening ok 時不 export,要等隔天 14:10 才上線 |
| deploy | 每輪 | ~3,000 檔 | 每個檔都帶 `generated_at`,全部重傳(本次不處理,見 §7) |

## 2. 原則

1. **輪詢到公布為止**(`lib.sh` `poll_until LABEL DEADLINE_HHMM INTERVAL_SEC CMD…`)。每輪有起點/間隔/截止;每次嘗試前 `flock -w` 拿 DB 鎖,匯入只要幾秒,沒到(exit 75)就**先 `flock -u 9` 放鎖再睡**——絕不握著鎖等來源。
   `import-daily --require src:ds[:minfrac]`:被要求的資料集 empty、rows=0、或 rows < minfrac × 前一個有資料日的 ok 列數(`import_logs`)→ exit 75,已寫入的照留(與 `import-futures-day` 的 75 同義)。TPEx 520 只在 `tpex:quotes` 被要求時算「還沒到」;沒給 `--require` = 舊行為逐字不變(含 `tpex_520_only` 的 75)。截止仍 75 → `notify_warn`「…至 HH:MM 仍未公布」,不上線。
2. **有變動才上線**(`round_has_changes`):本輪(`ROUND_STARTED_AT` 之後)`import_logs` 沒有任何 `ok` 且 `rows>0` 的 quotes/insti/margin/futures-day/branch → 不 compute/export/deploy,log `publish skipped: no change`。`price_date_is_today`(唯讀 `MAX(date) FROM daily_prices` == 台北今天)擋住分點輪、資券輪與 00:05 的非交易日。
3. **分點全量爬由探測觸發**:新 CLI `probe-branch-day [--date] [--sample 24] [--threshold 22] [--sleep 1.0]`,從 `--top 0` 池等距抽 24 檔各抓一次富邦頁(NoDataError 算沒到),**不寫 DB、不記 import_logs**,印 `branch-probe at=HH:MM date=… ok=k/24 …`,k ≥ 22 → 0,否則 75。17:30 起每 15 分鐘問一次(等待期間不握 DB 鎖,只握分點來源鎖);達門檻或到 20:30 → 全量爬(0/75/76 分級、覆蓋率閘門不變)。完成標記第二行寫 `coverage_ratio=`;22:30 第二輪:標記 ratio=1.0 → `publish skipped: first round complete`;<1.0(或舊格式)→ 照舊重爬 + 刷新評分;無標記 → 照舊接手完整鏈。
4. **搶不到鎖就等,不略過**:`acquire_db_lock_wait SECS`(`flock -w`;逾時 high 通知、exit 0)給五支日更輪與 `weekly-refdata.sh`;`data-backfill.sh` 維持 `flock -n`(可續跑,讓路一晚零損失)。

開關:`RADAR_POLL=0` = 只試一次、75 當已到(舊行為);`BRANCH_PROBE=0` = 不探測直接爬(舊行為)。
安靜窗(`quiet_window_at`)刻意**未改**:mid-backfill-publish 20:00 那一格必須留在窗外(`test_cron_quiet_window.py` 鎖住)。

## 3. 各輪(新 crontab 時刻;舊時刻下行為同樣正確)

| 新時刻(舊) | 腳本 | 行為 |
|---|---|---|
| 週一 11:00(新增) | `weekly-refdata.sh` | `acquire_db_lock_wait 1800` → sync → 題材/地緣/產業別(warn-and-continue)→ 寫 `/tmp/radar-refdata-<ISO 週>.done`;不 export(14:05 那輪一起上線)。過渡:crontab 還沒加這行時,週一 `daily-market.sh` 看不到標記就在 **deploy 之後**補跑 |
| 14:05(14:10) | `daily-market.sh` | 等鎖(2026-10-07 起不再先跑 futures_probe,見 docs/38 §7.18)→ 每 3 分輪詢 `import-daily --datasets quotes --require twse:quotes` 至 14:40 → 彙總 → 指標 → 分數 → export → deploy |
| 14:45(15:00) | `daily-tpex-quotes.sh` | `acquire_db_lock_wait 2700` → 每 3 分輪詢 `--require tpex:quotes:0.8` 至 15:30 → 彙總 → 指標 → 分數 → export → deploy。今天上市日K不在庫(休市)→ 只試一次 |
| 16:00(16:10) | `daily-insti.sh` | 日K保底(TPEx 520 → 75 分支保留)→ 每 5 分輪詢 `--datasets insti --require twse:insti,tpex:insti` 至 17:10,每次嘗試順手 `import-futures-day`(75 下次再試、0 不再試)→ 權證主檔、庫藏股(warn-and-continue)→ 彙總 → 指標 → 分數 → export → deploy → futures_digest。**截止仍缺**:有其他變動(上櫃法人/期貨等)→ warn 並先上線已到的部分(舊 16:10 也是先上線上櫃法人;不讓它陪等到 20:30);沒有 → `publish skipped` |
| 17:30(17:40) | `daily-branches.sh` | 非交易日收工 → 等鎖 → 日K+法人(保底)→ 期貨當日(法人輪已拿到就略過)→ 指標 → seed → **探測迴圈**(放 DB 鎖)→ 重新等鎖 → 全量爬 → 分級 → 分點統計 → 已過 21:00 順手匯入資券 → 分數 → 績效 → export → prune → deploy → 完成標記(含 `coverage_ratio=`) |
| 20:45(21:20) | `daily-margin.sh` | 上市＋上櫃資券今天都已匯入(分點輪帶入)→ 收工;保底日K匯入後仍無今天日K → warn 收工(§3.1);`acquire_db_lock_wait 5400` → 再查一次 → 每 5 分輪詢 `--datasets quotes,margin --require twse:margin,tpex:margin` 至 22:15 → import-futures(官方覆核)→ 分數 → 績效 → export → deploy;落後補抓分支保留 |
| 22:30(22:00) | `daily-branches.sh`(`BRANCH_ROUND_MODE=import`) | 原則 3 |
| 00:05(不變) | `safe-branch-stats.sh` | 既有守衛 + 前一日非交易日收工;PIT 或分位計數有算出 → export + deploy(不再跳過 export);evening ok 且兩者都沒有 → 不 export 也不 deploy |

### 3.1 驗證者修正(2026-10-04,同日;優先於上表與 §2 的對應敘述)

1. **`poll_until` 截止回 75 時仍握著 DB 鎖**(截止判斷移到放鎖之前)。舊版截止前先放鎖,`daily-insti.sh` 截止後的權證主檔/庫藏股/部分上線、休市路徑都在無鎖狀態寫 DB。只有「睡覺」那段沒有鎖。
2. **非交易日改成「先匯入、再判斷」**:分點輪在自己的 `import-daily quotes,insti` 之後、資券輪在自己的保底日K匯入之後,今天的日K仍不在庫才收工,並 `notify_warn`。夜間 00:05 只在「那一天沒有任何分點匯入紀錄**且**沒有那天的日K」才略過(warn)。前幾輪壞掉時,這些輪自己的匯入就是當天的補救,匯入前就判斷會把整天靜默丟掉。週一 `daily-market.sh` 在截止/無變動的出口也補跑題材/地緣/產業別(週一休市時本輪一定走那些出口)。
3. **分點輪順手匯入資券加 `--require twse:margin,tpex:margin`**(只到一邊 → 75 → 留給資券輪);資券輪「已由分點輪帶入」改成要求**上市與上櫃**今天都有 `import_logs` 的 ok、rows>0 紀錄,不再只看 `MAX(date)`。
4. 22:30 第二輪的「第一輪覆蓋率 100% → 收工」移到日K/法人匯入與期貨當日重試**之後**(仍是期貨當日的最後一次重試)。
5. 首頁時間表(`web/lib/freshness.ts`)已是新時刻:**合併與正式 crontab 套用要同一次完成**,否則首頁時刻會與實際差 5–35 分。

## 4. 預期效果(依 §1 實測推估,套用後要以 log 驗證)

| 項目 | 舊 | 新 |
|---|---|---|
| 上市日K上線(收盤後) | 35–53 分 | ~25 分 |
| 上櫃日K | ~25 分後(週一 ~100 分) | ~15 分(週一同) |
| 上市法人 | 7/12 天落後 3–5.7 小時 | ~20 分 |
| 分點(被扣留的日子) | 23:19–00:18 | ≤22:00 |
| 資券 | ≥35 分 | ~13 分 |
| 夜間分位/帳本 | 隔天 14:10 | 當晚 |
| DB 鎖忙碌/日 | 4.3–5.5 小時 | ~2.6–3.0 小時 |
| 非交易平日 | ~3.5 小時 | ~0.1 小時 |

## 5. 驗證(套用 crontab 後第一週,唯讀)

```bash
grep -E '^poll .* (ready|deadline) at=' ~/radar-cron.log | tail -n 40   # 各輪幾點到齊、試了幾次
grep -E '^branch-probe at=' ~/radar-cron.log | tail -n 30               # 探測進度
grep -E 'publish skipped' ~/radar-cron.log | tail                       # 沒變動/第一輪已完整
grep -E 'db lock acquired waited=' ~/radar-cron.log | tail              # 等鎖秒數
grep -E 'step (import-branch-trades|compute-branch-stats|export-json|deploy) done' ~/radar-cron.log | tail -n 40
cat /tmp/radar-branch-round-$(date +%F).done                            # 第二行 coverage_ratio=
```

失敗訊號:`poll … deadline` 天天出現(截止太早)、`branch-probe` 到 20:30 都不過(門檻太高,調 `--threshold`)、`資料庫鎖等滿` 的 high。

## 6. 回滾

- 單輪關閉輪詢:`RADAR_POLL=0`;關探測:`BRANCH_PROBE=0`(兩者都是舊行為)。可直接寫進 crontab 那一行的前綴。
- 全部回滾:`crontab` 還原備份(`~/crontab-backup-*.txt`)+ `git revert` 本次 commit。舊時刻下新腳本也正確,所以兩者可分開回滾。
- 完成標記多了第二行;舊程式只讀存在與否、夜間作業已改讀第一行,回滾不需清檔。

## 7. 刻意不做

- **docs/20 Phase 4 的「兩次 deploy」舊提案作廢**:16:10–21:00 只寫 DB 不上線 = 法人/分點晚數小時上站,與使用者目標相反。本方案是反方向:到了就上線,沒變就不上線。
- deploy 全量重傳(`generated_at`)、export 增量化屬 `docs/44` P1,不在本次。
- 安靜窗範圍不動;`data-backfill.sh` 不改成會等。

## 8. 分點輪提速(2026-10-07 定案並實作;正式 crontab 待人類套用)

> 使用者原話:「分點的資料是不是抓很慢」「其他網站分點資料五點就更新了 我還要等到八點」「我目標就是能在我的系統快點看到資料」。
> 主指標 = **來源公布 → 網站看得到** 的時間。程式在舊時刻(17:30)也正確;先合併、後改 crontab 沒有空窗。

### 8.1 實測(`~/radar-cron.log`)與各段耗時

| 日期 | 來源就緒(探測) | 全量爬 | 之後各段 | 上線 | 公布→上線 |
|---|---|---|---|---|---|
| 10-07 | 17:32 0/24、17:47 0/24、18:03 5/24、18:18 8/24、18:34 21/24、**18:49 24/24** | 3,263 s(54 分,1,962 檔,1.66 s/檔) | stats 600 s、export 840 s、多方榜 29 s、deploy ~180 s、scores/perf/prune ~90 s | 20:12 | **83 分** |
| 10-05 | 19:42(fubon 一次 ReadTimeout) | **6,119 s(102 分,3.1 s/檔)** | 同上 | ~21:55 | ~130 分 |
| 10-06 | — | — | 17:30 第一步 `import-daily quotes,insti` 回 1(TPEx ChunkedEncodingError,瞬時)→ `run_step_or_fail` 整輪中止;分點靠 22:30 第二輪(爬 3,221 s)約 00:00 上線 | 00:00 | **約 5 小時延後** |

10-05 為何兩倍:循序爬是「全域 1 秒一請求、五站輪替」,每檔耗時 = max(1 s, 來源回應時間)+寫入;一站回應慢(ReadTimeout 30 s × 3 次重試 + 退避 5/10 s,單檔最長 ~105 s)時,輪到那一站的 1/5 標的全部陪等——10-05 探測就抓到 fubon 站 ReadTimeout。**不是** mid-backfill-publish 或 bf 容器:分點輪整輪開著 fd 9,`fuser /tmp/radar-db.lock` 看得到,mid 20:00 會略過、bf-cron-guard 會 pause(只憑 log 無法百分之百排除,但機制上它們進不來)。

來源調查(2026-10-07,唯讀):證交所「買賣日報表」16:00 產製但要驗證碼(既定不破解;e-shop 為付費產品);櫃買「券商買賣證券日報表」16:00 起提供但已加 Google reCAPTCHA;TWSE/TPEx OpenAPI 沒有任何分點資料集(只有券商名單);其他網站 17:00 就有,是交易所資料(付費或破解驗證碼)。**免費、無驗證碼的來源只有 MoneyDJ 五鏡像(富邦/元富/永豐金/國泰/凱基)**,實測 18:00–18:50 逐步公布。五站是否同時更新**今天量不到**(資料已公布),已改成逐站探測並逐站記 log(§8.2 第 2 點),明天 16:30 起的 log 就有答案。

### 8.2 改了什麼(`vps/scripts/daily-branches.sh`、`lib.sh`、`pipeline/radar/{importer,mirror_crawl,http,cli}.py`、`providers/fubon.py`)

1. **五站平行、單站節奏不變**(`--workers 5`,`radar/mirror_crawl.py`):每站一個 worker **釘在那一站**,單站間隔 = `--sleep 1.0 × 5 站 = 5 秒`(循序輪替到同一站最快也是 5 秒一次,來源負載不變);總吞吐上限 1 請求/秒,2,000 檔 **~33 分鐘,不隨來源變慢而變長**(單站回應 < 5 秒即可)。共用一條佇列(慢的站拿得少);連續失敗 5 次的站視為死站退出,剩下由活站接手;重試輪只用活站。節流改 `http.py` 的 per-key(鎖內預約時槽),不碰全域 `_last_request_at`;`workers=1`(預設、回補、探測以外的呼叫)逐字維持舊行為。
2. **逐站探測、哪站先好先用哪站**:`probe-branch-day` 每站各抓同一批等距樣本(平行、各自節流),ok ≥ 門檻的站算就緒;**至少 3 站就緒**(`--min-ready-hosts 3`)或到 20:30 才全量爬——只有一站就緒時單站 5 秒間隔抓 2,000 檔要 10,000 秒,超過 7200 硬上限(2026-10-07 驗證者)。log 多逐站一行 `branch-probe mirror=<站> at=HH:MM ok=k/n ready=0/1`。全量爬開跑前再每站各抓 6 檔確認(`BRANCH_MIRROR_CHECK_SAMPLE`),已公布的站開工、**其餘站待命**(`mirror_crawl` standby:每 5 分鐘一個請求問一次,公布了就加進來當 worker);一站都沒到(20:30 截止的情況)用全部,閘門照舊把關。探測改 **16:30 起每 10 分鐘、每站 12 檔、門檻 11**(每站 12 請求/10 分鐘,早起沒有成本)。
3. **抓與寫分離,抓的時候不握 DB 鎖**:`import-branch-trades --stage-to`(只抓不寫,結果照目標順序落 `data/branch-stage-<日>.json`,**每 50 檔 checkpoint**(tmp+rename),不碰 DB、不記 import_logs,exit 0,硬上限 `radar_timeout 7200`)→ `acquire_db_lock_wait 3600` → `--from-stage`(只寫不抓,照順序 upsert、記 import_logs、量覆蓋率,離開碼 0/75/76/1 分級**逐字不變**;暫存檔裡 pending 的算 failed)。**續抓(設計決定,2026-10-07 第二次驗證)**:只接**同一天、`complete=false`**(被硬上限/SIGTERM 砍掉)的暫存檔,`--stage-to` 只重抓 pending/failed/empty,done 的不重抓——這是「同一輪鏈的續抓」,不是「第二輪沿用第一輪」。已完成的暫存檔一律忽略、整份重爬:寫入成功的會被腳本刪掉,留下來的只有不合格(覆蓋率掉出地板)那一支,而那正是 main 上 22:30 第二輪的語意(標記 ratio<1 或無標記 → **全部重爬**,晚公布的才補得到;ratio=1.0 → 收工)——新版逐字維持。形狀不對(缺 sid、outcome 不認得)→ 整份當不存在、印一行警告。取捨:被砍掉的那一輪 done 列最多舊 2 小時(抓取硬上限),來源公布後的「事後修正」不是已知現象,而且隔天第一輪冪等重抓同一天會覆蓋;不做「done 超過 N 小時重抓」。worker 裡的 checkpoint 寫檔失敗(磁碟滿)只記一行、繼續抓,收尾那次由主執行緒寫、失敗正常拋出。待命站的監督:**沒有活 worker、這一輪待命站也一個都沒進來 → 收工**,剩下的標的 pending/"no live mirror"(舊行為,交給重試輪 / 76 / 覆蓋率閘門),不再等到硬上限。暫存檔的清理(`.tmp` EXIT trap、別天的 `find -delete`)在**拿到來源鎖之後**才做:鎖拿到之前,今天的 .tmp 可能是還在抓的第一輪在寫的。**SIGTERM**:容器 `--init`(tini 當 PID 1 轉送;以前 python 是 PID 1,`timeout` 只殺得掉 docker CLI、容器變孤兒),CLI 在 `--stage-to` 時裝 handler:收到就不再領新工作、寫 checkpoint、以 143 離開。DB 鎖握持從「整輪 ~90–140 分」降到「前置 ~5 分 + 寫入與上線 ~30 分」。
4. **原始資料一致**(`tests/test_branch_crawl_parity.py`,只 mock HTTP、走真的解析器):循序 / 平行 / 暫存 / 續抓四條路的 `branch_trades_raw`、`branch_dim`(含新分點的 id——id 由插入順序決定,所以 worker 不准寫,主執行緒照目標順序 commit)、import_logs 位元級相同。**兩個已知的註記**:(a) 目標順序改成成交金額大的先(第 7 點),所以**全新**分點拿到的 `branch_dim.id` 與舊版(代號序)會不同——那是代理鍵,只有 raw 列的 `branch_id` 引用它,所有 join 走 id,沒有任何地方依賴 id 的大小;(b) 同一檔由哪一站抓取決於排程,若兩站對同一檔回傳不同內容,結果就不是決定性的——五站實測位元級相同(`docs/vps_backfill_plan.md` 附錄),一致性的前提是這個;某站改版時解析失敗會以 failed/死站的形式出現在 `branch crawl mirror=` 行。
5. **兩段式上線**:寫入 → scores → performance → prune → **export → 多方榜 → deploy(分點明細與評分上站)** → `set_round_consequence`「已於第一段上線…00:05 會重算排行統計」→ `notify_ok`(含覆蓋率、「排行統計約 25 分鐘後更新」)→ compute-branch-stats → 再 export/deploy → 完成標記。第一段上線的分點是**完整日**(覆蓋率閘門已放行),不是部分日;只有排行/分位統計是前一版,通知裡講明。`publish_site()` 只有一份,被呼叫兩次。第二輪只刷新評分的路徑在第一段之後離開(不算統計、不重寫標記,與以前相同;prune 在它之前,兩條路都走到)。
6. **前置步驟分級**(§8.3)。
7. **成交金額大的先抓**(`--top 0` 池改依 turnover 排序;探測的等距抽樣仍用代號序的池子;分母與覆蓋率不變):抓到一半被硬上限砍掉時,留在暫存檔外的是冷門股。
8. `bf-cron-guard.sh` 多一個 pause 條件:分點來源鎖被握著(`fuser /tmp/radar-branch-source.lock`)。bf 容器打同五個站,以前是靠分點輪開著 fd 9「順便」停住的,現在明講。
9. 首頁時間表 `web/lib/freshness.ts` 改 16:30;changelog v3.4。

### 8.3 前置步驟:哪些失敗可以續跑(`lib.sh` `run_step_or_fail_unless` / `run_step_or_warn`)

| 步驟 | 失敗時 | 理由 |
|---|---|---|
| `import-daily quotes,insti` | 今天的日K已在庫(`price_date_is_today`)→ **warn 續跑**;不在庫 → high + 原碼中止 | 只是補抓(14:05/16:00 早進庫);不在庫時它是當天唯一補救 |
| 休市判斷(`if ! price_date_is_today`) | 不變:先匯入再判斷,休市 warn 收工 | |
| `import-futures-day` | 不變:75 只記 log、其他 warn | |
| `compute-indicators --all --days 5` | 今天的指標已在庫(`indicators_date_is_today`)→ warn 續跑;不在庫 → 中止 | 三輪早算過;缺今天的指標評分會缺技術分 |
| `seed-branches` | **永遠 warn 續跑** | 追蹤名單沿用上次;CLI 本身設計成永不失敗 |
| `fetch-branch-trades`(抓) | high + 中止(什麼都沒進庫;暫存檔留著已抓到的,第二輪續抓) | 超時 124 / SIGTERM 143 |
| `import-branch-trades --from-stage`(寫)| 0/75/76/其他 分級不變 | |
| scores / performance / export / deploy / stats / prune | 不變:high + 中止 | 它們就是上線鏈 |

### 8.4 預期時間線(公布→看得到;各段估計依 §8.1 實測)

| 段 | 舊 | 新 |
|---|---|---|
| 探測偵測延遲 | 0–15 分(每 15 分一次) | 0–10 分(每 10 分一次,每站各 12 檔 ~1 分) |
| 全量爬 | 54 分(好日)/102 分(壞日) | **~34 分**(含開跑前每站 6 檔確認、重試輪),壞日相同 |
| 寫入 | 含在爬裡 | ~1–2 分(2,000 檔逐檔 commit) |
| scores + performance | ~1.5 分 | ~1.5 分 |
| compute-branch-stats | 10 分(**在上線前**) | 10 分(**移到第一段上線之後**) |
| export + 多方榜 + deploy | 14 + 0.5 + 3 分 | 同(第一段);第二段再一次 |
| **公布→分點明細可見** | **~83–90 分**(10-07:18:49→20:12) | **~60 分**(偵測 5 + 爬 34 + 寫 2 + 分數 2 + 匯出 14 + 榜 0.5 + 佈署 3) |
| 排行統計可見 | 同上 | 第一段 + ~28 分 |
| DB 鎖握持 | 整輪 ~90–140 分 | ~35 分(抓取期間完全不握) |

| 來源就緒 | 舊:分點可見 | 新:分點可見 | 新:排行統計可見 |
|---|---|---|---|
| 17:00(假設) | 不可能早於 17:30 探測 → ~18:55 | **~18:00** | ~18:30 |
| 18:30 | ~20:00(10-07 實測 18:49 → 20:12) | **~19:30** | ~20:00 |

剩下最大的固定段是 **export 14 分**(全量匯出 ~6,400 檔),其次 deploy 3 分:`wrangler deploy` 本來就只上傳 hash 變動的資產,但每檔都帶 `generated_at` 所以幾乎全部重傳(§1)。**下一步**(未做):export 只匯出本輪分點有變動的個股 chips 檔 + radar.json(`docs/44` P1 增量化),第一段可再省 ~10 分;compute-branch-stats 改只算新日期(未評估安全性,先不動);更早的部分上線(聯集/自選先抓 ~300 檔 → 先上線)需要上面的 subset export 才划算,而且要在資料與 UI 標「分點資料更新中 n/N」,否則違反覆蓋率閘門的用意——留待 subset export 完成後再議。

### 8.5 鎖表(新架構;「撞到」= 另一輪同時要用時怎麼辦)

| 腳本(時刻) | 鎖 | 握著的時段 | 撞到時 |
|---|---|---|---|
| `daily-branches.sh`(16:30 / 22:30) | 分點來源鎖 fd 8 `/tmp/radar-branch-source.lock`(**先拿**) | 整輪(含 ②) | `acquire_branch_source_lock_wait 5400`:**等**(不握 DB 鎖地等);等滿 = 第一輪卡住(抓取有 9000 s 硬上限,最晚 ~23:50 收工,正常不會)→ high + exit 0。22:30 撞上還在抓的第一輪:等第一輪收工再接手,不再靜默略過 |
| 同上 | DB 鎖 fd 9 `/tmp/radar-db.lock`(**後拿**) | ① 開輪 → 前置步驟結束(~5 分);② **放掉**:探測 + 抓取(10–100 分,`release_db_lock`,fd 仍開著);③ 寫入前 `acquire_db_lock_wait 3600` → 第二段 deploy 結束(~35 分) | 等,最多 3600 s;等滿 high 通知 + exit 0 |
| `daily-insti.sh`(16:00–17:10 輪詢) | DB 鎖 | 每次嘗試前 `flock -w 3600`,75 之後放鎖再睡 | 與 16:30 分點輪交錯:誰先拿誰先做,對方等 ≤3600 s |
| `daily-margin.sh`(20:45) | DB 鎖 | `acquire_db_lock_wait 5400` → 收工 | 分點輪多半已在 19:30 前結束;撞到就等(≤5400 s) |
| `mid-backfill-publish.sh`(03/09/12/20) | 不拿鎖;`fuser` 看 DB 鎖檔有沒有人開著 | export + deploy ~15 分 | 任何日更輪活著(含分點輪的 ② 相位,fd 9 仍開)→ **略過**。刻意保守:它只服務 bf 容器,沒有 bf 時本來就 noop |
| `safe-branch-stats.sh`(00:05) | DB 鎖 `flock -w LOCK_WAIT_SECS` | 統計 → 上線 | 等;有完成標記 → 整夜略過;分點輪第二段失敗沒寫標記 → 它補 |
| `weekly-backup.sh`(週六 05:00) | DB 鎖 `acquire_db_lock`(`flock -n`) | 備份全程 | 搶不到 → 略過 + 通知(週六沒有日更輪) |
| `data-backfill.sh`(01:10) | DB 鎖 `flock -n` | | 搶不到 → 略過(可續跑) |
| `warrant-backfill.sh` | 來源鎖(就地 `flock -n`)→ 再 DB 鎖 | | 分點輪握著來源鎖 → 略過 |
| `bf-cron-guard.sh`(常駐) | 不拿鎖;看 DB 鎖檔(`fuser`)、來源鎖檔(`fuser`,新)、安靜窗、flag | | 任一成立 → pause bf 容器 |

無死鎖:`daily-branches.sh` 的順序是**來源鎖(等)→ DB 鎖(等)**,等來源鎖時不握 DB 鎖;其他拿來源鎖的腳本(`warrant-backfill.sh`、`daily-warrant-branches-poc.sh`)先握 DB 鎖、再**非阻塞**拿來源鎖(拿不到就收工),所以沒有人會握著 DB 鎖等來源鎖,也沒有人會握著來源鎖無上限地等 DB 鎖(分點輪等 DB 鎖 ≤3600 s)。(反過來「先 DB 後等來源」會讓第一輪寫入時拿不到 DB 鎖、第二輪拿不到來源鎖,互等到逾時——驗證者 MED 3 的修法刻意避開。)每一次等鎖都有上限(3600 / 5400 / `LOCK_WAIT_SECS`)。沒有部分上線,所以沒有「部分與完整互相競賽」的問題;兩段式上線在同一輪、同一把鎖之下依序進行。寫 DB 的只有握著 DB 鎖的那一個程序(抓取 worker 只抓不寫)。**當天一定有人上線的保證**:第一輪抓取最晚 20:30 開始、7200 s 硬上限、寫入+上線 ~35 分 → 最晚 ~23:05 收工;第二輪 22:30 起最多等 3600 s 來源鎖(到 23:30)→ 第一輪有標記就只刷新評分、沒標記就從暫存檔續抓並接手完整鏈。測試:`tests/test_daily_branches_lock_phases.py`(對真的 lib.sh 用 stub 量:放鎖期間別的程序 `flock -n` 拿得到、`fuser` 仍看得到 fd、重新拿回;等鎖逾時;來源鎖等待版拿得到/逾時 high、非阻塞版略過;`--init`;鎖序)。

### 8.6 正式機要做的事(人類)

1. 合併後 VPS 下一輪 `sync_code` 自動拉到新腳本(舊 crontab 17:30 也正確)。
2. **改 crontab**(與 `web/lib/freshness.ts` 的 16:30 同一次上線,否則首頁時刻差 60 分):`30 17 * * 1-5 … daily-branches.sh` → `30 16 * * 1-5 … daily-branches.sh`(見 `crontab.example`);22:30 那行不變。
3. 明天核對:`grep -E '^branch-probe (at|mirror)=' ~/radar-cron.log`(各站幾點先有)、`grep -E 'step (fetch-branch-trades|import-branch-trades|compute-branch-stats|export-json|deploy) done' ~/radar-cron.log`(各段耗時)、`grep -E '^branch crawl' ~/radar-cron.log`(哪些站用上、死站)。
4. 回滾:`git revert`;`--workers 1` 即舊循序爬;`BRANCH_PROBE=0` 不探測。

### 8.8 第一次正式跑(2026-10-08)與修正

**時間線**(cron log):16:34 起探測;17:51 第一站達門檻(kgieworld 11/12,fubon 10/12);kgieworld 隨後**抖動**(18:02 1/12、18:13 0/12、18:24 10/12);fubon 18:13 就緒;masterlink、sinotrade 18:24 就緒 → 滿足 3 站門檻,**18:24 開爬**(4 站 + cathay 待命,cathay 之後通過 1 檔檢查加入)。抓取 2,788 s(46 分;估 34)、寫入 14 s、**第一段 19:28 上線**(前一天 20:12)、第二段 19:53。

| 站 | done | empty |
|---|---|---|
| fubon | 530 | 4 |
| masterlink | 548 | 4 |
| sinotrade | 538 | 0 |
| kgieworld | 534 | 3 |
| cathay(待命加入) | 453 | **98** |

**問題**:`branch_coverage` 10-08 = `expected=1958 ratio=0.9464 done=2603 empty=109`(10-07 是 1.0000 / empty=0)。cathay(可能還有抖動的 kgieworld)對**它還沒公布**的股票回 NoDataError,被當成「當天沒有分點」在第一段上線——約 100 檔分點缺了 ~3 小時(22:30 第二輪因 ratio<1 全部重爬而自癒)。一個只公布一部分的站,1 檔(待命)或 12 檔的檢查都擋不住;10-07 全市場 empty=0 也說明「合法的空」幾乎不存在,**空幾乎永遠代表「還沒公布」**。

**修正**(commit 見 STATUS):

1. **空不信單一站**(`_confirm_empties`;第四次驗證後的規則):確認用的站必須是**乾淨站**——這一輪一個 empty 都沒回過的活站(只排除回空的那一站不夠:半公布的 D 回的空會被抖動的 E 的空「確認」,驗證者重播 8 個種子有 3 個漏網),多個乾淨站時用 done 最多的。有列 → done;仍空 → 確認 empty(記 `confirmed_by`);失敗 → 換**另一個**乾淨站再試一次,仍失敗才 failed。沒有乾淨站 → 要**兩個不同的**其他站都說空;任一站有列 → done;湊不到兩站 → failed。全場只剩一個活站 → 同站再抓(文件化的限制,log 印 `self-confirm`、統計列 `self_confirmed=`)。failed 交給覆蓋率閘門、次日冪等重抓。成本 = empty 數 ×(1–2)(正常日 0–10 個請求;10-08 的情況 109 個 ≈ 2–4 分鐘)。測試:只公布一半的站回假空 → 全部救回、列與循序爬位元級相同;驗證者的重播(400 檔、D 半公布 20 假空、E 30% 抖動、3 好站)8 個種子 0 假空存活、0 真空被標 done。
2. **就緒要連續兩次**:探測 `--min-consecutive 2`(連勝數存 `data/branch-probe-state-latest.json`,內容帶日期;kgieworld 那種 11→1→0→10 不會過);待命站的檢查改用同一條規則(12 檔 ≥11)且連續兩次(每 5 分鐘一次 → 最快 10 分鐘加入);開跑前檢查抽樣 6 → 12。
3. **第一段門檻**:覆蓋率 ≥ `BRANCH_FAST_PUBLISH_MIN_RATIO`(0.98)才先上線,否則略過第一段、照舊算完排行統計一併上線(= 改動前一次上線)並 warn 講明覆蓋率。0.5 扣留地板不動。只刷新評分的第二輪一律上線。`futures_digest` 併入 `publish_site`(同一期貨日只送一次,兩次上線不會重複)。
4. **吞吐與開爬門檻**:目標不是 2,000 而是 **~2,700**(1,958 普通股 + ~740 權證),極限 = 0.2 req/s × 活站數:5 站 ~45 分、4 站 ~56 分、3 站 ~75 分、2 站 ~112 分(6,750 s)。10-08 的 46 分 = 4 站 + 晚到的第 5 站,符合。站數在爬的途中會**增**(待命站連續兩次通過加入)也會**減**(連續 5 次失敗的站退出),所以 2 站開爬對 7200 s 上限只剩 ~5% 餘裕,不夠。規則(`branch_probe_attempt`):**19:00 前要 3 站**(來源 18:00–18:50 逐站公布,10-08 第 3 站只晚第 2 站 11 分鐘;3 站爬 75 分 vs 2 站 112 分,等它比較快),**19:00 起 2 站**即可(`BRANCH_PROBE_THREE_HOSTS_UNTIL=1900`,crontab 前綴可改);抓取硬上限 7200 → **9000 s**(2 站最壞 6,750 + 開跑前檢查/重試/確認,25% 餘裕)。「當天一定有人上線」重算:第一輪最晚 20:30 開爬 + 9000 s = 23:00 抓完,寫入與第一段 ~20 分、統計與第二段 ~30 分 → 最晚 ~23:50 放來源鎖;22:30 第二輪等來源鎖的上限改 **5400 s**(到 00:00)剛好涵蓋;00:05 的夜間作業等 DB 鎖、看到標記就略過,看不到就補。
6. **跨午夜**(第五次驗證):第二輪可能等來源鎖到 00:00、再等 DB 鎖到 01:00,之後台北「今天」= D+1,舊寫法會匯入 D+1、判定「休市」、整輪靜默收工。現在 `import-daily`、休市判斷、兩個述詞(`round_prices_present`/`round_indicators_present`)、`import-futures-day`、`probe-branch-day`、`import-branch-trades --stage-to`、`compute-scores` 一律帶 `$ROUND_DATE`(開跑日 = 資料日);`compute-performance`(預設補所有缺 20 日報酬的列,帶日期反而縮成一天)、`compute-indicators --days 5`、`compute-branch-stats`、`export-json`、`prune` 不看日曆日。`taipei_date` 只剩定 `ROUND_DATE`、log 時戳、探測站數的時刻門檻、資券 21:00 判斷四處(測試鎖住)。harness 測試:開跑 10-08、時鐘 10-09 → 述詞與休市判斷都以 10-08 問庫,不誤判;預設版才會。
7. **兩活站、兩站的真空互相落到 failed**(第五次驗證可選項):**維持現狀**——那種日子覆蓋率閘門會照常放行(真空只占 ~0–0.5%),失敗的次日冪等重抓;放寬成「另一站對這檔的集合沒回過空就接受」會把 10-08 那種半公布站的空重新放進來,不值得。
8. TPEx `dailyQuotes` 的 ChunkedEncodingError(10-06、10-08 各三連發):該端點傳輸失敗改 5 次嘗試(線性 5/10/15/20 s 退避,最壞 +50 s);其他端點不變。沒有替代端點:OpenAPI 的上櫃日成交是另一份較窄的表,`dailyQuotes` 仍是唯一含權證的整表。

**預期**(來源就緒 → 分點明細可見):偵測 ≤10 分(連續兩次 → 第二次探測才算,最多 +10 分)+ 爬 45–56 分(4–5 站)+ 確認空 ~0–2 分 + 寫入 0.5 + 分數 2 + 匯出 14 + 榜 0.5 + 佈署 3 ≈ **75–90 分**;18:24 開爬的日子 → ~19:30(10-08 實測 19:28)。

### 8.7 SIGTERM 真的到得了容器:人工核對

**已於 2026-10-07 在正式機核對**(人類執行):Docker 27.1.2,`docker info` 的 InitBinary = docker-init;`docker run --rm --init radar-pipeline python -c 'import sys; sys.exit(75)'` 回傳 rc=75(`--init` 可用、離開碼經 docker-init 逐位元轉回)。本機測試只鎖 lib.sh 的文字。要再驗「TERM 真的進到 python」可跑(不碰正式 DB、不寫任何東西):

```bash
cd ~/trever-radar
docker run --rm --init --name radar-sigterm-check radar-pipeline python -c 'import signal,time; signal.signal(signal.SIGTERM, lambda *_: (print("TERM received", flush=True), exit(143))); print("ready", flush=True); time.sleep(120)' &
sleep 3; timeout --signal=TERM 5s docker attach radar-sigterm-check; docker ps --filter name=radar-sigterm-check --format '{{.Names}}'
```

預期:印出 `TERM received`,`docker ps` 沒有列出那個容器(沒有孤兒)。拿掉 `--init` 重跑,預期容器還活著(這就是驗證者抓到的洞)。
