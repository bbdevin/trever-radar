# 43 — `branch_trades_raw`／`daily_prices` 改 WITHOUT ROWID:離線轉換維護窗 runbook

> 狀態(2026-10-04):**準備完成,尚未執行**。工具、測試、程式修正都在 repo;維護窗、正式庫下載／換檔
> 由使用者批准後才做(AGENTS.md「仍須人工確認」:schema migration、資料重建、VPS destructive 操作)。
> Planner 2026-10-04 定案最終版面(`_date_cover` 覆蓋索引＋`--analyze`)並 GO;是否換檔以 §6.1 閘門 G0–G7 為準。
> 合成資料提醒:ANALYZE 之後 planner 在合成庫上把 b4 評分 20 日窗改走 `ix_branch_trades_raw_branch`(不走 `_date_cover`),
> verify 的計畫檢查與 bench G2 都會擋下;正式庫的統計不同,以 P2 實測為準(§10)。
>
> **單一寫者例外(使用者 2026-10-03 核准)**:這次在 Windows PC 上離線寫出一份新的 `radar.db`。
> 只在 VPS 全程握著 `/tmp/radar-db.lock`、所有寫者都停住時進行;PC 上產生的檔案在換上 VPS 之前
> 不是正式庫,換上之後 PC 不再保有任何寫入路徑。除此之外 `docs/31` 的「VPS 單一寫者」不變。

## 0. 一頁摘要

| 項目 | 內容 |
|---|---|
| 目的 | 磁碟:VPS 不能擴充,`radar.db` 9.03 GB、剩 3.4 GB。把兩張最大的表改成依主鍵聚集的 WITHOUT ROWID,PK 自動索引與 1.33 GB 覆蓋索引消失,檔案重排壓緊 |
| 轉換的表 | `branch_trades_raw`(32,378,591 列,PK `stock_id,date,branch_id`)、`daily_prices`(10.28M 列,PK `stock_id,date`);`--tables` 可只轉其一 |
| 最終索引(Planner 2026-10-04 定案) | `branch_trades_raw`:PK(表本身)、**`ix_branch_trades_raw_date_cover (date, stock_id, branch_id, buy_lots, sell_lots, net_lots, pct)`**(新;依日期連續的完整副本,日期切片只讀索引)、`ix_branch_trades_raw_branch (branch_id, date)`(保留)。`daily_prices`:PK(表本身)、`ix_daily_prices_date`(保留,不加覆蓋) |
| 拿掉的物件 | `ix_branch_trades_raw_stock_cover`(1.33 GB)、`ix_branch_trades_raw_date`(0.73 GB,被 `_date_cover` 取代)、兩張表的 `sqlite_autoindex_*_1`(PK 自動索引;`branch_trades_raw` 那個 1.55 GB、42% 空洞) |
| 生產變體 | `--page-size 4096 --analyze`(覆蓋索引預設開啟);`--no-cover` 只做比較用 |
| 程式 | `radar/db.py` 每條連線 `PRAGMA cache_size=-65536`(64 MiB;只改這一項) |
| 預期大小 | Planner 實測後估 6.0–6.5 GB(含覆蓋索引)。以轉換工具印出的實數為準(§6 P2) |
| 資料 | 逐表逐列 SHA-256(主鍵順序)、列數、DDL(只差 ` WITHOUT ROWID`)全部比對;`integrity_check` ok |
| 功能 | 同一份程式碼對新舊兩個檔案:完整 `export-json`(約 3,580 檔)逐位元比對;夜間計算鏈(指標／分點統計／PIT／分位／評分)在兩份副本上各跑一次,逐表比對 |
| 維護窗 | 週六 07:30 → 週一 14:10(§4)。實作業約 8–12 小時 |
| 傳輸 | **不用 Google Drive**(只剩 2.4 GiB)。VPS 與 PC 之間用 `ssh trever-vps` 的 scp |

## 1. 為什麼可以、哪裡會變

* **資料不變**:轉換只是換 B-tree 的組織方式。每一列、每一欄、儲存型別(5 / 5.0 / '5' 不同)都由
  `verify_db_equivalence.py` 證明相同;其餘 rowid 表連 rowid 都保留(隱含順序不變)。
* **WITHOUT ROWID 的已知副作用(稽核結果)**:
  1. 次要索引的尾端由 rowid 變成 PK 欄:`ix_*_date` 實際上變成 `(date, stock_id[, branch_id])`。
     **同一天內**的列,沒有 ORDER BY 時以前是「寫入順序」,之後是「代號順序」。
  2. 沒有任何程式讀 rowid／`_rowid_`／`oid`、`last_insert_rowid`、`INSERT OR REPLACE`、
     `sqlite_sequence`、`INDEXED BY`(全 repo grep;web/ 與 Worker 不讀 SQLite)。唯一的 `SELECT rowid`
     在 `.github/workflows/data-backfill.yml:160`,是對子查詢取 rowid、且該 workflow 已退役。
  3. `radar.db.upsert` 用 `ON CONFLICT (主鍵) DO UPDATE`:WITHOUT ROWID 一樣支援(測試全過)。
  4. WITHOUT ROWID 的 PK 欄禁止 NULL;兩張表的 PK 欄本來就是 NOT NULL,轉換工具仍先檢查。
* **原則(使用者硬性要求)**:程式上線後,計算與匯出的結果必須只由**資料**決定,與列的實體順序無關。
  因為 1.,先把所有「依賴讀取順序」的地方改成明確的全序或與順序無關的規則。改動清單、理由與
  「相對現行 HEAD 會變的值」見 §1.1;新舊兩個檔在新程式下的計算與匯出逐位元相同(§10)。
* **效能的取捨**:依股票讀變快;依日期切的全市場讀變慢(§10)。

### 1.1 為了「與順序無關」做的程式修正

| 位置 | 原本依賴什麼 | 現在的規則 | 相對 HEAD 何時會變 |
|---|---|---|---|
| `scores.py` B1 連買(挑最強分點)——**評分規則修正,使用者 2026-10-04 核准**(「可以優化邏輯的,不一定要一致」;`docs/04` §2 已註記) | 兩兩比較「天數多**或**張數多就換」,不具遞移性;誰被選中(20／30 分)取決於候選的先後 | 全序:連買天數 ↓、累計張數 ↓、佔比 ↓、`branch_key` ↑ 取第一(給分只看天數,所以天數優先) | 同日有 ≥2 個分點合格且舊規則選到非最強者時;隨機無同值案例 20,000 例中 43 例 B1 輸出變、24 例分數變(多為 20→30)。B2/B3/B6 與反手扣分在無同值時與 HEAD 逐值相同(測試 3,000 例) |
| `scores.py` B2 名單排序 | 同張數時的列序 | `(張數 ↓, branch_key)` | 同張數 |
| `scores.py` 反手倒貨扣分(昨日前 5 大) | `sorted(張數)[:5]` 同張數時的列序 | `(張數 ↓, branch_key)` | 第 5 名同張數 |
| `pocket.py` 追蹤分點同買前 3 名 | dict 插入順序 | `(張數 ↓, 名稱)` | 同張數 |
| 分點名稱為單位的計算:`compute_branch_stats.py`、`branch_ranking_v2_shadow.py`、`branch_stock_pctile_counts.py`、`branch_point_in_time_persist.py`、`branch_point_in_time_report.py`、`branch_window_direction_battery.py` | 同一名稱有多個 `branch_key`(不同來源頁、改名合併)同日都有列時:有的「留最後一列」(誰最後取決於讀取順序),有的「每列各判一次」(同一天算兩次合格) | **同名同日加總**(`radar/compute/branch_same_day.py`):張數相加;pct 是「淨買超 ÷ 當日成交值」,分母相同所以相加後仍與合計淨買超一致(平均或取最大會讓 pct 與 net 對不起來);全為 NULL 才是 NULL;浮點用 `math.fsum`(與順序無關)。只有一列的日子數值原封不動 | 只在「同名同日多列」的日子;正式庫件數用 §3 的 SQL 先數 |
| 上述掃描的 SQL | `ORDER BY stock, name, date` 同值時 | 加 `, b.branch_key`(串流順序明確;值已由上一列的加總規則決定) | 不變 |
| `json_export.py` 權證當日分點 top-8 | 同張數時的寫入順序(可能換掉第 8 名) | SQL `ORDER BY stock_id, branch_key` 後穩定排序 | 同張數 |
| `json_export.py` `branches/today.json` | `ORDER BY branch_name, net_lots DESC` 同值時 | 加 `, stock_id, branch_key` | 同值 |
| `json_export.py` 主查詢(radar.json 各榜單同分先後) | `daily_prices` 當日列的寫入順序(上市先、上櫃後) | `ORDER BY p.stock_id` | 榜單同分 |
| `indicators.py`／`adjustments.py`／`importer.py` 依成交額取前 N 檔 | `ORDER BY turnover DESC LIMIT n` 同成交額 | 加 `, stock_id` | 第 N 名同成交額 |
| `json_export.py` 個股 `branches`(當日分點) | `ORDER BY net_lots DESC` 同值時靠索引走訪順序 | 直接 join `branch_trades_raw`,`ORDER BY net_lots DESC, branch_id`(= 以前走 PK 的自然順序) | **不變**(合成資料新舊程式逐位元相同) |
| `json_export.py` 個股 `branch_history`(每日前 12) | `ORDER BY date DESC` 後依 \|net\| 穩定排序,同值時靠倒走索引的順序 | `ORDER BY date DESC, branch_id DESC`(= 以前倒走索引的自然順序) | **不變** |
| `json_export.py` 權證分點金額(`breakdown`／`daily`,7 處) | 浮點 `SUM(net × 1000 × close)` 的結果隨加總順序差最後一位,`int()` 後差 1 元 | 整數加總 `net × CAST(ROUND(close × 1000) AS INTEGER)`(權證價 ≤ 3 位小數,等於真值) | 以前被截斷少 1 元的地方 |

**全市場日期窗讀取改走覆蓋索引**(2026-10-04):`scores.py` 評分 20 日窗與 `pocket.py` 口袋窗改讀
`branch_trades_raw r JOIN branch_dim d`(與 `branch_trades` view 同一個 join,列與值相同),新版面上加
`INDEXED BY ix_branch_trades_raw_date_cover`;舊版面(沒有這個索引)自動用不加提示的 join(`radar/branch_source.py`)。
原因:ANALYZE 之後 planner 會改走 `branch_dim`＋`_branch`。合成資料:b4／b7 讀取量 0.55×、compute/export parity PASS、
兩種版面同列(單元測試)。

**已知殘留(刻意不改)**:`_export_tracked_branch_history` 的 `AVG(b.pct)` 在同名同日 ≥3 個 branch_key 時,
浮點平均的最後一位與加總順序有關。改成 SUM 會改變追蹤明細 pct 的意義,而正式庫目前沒有這種組(Planner 實測 0);
保留現狀,§3 的計數 SQL 若出現 >0 再處理。

稽核過、**不需要改**的(都與順序無關或已是全序):`scores.py` 價格／成交量／法人讀取(以 `(股, 日)` 為鍵的 dict)、
`buy_concentration`(前 5 大加總,同張數換人總和不變)、`pocket.py` 地緣觸發(名稱排序、加總)、
`next_day_*_battery.py` 價格(以 `(股, 日)` 為鍵)、`indicators.py`／`performance.py`／`futures_*` 逐檔或
`ORDER BY stock_id, date`、各 `GROUP BY` 聚合(整數加總;選出的欄都在 GROUP BY 內)、
`importer.py:1497/1525`(`daily_scores`／`warrant_daily` 不在這次轉換)。

`PYTHONHASHSEED`:約 100 個 `branches/track/*.json` 的物件鍵順序每個程序都不同(以字串 set 建 dict)。
這是既有現象、與轉換無關、不改值;比對工具固定 seed、manifest 忽略物件鍵順序。

## 2. 工具(都在 `pipeline/tools/`)

| 檔案 | 用途 | 依賴 |
|---|---|---|
| `convert_branch_raw_without_rowid.py SNAP OUT [--tables …] [--page-size 4096\|8192] [--analyze] [--no-cover]` | 唯讀＋immutable 開快照;輸出不存在才做;先建 `OUT.partial`,全部成功才 rename;依 PK 首欄分批、PK 順序寫入;拿掉舊 `_stock_cover`／`_date`、在其他索引之後建 `_date_cover`(DDL 與 SQLAlchemy 為 schema.py 產生的逐字相同,測試釘住);印進度與耗時;最後 VACUUM INTO、設 WAL | 只要 python3 標準庫 |
| `verify_db_equivalence.py OLD NEW [--expect-page-size N] [--no-cover]` | §0 的資料比對;`_date_cover` 只能在 NEW 且 DDL 逐字相同;查詢計畫檢查(b3 權證當日、b4 評分 20 日必須 `COVERING INDEX …_date_cover`,b4 不得走 `_branch`,c1 追蹤明細不得 `SEARCH r USING INDEX …_branch`);PASS/FAIL 與離開碼 | 標準庫 |
| `verify_db_equivalence.py DB --single` | VPS 換檔後:integrity／quick_check、WAL、兩表 WITHOUT ROWID、`_date`／`_stock_cover` 不在、`_date_cover` 在、`sqlite_stat1` 涵蓋兩表、查詢計畫 | 標準庫 |
| `export_parity.py OLD NEW --work DIR` | 兩個子程序各跑完整 `export_json`(引擎唯讀 immutable、`init_db` 停用、`PYTHONHASHSEED=0`),逐檔比對;另有 `--export-one`、`--manifest`、`--compare-manifests`、`--dirs`、`--old-code/--new-code` | pipeline venv |
| `compute_parity.py OLD NEW --work DIR` | 兩份**副本**上各跑夜間計算鏈(真的 CLI),再逐表比對(主鍵順序 SHA-256,略過 `*_at` 時間戳;不同時列出只在舊／只在新／內容變更的列數);`--old-code/--new-code` 可量「純程式改動」造成的差 | pipeline venv |
| `bench_branch_raw.py OLD --variant 名=路徑 …` | 舊 vs 各變體:a 依股票、b 依日期、c 依分點、d 寫入(temp 副本)、e 完整匯出;2 MB 快取;distinct KiB = 冷碟讀取量;>2× 自動試 `INDEXED BY`/`NOT INDEXED` 並下結論 | pipeline venv |
| `make_synthetic_branch_db.py OUT` | 正式版面的合成庫(rowid 表＋覆蓋索引、逐日附加、上市先上櫃後、同名多 branch_key 同日),演練用 | pipeline venv |
| `tests/test_branch_raw_without_rowid_tools.py`、`tests/test_order_independence.py` | 轉換／驗證的正反例;B1、反手扣分、同名同日加總在所有排列下結果相同 | pytest |

`vps/scripts/build-branch-cover-index.sh` 已標為作廢(預設直接結束)。

## 3. 前置條件(維護窗之前完成)

1. **程式先上線、在舊檔上跑幾天**:本次 commit(schema 宣告、§1.1 的順序修正、`export timing:` log)照一般流程
   push → VPS 每輪 `sync_code` 自動拉。新程式在舊檔上也能跑(`create_all` 不改既有表);跑過至少一個完整
   交易日、`export timing:` 有出現在 `~/radar-cron.log`,再進維護窗。PC 上的轉換、比對都用**同一個 commit**。
   §1.1 的值變動在這一步就發生(與轉換無關);先在 VPS 唯讀數一下同名同日多列的件數:

   ```bash
   docker run --rm -v ~/trever-radar/data:/app/data radar-pipeline python -c "import sqlite3; c=sqlite3.connect('file:/app/data/radar.db?mode=ro', uri=True); print(c.execute('SELECT COUNT(*), COALESCE(SUM(n),0) FROM (SELECT COUNT(*) n FROM branch_trades_raw r JOIN branch_dim d ON d.id=r.branch_id GROUP BY r.stock_id, r.date, d.branch_name HAVING COUNT(*)>1)').fetchone())"
   ```
2. PC:`D:` 至少 80 GB 空間(快照 9 GB＋2 個變體約 13 GB＋bench 副本約 22 GB＋compute_parity 兩份副本約 15 GB＋數份匯出);
   `cd D:\code\stock\pipeline; .\.venv\Scripts\python.exe -m pytest -q tests/test_branch_raw_without_rowid_tools.py tests/test_order_independence.py` 全過;
   `ssh trever-vps "echo ok"` 可連。
3. VPS:記下 `df -B1 ~/trever-radar/data`、`ls -ld ~/trever-radar/data; ls -l ~/trever-radar/data`、
   `docker ps -a`、`crontab -l`。`data/` 目錄須屬於登入帳號(刪檔、`mv` 只看目錄權限);若屬 root,§6 的
   `rm`／`mv`／`gunzip >` 改用 `docker run --rm -v $REPO/data:/app/data radar-pipeline sh -c '…'` 執行。
4. **工作目錄放 `~/wor`,不放 `/tmp`**:`/tmp` 可能是 tmpfs(吃記憶體,1.7 GB 的機器放不下 1.5 GB 的 gz)。
   `mkdir -p ~/wor && df -h ~/wor ~/trever-radar/data` 兩行必須是同一個實體磁碟、不是 `tmpfs`。
5. 確認 Drive 上有 2026-10-03 05:00 的週備份(最後一道保險;不參與這次傳輸)。

## 4. 維護窗:週六 07:30 → 週一 14:10

這段時間會碰資料庫的排程與它們遇到「鎖被佔」時的行為:

| 排程 | 時間 | 遇到鎖 |
|---|---|---|
| `weekly-backup.sh`／`weekly-tdcc.sh` | 週六 05:00／06:30 | 窗口開始前應已跑完;`weekly-tdcc` 只在**開始時**用 `fuser` 看鎖,07:30 若還在跑,V1 的 flock 會等它放鎖 |
| `mid-backfill-publish.sh` | 每天 03/09/12/20 | **只在開始時** `fuser` 看鎖 → 略過;若在 V1 之前已開始,會跑完(約 11–13 分)——V1 前先 `pgrep -af mid-backfill-publish` 確認沒有在跑 |
| `data-backfill.sh` | 每天 01:10 | `flock -n` 失敗 → 略過(ntfy「略過」) |
| `backfill-margin.sh` | 週日 02:30 | 開始時 `fuser` → 略過 |
| `monthly-directors.sh` | 每月 16 日 07:00 | 開始時 `fuser` → 略過(窗口若落在 16 日,事後手動補跑) |
| `safe-branch-stats.sh` | 週二–六 00:05 | 窗口內不會觸發 |
| 平日 `daily-*` | 週一 14:10 起 | 窗口必須在此之前結束 |
| `bf-cron-guard.sh`／`bf-supervisor.sh` | 常駐 | 看到鎖 → pause／hold,不新開容器 |
| `disk-cleanup.sh` | 每天 07:40 | 不碰 `radar.db`;但 `docker container prune -f` 會**刪掉** V2 停下的回補容器——放鎖後 `bf-supervisor` 走 `missing` 分支用 `start_job` 重新開一個(回補可續跑),不是「重啟」 |
| 盤中 `radar-worker` | 平日 08:50 | 不掛 data/,不碰資料庫 |

只在開始時看鎖的幾支,一旦開跑就會一路寫到結束。所以真正的關卡是 V3:`docker ps` 沒有任何
`radar-pipeline` 容器在跑,而且 `wal_checkpoint(TRUNCATE)` 的第一個數字是 0(沒有其他連線卡住)。

## 5. 磁碟算術(VPS,單位 GB)

| 時點 | 佔用 | 可用 |
|---|---|---|
| 開始 | radar.db 9.03 | 3.4 |
| V4 建快照 gz(約 2.1) | +2.1 | ≈1.3 |
| P1 之後:PC 確認快照 sha256 → 刪快照 gz | −2.1 | ≈3.4 |
| V4b 舊檔基準匯出 `~/wor/export_old`(約 1.13)→ manifest → 刪匯出 | +1.13 −1.13 | ≈2.3 → 3.4 |
| P3 上傳新檔 gz(約 1.5),**在 VPS 上驗 gz 的 sha256** | +1.5 | ≈1.9 |
| V5 刪舊 `radar.db*` | −9.03 | ≈10.9 |
| V5 解壓新檔(6.0–6.5),驗 sha256,刪 gz | +6.5 −1.5 | ≈5.9 |
| V5 新檔匯出 `~/wor/export_new`(約 1.13)→ manifest → 比對 → 刪匯出 | +1.13 −1.13 | ≈4.8 → 5.9 |

新舊檔**不可能同時**放在 VPS,所以「換檔」等於「刪舊放新」。刪舊之前必須:(1) PC 上有兩份已驗證的舊檔
(快照 gz＋解壓後 sha256 相符的原檔);(2) 新檔的 gz 已在 VPS 上、sha256 相符。Drive 的週六 05:00 備份是
第三份,但少了 06:30 TDCC 的寫入。

## 6. 步驟

以下 VPS 指令在 `ssh trever-vps` 裡跑。先貼上這幾個小工具(與 `weekly-backup.sh` 同法,用管線映像的
python 跑 SQL,主機不需 sqlite3):

**SSH 斷線重連後,這一段要重新貼一次**(`$REPO`、`$W`、`db_sql`、`tool` 都只活在該 shell 裡;
鎖由背景的 `flock` 持有,斷線不影響)。

```bash
REPO=~/trever-radar; W=~/wor; mkdir -p "$W"
db_sql() { docker run --rm -v "$REPO/data":/app/data radar-pipeline \
  python -c "import sqlite3,sys; c=sqlite3.connect('/app/data/radar.db'); [print(*r) for r in c.execute(sys.argv[1])]" "$1"; }
tool() { docker run --rm -v "$REPO/pipeline":/app/pipeline -v "$REPO/data":/app/data \
  -v "$REPO/web/public/data":/app/web/public/data:ro -v "$W":/wor radar-pipeline python "tools/$1" "${@:2}"; }
SPARK=$([ -f "$W/spark_day.json" ] && echo "--spark-cache /wor/spark_day.json")   # V4b 之後才有意義
```

### V1 拿鎖(5 分鐘;若剛好有一輪在跑,等它結束)

```bash
pgrep -af 'mid-backfill-publish|weekly-tdcc|monthly-directors|backfill-margin' || echo "none running"
nohup flock /tmp/radar-db.lock sleep infinity >/dev/null 2>&1 &
LOCKPID=$!; sleep 2
SLEEPPID=$(pgrep -P "$LOCKPID" sleep); echo "flock=$LOCKPID sleep=$SLEEPPID" | tee ~/wor-lock.pids
```

* `sleep=` 有數字 = 已拿到鎖(flock 拿到鎖才會啟動它)。
* **`sleep=` 是空的** = 有一輪正握著鎖,flock 還在等。不要往下做:等幾分鐘再跑
  `pgrep -P "$LOCKPID" sleep`,有數字後重寫 `~/wor-lock.pids`;或 `kill $LOCKPID` 放棄、稍後重來。
* 釋放時**殺 sleep 那個 PID**(flock 隨之結束、鎖釋放);只殺 flock 的話,sleep 會繼續持有鎖。

### V2 停下回補容器(2 分鐘)

```bash
docker stop radar-bf-branches radar-bf-warrant 2>/dev/null
docker ps            # 不得有任何 radar-pipeline 映像的容器在跑(沒有 filter,全部列出)
sudo -n fuser -v $REPO/data/radar.db $REPO/data/radar.db-wal 2>&1 || echo "(無 sudo:以 docker ps＋V3 的 busy=0 為準)"
```

* 用 `stop` 不用 `pause`:暫停的容器仍開著舊檔的 fd 與 `-wal`/`-shm`,換檔後恢復就會寫進已刪除的舊檔(資料默默遺失)。
* 一般帳號的 `fuser` 看不到 root 容器內的程序,所以它的「空」不算數;能用 `sudo` 就用,不能就以 `docker ps`
  ＋ V3 checkpoint 的 busy=0 為準。
* 07:40 的 `disk-cleanup.sh` 會把停下的容器刪掉;放鎖後 `bf-supervisor` 會重新開(§4),會收到一則 ntfy,屬預期。

### V3 checkpoint＋完整性＋基準數字(20–40 分鐘)

```bash
docker ps --format '{{.Image}} {{.Names}}' | grep radar-pipeline && echo "STOP: 還有容器在跑"
db_sql "PRAGMA wal_checkpoint(TRUNCATE)"          # 必須是「0 x x」:第一個數字 0 = 沒有別的連線卡住
ls -l $REPO/data/radar.db-wal                      # 必須是 0 bytes 或不存在
db_sql "PRAGMA integrity_check"                    # 必須只有 ok
db_sql "SELECT (SELECT COUNT(*) FROM branch_trades_raw), (SELECT COUNT(*) FROM daily_prices)"
db_sql "PRAGMA page_count"; db_sql "PRAGMA freelist_count"
```

### V4 快照壓縮＋sha256(15–25 分鐘)

```bash
STAMP=$(TZ=Asia/Taipei date +%Y%m%d)
cd $REPO/data
sha256sum radar.db | tee $W/old.sha256
gzip -c radar.db > wor-snapshot-$STAMP.db.gz      # 約 2.1 GB
sha256sum wor-snapshot-$STAMP.db.gz | tee -a $W/old.sha256; df -h .
```

檔名刻意不用 `radar-*.db.gz`:`weekly-backup.sh` 成功後會 `rm -f data/radar-*.db.gz`。

### P1 PC 下載＋驗證(10–30 分鐘,看 VPS 上傳頻寬)

```powershell
New-Item -ItemType Directory -Force D:\wor | Out-Null; cd D:\wor
scp trever-vps:trever-radar/data/wor-snapshot-YYYYMMDD.db.gz .
scp trever-vps:wor/old.sha256 .
scp trever-vps:trever-radar/data/spark_day.json .     # export 的非資料庫輸入(§6 V4b);沒有這個檔就略過
(Get-FileHash .\wor-snapshot-YYYYMMDD.db.gz -Algorithm SHA256).Hash.ToLower()   # 對 old.sha256 第二行
python -c "import gzip,shutil,sys; s=gzip.open(sys.argv[1]); d=open(sys.argv[2],'wb'); shutil.copyfileobj(s,d,16<<20); d.close()" wor-snapshot-YYYYMMDD.db.gz old.db
(Get-FileHash .\old.db -Algorithm SHA256).Hash.ToLower()                        # 對 old.sha256 第一行
```

兩個 sha256 都相符才繼續。**`wor-snapshot-*.db.gz` 保留到 §7 的刪除條件成立**。

### V4b 舊檔的基準匯出(VPS,同一個映像;15–30 分鐘)

匯出比對的判準必須是「**同一台機器、同一個映像、同一份程式、同樣的非資料庫輸入**」產生的新舊兩份匯出
(PC 與容器的 Python／SQLite 版本不同,不能拿 PC 的匯出去比 VPS 的)。export_json 讀的非資料庫輸入
(`python tools/export_parity.py --list-inputs` 印出全表):

1. `data/spark_day.json`(盤中分時快取)——兩次都餵**同一份副本**(`--spark-cache`);
2. `FUGLE_API_KEY`＋台北日期(有 key 且今天=價格日時會連網抓分時並改寫快取)——工具一律拿掉 key;
3. `pipeline/radar/data/company_groups.json`(repo 檔,同一個 commit);
4. 牆鐘——只影響 `generated_at`(比對時忽略);
5. `PYTHONHASHSEED`——工具固定為 0。

```bash
rm -f $REPO/data/wor-snapshot-*.db.gz && df -h $REPO/data         # PC 已驗過、留有兩份
cp $REPO/data/spark_day.json $W/spark_day.json 2>/dev/null || echo "no spark cache (both exports run without it)"
SPARK=$([ -f $W/spark_day.json ] && echo "--spark-cache /wor/spark_day.json")
tool export_parity.py /app/data/radar.db --export-one /wor/export_old $SPARK
tool export_parity.py --manifest /wor/export_old /wor/old-manifest.json
du -sh $W/export_old; docker run --rm -v "$W":/wor radar-pipeline rm -rf /wor/export_old /wor/export_old.datadir
df -h $REPO/data
```

### P2 轉換、比對、量測(PC,3–6 小時;轉換可兩個平行)

```powershell
cd D:\code\stock\pipeline; $py = ".\.venv\Scripts\python.exe"
& $py tools\convert_branch_raw_without_rowid.py D:\wor\old.db D:\wor\new_cover.db --page-size 4096 --analyze           # 生產
& $py tools\convert_branch_raw_without_rowid.py D:\wor\old.db D:\wor\new_plain.db --page-size 4096 --analyze --no-cover # 只做比較
& $py tools\verify_db_equivalence.py D:\wor\old.db D:\wor\new_cover.db                     # G3
& $py tools\verify_db_equivalence.py D:\wor\old.db D:\wor\new_plain.db --no-cover
& $py tools\verify_db_equivalence.py D:\wor\new_cover.db --single
& $py tools\bench_branch_raw.py D:\wor\old.db --variant cover=D:\wor\new_cover.db --variant plain=D:\wor\new_plain.db `
      --write --tmp D:\wor\bench_tmp --export --work D:\wor\bench_exports --json D:\wor\bench.json *> D:\wor\bench.txt   # G1 G2 G4 G5
& $py tools\export_parity.py  D:\wor\old.db D:\wor\new_cover.db --work D:\wor\parity --parallel --self-check `
      --spark-cache D:\wor\spark_day.json        # 沒有 spark_day.json 就拿掉這個參數(早期 G6)
& $py tools\compute_parity.py D:\wor\old.db D:\wor\new_cover.db --work D:\wor\cparity    # G7
```

* 每個 `verify` 必須 `RESULT: PASS`;選定變體的 `export_parity` 與 `compute_parity` 都必須 `RESULT: PASS`(離開碼 0)。
  兩者都在 PC 上同一個 Python 下跑新舊兩邊,所以可比;它們是**早期關卡**,正式判準是 V5 在 VPS 上的 manifest 比對。
  出現 ORDER-ONLY/VALUE/FAIL → **停止**,把報告交 Planner,修程式後重來(維護窗可直接中止,見 §8)。
* `bench.txt` 末段「閘門」一節對 `cover` 必須全 PASS(§6.1);`plain` 只供對照。
* 數字填進 §9 與 `docs/STATUS.md`。

### 6.1 閘門 G0–G7(任一不過 → 不換檔,走 §8)

| 閘門 | 內容 | 在哪裡檢 |
|---|---|---|
| G0 | VPS 刪舊庫前重算 `radar.db` 的 sha256 = `old.sha256` 第一行,且 `-wal` 不存在或為空 | V5 第一段 |
| G1 | 逐檔讀(新/舊 distinct KiB):a2 個股 branch_history、a5 K 線全歷史、a6 K 線 600 根 ≤ 0.35×;a1 分點統計逐檔、a4 v2 shadow ≤ 1.10× | bench「閘門」 |
| G2 | 每個案例:distinct KiB ≤ 1.10×舊＋256 KiB,且中位 ms ≤ max(1.25×舊, 舊＋50 ms);b3 b4 b5 b6 b7 b9 c1 c2 在 2 MB 快取下重讀 KiB ≤ 1.5×舊 | bench「閘門」 |
| G3 | 資料等價:`verify` PASS(含 `_date_cover` DDL 與計畫檢查),`--single` PASS | P2 |
| G4 | 完整 export:新秒數 ≤ 0.60×舊;`export timing:` 各段(write 除外,兩邊都 <1 s 的段略過)≤ 1.25×舊 | bench `--export` |
| G5 | 寫入:每個 upsert 步驟 ≤ 2.0×舊 | bench `--write` |
| G6 | 匯出逐檔相同:PC `export_parity` PASS(早期);**VPS 同映像 V4b/V5 manifest 比對 PASS(判準)** | P2、V5 |
| G7 | 計算逐表相同:`compute_parity` PASS | P2 |

G1/G2/G4/G5 由 `bench_branch_raw.py` 自動判定並列出每一條失敗;G3/G6/G7 看各工具的 `RESULT:` 與離開碼。
(G3、G6、G7 的編號與內容是執行者依 Planner 的閘門清單補齊的,Planner 可再調整。)

### P3 上傳新檔(20–40 分鐘)

PC 壓縮新檔、寫 sha256(**不要用 `Set-Content`**:它會加 CRLF,VPS 的 `sha256sum -c` 會失敗):

```powershell
python -c "import gzip,shutil,sys; s=open(sys.argv[1],'rb'); d=gzip.open(sys.argv[2],'wb',6); shutil.copyfileobj(s,d,16<<20); d.close()" D:\wor\new_cover.db D:\wor\new.db.gz
$h = (Get-FileHash D:\wor\new_cover.db -Algorithm SHA256).Hash.ToLower()
$g = (Get-FileHash D:\wor\new.db.gz -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("D:\wor\new.sha256", "$h  radar.db.tmp`n$g  new.db.gz`n")   # LF、無 BOM
```

**不要**在 Windows PowerShell 5.1 用 `|` 把二進位串流接到 `ssh`(它會轉碼毀檔);一律 scp 檔案。

上傳(快照 gz 已在 V4b 刪掉),**在刪舊庫之前**於 VPS 驗新 gz:

```powershell
scp D:\wor\new.db.gz D:\wor\new.sha256 trever-vps:wor/
```

```bash
cd $W && tr -d '\r' < new.sha256 > new.sha256.lf && grep ' new.db.gz$' new.sha256.lf | sha256sum -c -   # 必須 OK
```

### V5 換上新檔＋檢查(40–70 分鐘)

只在上一步 `new.db.gz: OK` 之後。刪舊庫前**再確認一次**它就是 PC 手上那份(期間沒有任何寫入):

```bash
cd $REPO/data
[ ! -s radar.db-wal ] && echo "wal empty/absent" || echo "STOP: radar.db-wal 不是空的——有東西寫過"
tr -d '\r' < $W/old.sha256 | head -n 1 | sha256sum -c -                # 必須 radar.db: OK
rm -f radar.db radar.db-wal radar.db-shm && df -h .
gunzip -c $W/new.db.gz > radar.db.tmp
grep ' radar.db.tmp$' $W/new.sha256.lf | sha256sum -c -                 # 必須 OK
mv radar.db.tmp radar.db && rm -f $W/new.db.gz && df -h .
tool verify_db_equivalence.py /app/data/radar.db --single               # integrity/quick_check/WAL/計畫,必須 PASS
tool export_parity.py /app/data/radar.db --export-one /wor/export_new $SPARK
tool export_parity.py --manifest /wor/export_new /wor/new-manifest.json
tool export_parity.py --compare-manifests /wor/old-manifest.json /wor/new-manifest.json   # 判準:必須 PASS
tool export_parity.py --dirs /app/web/public/data /wor/export_new --only-in-old-ok       # 參考:與現行線上檔比
```

判準是 `--compare-manifests`:同一個映像、同一份程式、同一份 spark 快取,舊檔(V4b)與新檔的匯出必須逐檔相同
(物件鍵順序與 `generated_at` 除外)。最後一行與線上檔比只是參考:線上檔是窗口前最後一次匯出,之後若回補容器
寫過歷史列,會出現合理的 VALUE 差。不過 → 不要放鎖,走 §8「放鎖之前」回滾。

### V6 放鎖、跑一輪(10 分鐘＋一輪)

```bash
SLEEPPID=$(sed -n 's/.*sleep=\([0-9][0-9]*\).*/\1/p' ~/wor-lock.pids)
[ -n "$SLEEPPID" ] && kill "$SLEEPPID" || echo "STOP: ~/wor-lock.pids 沒有 sleep PID,用 pgrep -af 'sleep infinity' 找"
sleep 1; flock -n /tmp/radar-db.lock true && echo "lock released"
docker run --rm -v "$W":/wor radar-pipeline rm -rf /wor/export_new /wor/export_new.datadir   # 容器以 root 寫入,用容器刪
nohup bash $REPO/vps/scripts/daily-market.sh >> ~/radar-cron.log 2>&1 &  # 非交易日 import 安全空跑,其餘照跑並上線
```

週日另可手動跑一次 `safe-branch-stats.sh`(重算同一個 as_of,PK 覆蓋)量重型計算在新版面的耗時。

### V7 換檔後觀察(週一起 5 個交易日)

```bash
grep -E '^step (export-json|compute-branch-stats|branch-point-in-time-persist|branch-stock-pctile-counts|compute-scores) (start|done)|^export timing:' \
  ~/radar-cron.log | tail -n 200
```

把換檔後前幾輪的 `step export-json done … elapsed=` 與前 5 個交易日比;`export timing:` 各段
(branch_history／candles／pctile／pnl／warrant_shards／tracked／write)看是哪一段變了。任何一步慢超過 2 倍 → 回報 Planner。

## 7. 刪除舊檔的條件

舊檔在 VPS 上換檔時就已刪除;這裡講的是 PC 上的 `wor-snapshot-*.db.gz`／`old.db`:

1. 換檔後至少一個完整交易日:14:10、15:00、16:10、17:40、21:20、22:00 各輪與隔日 00:05 `safe-branch-stats` 都成功上線;
2. V5 的 manifest 比對(舊檔 V4b vs 新檔)PASS;
3. 人工看站:個股頁(4967、6488、2330、8299、3105)K 線／籌碼日報／權證分頁、分點頁、radar 榜單;
4. 下一個週六 05:00 週備份成功上傳(Drive 上有新版面的快照)。

四項都成立後才刪 PC 上的舊檔。

## 8. 回滾

* **放鎖之前**(V5 任何一步不過):`cd $REPO/data && rm -f radar.db radar.db-wal radar.db-shm radar.db.tmp`,
  把 PC 的 `wor-snapshot-*.db.gz` scp 回 `~/wor/`,`gunzip -c … > radar.db.tmp`,`sha256sum` 對 `old.sha256`
  第一行(先 `tr -d '\r'`),`mv` 回 `radar.db`,`db_sql "PRAGMA quick_check"` = ok,然後 V6 放鎖。資料零損失。
  (`--single` 檢查在舊版面上會 FAIL,屬預期。)
* **放鎖之後**(已有新寫入):同上換回舊檔(同樣先刪 `-wal`/`-shm`;先 V1/V2 拿鎖、停回補容器),之後重跑
  換檔後那幾天的匯入(各 importer 冪等,`manual-catchup.sh` 會補近 N 日缺口)。**換檔後回補容器寫進新檔的
  歷史分點列也會跟著丟掉**——回補是可續跑的,`bf-supervisor` 重開後會再抓(done flag 未寫的話);若期間已寫
  done flag,刪掉 `~/bf-*.done` 讓它重跑那一段。程式碼不用回退:新程式在舊版面也能跑。
* 維護窗中途想放棄:不要刪舊檔,直接 V6 放鎖(`rm` 掉 gz 回收空間即可)。

## 9. 結果(維護窗後填)

| 項目 | 數值 |
|---|---|
| 執行日 | **2026-10-04(日)**,使用者要求提前(原定 10-10);VPS 持鎖 01:39 → 14:45 |
| 同名同日多列件數(§3) | 0(正式庫唯讀查詢,只有「台新」有兩個 key 且從未同股同日) |
| 快照 sha256／列數(branch／prices) | `397d8254…`(9,027,452,928 B);32,378,591／10,279,864;integrity ok |
| 各變體檔案大小 | new_cover(4k+ANALYZE+`_date_cover`)5,556,072,448 B;new_plain(無 cover,只做對照)5,116,956,672 B;轉換 10 分鐘 |
| 選定變體與理由 | new_cover;Planner(Fable)GO:硬性資料閘門全過,效能閘門未過者為 PC 暖快取校準問題或已知小額結構代價(b5/b6 日價日期窗 +0.02–0.2 s、prices_new_day +1 s);b14 權證異動改走釘選覆蓋索引(37 s → 8.4 s)後過 |
| verify／export_parity／compute_parity 結果 | verify PASS(兩表 sha 相同);compute_parity 26/26 PASS;PC export_parity 3 檔 company_themes 同分順序(已以 `ORDER BY st.rowid` 固定);**VPS 同映像 manifest:3,592 檔 identical,0 different** |
| bench 結論 | `D:\wor\bench64.txt`(64 MB cache):branch_history 讀取量 0.19×、夜間分位 237→84 s、追蹤明細 13.9→1.5 s、權證 120 日 64→25 s、PC 匯出 816→675 s |
| VPS 匯出(同一程式 0c523ed,export-one) | **舊庫 26.5 分 → 新庫 14.4 分**(0.54×) |
| 換檔後 | 15:01 重新匯出+deploy 完成;磁碟 3.4 → 6.9 GB 可用;權證分點 prune dry-run backlog 3,960 列/28 日(首輪 1,671 列/10 日) |
| 換檔後 export-json elapsed(前 5 日 → 後 5 日) | 待週一起填(V7) |

## 10. 合成資料演練紀錄(PC)

**演練 A(2026-10-04,含同名多 branch_key)**:120 檔＋480 權證、250 交易日、160 分點(每 8 個分點有一個別名
branch_key,一半的機率與本尊同日同股都有列,插入先後隨機)。`branch_trades_raw` 541,012 列,同名同日多列 31,596 組
(遠高於正式庫的預期,用來壓測)。

| 檢查(新程式) | 結果 |
|---|---|
| `verify` 舊 vs 新(4k+ANALYZE) | PASS |
| `export_parity` 舊 vs 新 | 416 檔:412 逐位元相同、4 檔只差 `generated_at`;**PASS** |
| `compute_parity` 舊 vs 新(指標 `--days 5`、分點統計、PIT、分位、評分) | 26 張表全部 **PASS** |

**演練 A'(2026-10-04,最終版面 `_date_cover`＋`--analyze`,同一份合成庫)**:verify PASS(`_date_cover` DDL 逐字相同);
`export_parity` 416 檔**全部逐位元相同**(`PYTHONHASHSEED=0`、同一份 spark 快取);`compute_parity` 26 表 PASS。
verify 的計畫檢查在這份庫上擋下 b4(ANALYZE 後改走 `_branch`,見檔頭)。個股 `branches`／`branch_history`
相對 HEAD 逐值相同(120 檔 0 差)。

**純程式改動相對 HEAD 的值變化**(同一份舊檔,HEAD 程式 vs 新程式;這是上線那一刻發生、與轉換無關的一次性變化):

| 輸出 | 變化 | 原因 |
|---|---|---|
| `branch_stock_pctile_counts` | 19,200 列全部的 `stock_*` 合計欄 | 同名同日加總;合計欄是整檔加總,一檔裡只要有一組重複,整檔每列都變 |
| `branch_stock_stats` | 19,114 列中 2,221 列變值、+17/−6 列 | 同名同日加總(只有 20 個有別名的分點受影響) |
| `branch_rankings`／`branch_pit_stats` | 各 160 列中 20 列 | 同上(恰為 20 個有別名的分點) |
| `daily_scores` | 120 列中 1 列 `reasons` | B1 全序／tie-break |
| 匯出:權證分點 `breakdown`／`daily` | 118／120 檔 `net_amount` 等差 ±1 元或因同名加總 | 整數加總取代浮點 `int()` 截斷 |
| 匯出:個股 `active_warrants[].branches` | 14 檔同分順序 | 明寫 ORDER BY |
| 匯出:`pocket_tags` | 2 檔追蹤同買名單 | 同張數以名稱排序 |
| 匯出:`today.json`、`radar.json` surge | 各 1 處同分順序 | 明寫 ORDER BY |

**演練 B(2026-10-03,bench;同名別名加入前的合成庫)**:300 檔＋1,800 權證、250 日、400 分點、1,573,285 列;
四個變體轉換各 7–8 秒,verify 全 PASS。壓緊後每列位元組(表＋其索引):`branch_trades_raw` 158.7 → 93.9、
`daily_prices` 117.5 → 92.1。

bench(2 MB 快取;KiB = distinct 冷碟讀取;比例 = 新/舊):

| 案例 | 4k | 4k+stats | 8k | 8k+stats |
|---|---|---|---|---|
| a2 個股 branch_history(含 buy_lots) | 0.42× ms／0.16× KiB | 0.65／0.16 | 0.48／0.16 | 0.29／0.16 |
| a5 K 線全歷史 | 0.18／0.15 | 0.19／0.15 | 0.20／0.17 | 0.21／0.17 |
| b3 權證當日分點 | 2.37／17.05 ⚠ | 13.56／17.05 ⚠ | 12.54／30.87 ⚠ | 12.60／30.87 ⚠ |
| b4 評分 20 日窗 | 1.96／1.97 | 5.63／2.17 ⚠ | 1.95／2.86 ⚠ | 5.44／3.22 ⚠ |
| b5 評分 11 日價格(daily_prices) | 1.76／4.65 ⚠ | 1.73／4.65 ⚠ | 3.65／8.02 ⚠ | 4.41／8.02 ⚠ |
| b7 口袋 20 日窗 | 3.27／2.01 ⚠ | 9.30／2.22 ⚠ | 3.50／2.95 ⚠ | 9.08／3.33 ⚠ |
| b12 權證 120 日聚合 | 1.18／1.08 | 0.54／0.68 | 1.22／1.21 | 0.44／0.80 |
| b15 分位 490 日 | 1.66／0.99 | 0.53／0.26 | 1.71／0.99 | 0.50／0.26 |
| c1 追蹤明細 120 日 | 2.88／1.22 ⚠ | 0.17／0.30 | 3.02／1.44 ⚠ | 0.17／0.33 |
| c2 追蹤當日異動 | 2.98／16.28 ⚠ | 1.26／3.46 ⚠ | 3.26／29.47 ⚠ | 1.30／5.63 ⚠ |

結論(規則 >2× 且提示修不好 → 不可上線):**四個變體都不可上線**(4k: b3 b5 b6 b7 b14 c1 c2;4k+stats: b3 b4 b5 b6 b7 c2;
8k、8k+stats 更多)。回歸的多是單日／短窗全市場讀,絕對量小(多數 <20 MB、<0.1 s);改善的是逐檔讀與長窗掃描。
可能的方向(Planner 決定):(a) 接受小量絕對回歸;(b) 只轉 `branch_trades_raw`(b5/b6/b9 是 daily_prices 造成的);(c) 不轉。

寫入:換檔後第一天每檔股票各分裂一頁(4k +8.7 MiB／8k +15.7 MiB),之後每天 +0.2–0.5 MiB(舊版 +1.0 MiB/日);
長期表內頁面填充率會降到 70% 左右,約抵銷 0.4 GB 的節省——需要時再在 PC 上離線 VACUUM 一次。
