# 回補中途動態上線（Mid-Backfill Publish）

> 狀態：**S1 + S1.1 已實作**（2026-08-25）— mid 預設略過 stats；`safe-branch-stats.sh` @ 23:30；stats 增量累加防 OOM  
> **S2 架構定案**（2026-08-26，程式未實作）：四層總圖見 [`docs/35_vps_schedule_architecture.md`](35_vps_schedule_architecture.md)（含 bf-supervisor 自啟、大戶週槽、23:30＋scores）  
> 相關：`docs/31` §2（回補不拿 flock）、`vps/README.md`

## 1. 問題

歷史回補（`radar-bf-branches` / `radar-bf-warrant`）直接寫 VPS `radar.db`，但網站只吃  
`export-json` → `wrangler deploy` 產出的 `/data/*`。  
若等整段回補結束才上線，使用者要等數天才看得到漸進歷史；且 `docs/31` WP-B6 雖說  
「每晚 17:40 自然帶上線」，實務上：

- `compute-branch-stats` 全市場很重（常 20–40 分），daily-branches 未必每次都完整反映「歷史加深」
- 權證分點 JSON（`warrant_branches.json`）也要 export 才會變
- 回補與 daily-* 已用 pause-guard 錯開，但仍缺「專門為回補進度服務的中途 publish」

## 2. 目標

在長回補期間，**每隔一段就暫停回補 →（可選）重算分點統計 → export + deploy → 恢復回補**，  
讓線上歷史／分點排行／權證分點動向逐步變完整，不必等終點。

非目標：

- 不改評分公式、不降權證 500 萬門檻
- 不讓中途 publish 長時間握 `/tmp/radar-db.lock` 擋 daily-*（與 8/21 教訓一致）
- 不自動開跑 WP-M4 全市場 destructive 重算

## 3. 建議架構

```
radar-bf-branches ──┐
radar-bf-warrant  ──┼── 寫 radar.db（不拿 flock）
                    │
bf-cron-guard ──────── daily-* 窗 / flock 被佔 → docker pause
                    │
mid-backfill-publish.sh（新）
  1. 若正在 daily-* 窗 → 跳過（exit 0 + log）
  2. disk free < 4G → 跳過 + ntfy default 警告
  3. pause 兩個 bf 容器；暫停/協調 guard（寫 flag）
  4. （預設略過）compute-branch-stats   # mid 預設不跑;排行改 23:30 safe-branch-stats
  5. export-json → wrangler deploy      # 不長握 flock；stats/export 期間靠 pause 隔離寫入
  6. 記進度到 ~/mid-publish.state（時間、branch 最舊已密化日期粗標、warrant 進度）
  7. unpause bf；清 flag；重開 guard
  8. ntfy default：「中途上線完成」+ 簡短進度
```

**S1.1（2026-08-25）**：VPS 僅 ~1.7G RAM，`compute-branch-stats` 在歷史加深後尖峰 ~1.5G 兩次 OOM（20:00 / 03:00）。定案：

- mid-publish **預設略過 stats**（`RUN_STATS=1` 才強制）
- 新增 `safe-branch-stats.sh` @ **23:30**：pause bf → mem 門檻 → stats → export
- `compute_branch_stats` 改增量累加器，降低事件 list 記憶體

### 3.1 觸發策略（建議採 A + 手動）

| 方案 | 做法 | 優點 | 缺點 |
|---|---|---|---|
| **A. 定時（已落地）** | crontab:`0 3,9,12,20` mid=只 export；`23:30`=`safe-branch-stats.sh`（專跑 stats） | mid 不 OOM；排行每晚更新 | stats 失敗時排行多舊一天 |
| B. 里程碑 | 監看 log，每跨過一個月交易日觸發 | 與進度對齊 | 實作較複雜 |
| C. 僅手動 | `vps/scripts/mid-backfill-publish.sh` | 零風險 | 要人記得跑 |

**定案建議**：先做 **A + C**（腳本入 repo + crontab.example 註解列；VPS 是否掛上由使用者確認）。  
回補容器都不存在時腳本直接 no-op（方便回補結束後 cron 可留著無害）。

### 3.2 與現有機制的關係

| 機制 | 角色 |
|---|---|
| `bf-cron-guard` | 保護 daily-*；中途 publish 期間用 flag 讓 guard 不要搶著 unpause |
| daily-* | 仍是當日行情真相；中途 publish **跳過**其時間窗 |
| `weekly-backup` | 不動；publish 不取代備份 |
| 17:40 `daily-branches` | 仍會 stats+export；中途 publish 是「加密度」，不是取代 |

### 3.3 磁碟與時間預算

- 前置：`df` 可用空間 **≥ 4G**，否則跳過（回補中 DB 已 ~4G 級）
- `compute-branch-stats`：允許最長 ~45 分；超時則記 log、仍嘗試 export（至少 JSON 歷史加深）
- export+deploy：通常 5–15 分
- 整輪預期佔回補暫停 **15–60 分**／次；一天 2–4 次可接受

### 3.4 網站會變什麼

每次成功 publish 後使用者可比較到的：

- 個股 K 線下分點歷史／籌碼日報更深
- `/branch` 排行與追蹤（若有跑 stats）
- 個股「權證」分頁的權證分點動向、`warrant_branches.json`

不會變的：當日 quotes／法人 freshness（仍靠 daily-*）。

## 4. 實作工作包（待確認後 Executor 動手）

1. **新增** `vps/scripts/mid-backfill-publish.sh`（source `lib.sh` 的 notify／路徑；**不要**整段 `acquire_db_lock`）
2. **新增或併入** repo 版 `vps/scripts/bf-cron-guard.sh`（把目前只在 `~/` 的 guard 收進版控，並認 `MID_PUBLISH_LOCK` flag）
3. **更新** `vps/scripts/crontab.example` + `vps/README.md`（觸發列註解、手動指令）
4. **更新** `handoff.md` / `docs/STATUS.md` 一行
5. VPS：`git pull`、chmod、**使用者確認後**才寫入 crontab

驗收：

- 手動跑一輪：pause → stats? → export → deploy → unpause；ntfy 一則；線上 `generated_at` 更新
- 模擬 daily 窗內觸發：腳本跳過且回補不被誤 pause 太久
- 無 bf 容器：exit 0

## 5. Confirmed Scope

- [x] **S1（2026-08-24 使用者確認）**:腳本 + 收編 guard + crontab `0 3,9,12,20`(避開 17:40–19:30,改 20:00)+ 腳本內再擋 daily 窗／lock
- [x] **S1.1（2026-08-25）**:mid 預設略過 stats;新增 `safe-branch-stats.sh` @ 23:30;stats 增量累加降記憶體(修 OOM)
- [ ] **S2（2026-08-26 架構定案，程式待做）**:`bf-supervisor` 全自動單寫者回補＋完成 ntfy；safe-stats＋scores；TDCC 週六 06:30 納入總圖——詳 `docs/35`

## 6. 風險

- stats 期間網站短暫仍顯示舊 JSON（到 deploy 完成前）——可接受  
- 若 publish 與回補 pause 重疊過久，回補 ETA 拉長——用每天次數上限控制  
- Drive／磁碟告警與本機制無關，但 publish 前檢查 free space 可避免 OOM／寫滿
