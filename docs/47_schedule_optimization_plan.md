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
| 14:05(14:10) | `daily-market.sh` | futures_probe → 等鎖 → 每 3 分輪詢 `import-daily --datasets quotes --require twse:quotes` 至 14:40 → 彙總 → 指標 → 分數 → export → deploy |
| 14:45(15:00) | `daily-tpex-quotes.sh` | `acquire_db_lock_wait 2700` → 每 3 分輪詢 `--require tpex:quotes:0.8` 至 15:30 → 彙總 → 指標 → 分數 → export → deploy。今天上市日K不在庫(休市)→ 只試一次 |
| 16:00(16:10) | `daily-insti.sh` | 日K保底(TPEx 520 → 75 分支保留)→ 每 5 分輪詢 `--datasets insti --require twse:insti,tpex:insti` 至 17:10,每次嘗試順手 `import-futures-day`(75 下次再試、0 不再試)→ 權證主檔、庫藏股(warn-and-continue)→ 彙總 → 指標 → 分數 → export → deploy → futures_digest。**截止仍缺**:有其他變動(上櫃法人/期貨等)→ warn 並先上線已到的部分(舊 16:10 也是先上線上櫃法人;不讓它陪等到 20:30);沒有 → `publish skipped` |
| 17:30(17:40) | `daily-branches.sh` | 非交易日收工 → 等鎖 → 日K+法人(保底)→ 期貨當日(法人輪已拿到就略過)→ 指標 → seed → **探測迴圈**(放 DB 鎖)→ 重新等鎖 → 全量爬 → 分級 → 分點統計 → 已過 21:00 順手匯入資券 → 分數 → 績效 → export → prune → deploy → 完成標記(含 `coverage_ratio=`) |
| 20:45(21:20) | `daily-margin.sh` | 非交易日收工;資券已是今天(分點輪帶入)→ 收工;`acquire_db_lock_wait 5400` → 再查一次 → 每 5 分輪詢 `--datasets quotes,margin --require twse:margin,tpex:margin` 至 22:15 → import-futures(官方覆核)→ 分數 → 績效 → export → deploy;落後補抓分支保留 |
| 22:30(22:00) | `daily-branches.sh`(`BRANCH_ROUND_MODE=import`) | 原則 3 |
| 00:05(不變) | `safe-branch-stats.sh` | 既有守衛 + 前一日非交易日收工;PIT 或分位計數有算出 → export + deploy(不再跳過 export);evening ok 且兩者都沒有 → 不 export 也不 deploy |

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
