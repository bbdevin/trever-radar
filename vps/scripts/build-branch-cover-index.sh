#!/usr/bin/env bash
# 一次性維運:在正式庫建立 branch_trades_raw 的覆蓋索引(2026-09-30,使用者核准)。
#
# 為什麼:compute-branch-stats 逐檔讀 branch_trades,冷讀 526 秒——表是 rowid 表、按
# 日期附加,一檔股票的列散在整個 7.5 GB 檔案裡,機器只有 1.7 GB 記憶體。這個索引
# 依 stock_id 聚集,讀取只走索引(pipeline/radar/schema.py 的
# ix_branch_trades_raw_stock_cover;1% 抽樣外推約 1.24 GB)。
#
# 為什麼要專用腳本、不交給 init_db:create_all 不會替既有表補建索引(這是好事——
# 否則某一輪會在沒人預期的時候卡十幾分鐘)。建索引期間握著 /tmp/radar-db.lock,
# 而排程輪次是 flock -n、拿不到就**整輪略過**,所以必須挑一段離下一個排程寫入者
# 夠遠的空檔,做法同 warrant-backfill.sh:先等窗口、再搶鎖、搶到才 pause 回補容器。
#
# 磁碟:建索引時排序暫存與 WAL 各約一份索引大小,checkpoint 時資料庫再長一份,
# 峰值約 2.5–3 GB。可用空間不足 4 GiB 就不做。
#
# 冪等:CREATE INDEX IF NOT EXISTS;已存在就只回報、不重建。
source "$(dirname "$0")/lib.sh"
trap - ERR   # 失敗點各自講清楚後果,不用「執行到第 N 行失敗」

INDEX="ix_branch_trades_raw_stock_cover"
NEED_WINDOW_MIN="${COVER_INDEX_WINDOW_MIN:-90}"
NEED_FREE_BYTES=$((4 * 1024 * 1024 * 1024))
WAIT_UNTIL=$(( $(date +%s) + ${COVER_INDEX_MAX_WAIT_HOURS:-12} * 3600 ))

cd "$REPO"

db_py() {
  docker run --rm -e SQLITE_TMPDIR=/app/data -v "$REPO/data":/app/data radar-pipeline \
    python -c "import sqlite3,sys; c=sqlite3.connect('/app/data/radar.db', timeout=60); r=c.execute(sys.argv[1]).fetchone(); c.commit(); print(r[0] if r else '')" "$1"
}

exists="$(db_py "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='${INDEX}'")"
if [ "$exists" = "1" ]; then
  echo "${INDEX} already exists — nothing to do"
  exit 0
fi

# 回補的維運暫停檔(warrant-backfill.sh 看到它就不開新的一段)。第一版沒有這一步,
# 整晚 12 小時的每一個空檔都被回補先搶走:回補每 3 分鐘試一次、一拿就是 240 分鐘,
# 這支每 5 分鐘才看一次。暫停檔讓回補跑完手上那一段就讓出空檔;EXIT 時一定移除。
#
# 只刪**自己建的**那一份:warrant-backfill.sh 在吞吐塌陷時也會建同一個檔,那是給人
# 看的告警(「請人工確認來源後刪除該檔」)。開始時檔案已在 → 不建、也絕不刪。
PAUSE_FILE="${WARRANT_PAUSE_FILE:-/tmp/radar-warrant-backfill.pause}"
PAUSE_OWNED=0
if [ ! -e "$PAUSE_FILE" ]; then
  : > "$PAUSE_FILE"
  PAUSE_OWNED=1
fi
release_pause() { if [ "$PAUSE_OWNED" = 1 ]; then rm -f "$PAUSE_FILE"; fi; }
trap 'release_pause' EXIT

echo "=== cover-index wait start $(taipei_date -Is) (need ${NEED_WINDOW_MIN}min window; warrant backfill paused via ${PAUSE_FILE})"
while :; do
  if [ "$(date +%s)" -ge "$WAIT_UNTIL" ]; then
    echo "--- gave up $(taipei_date -Is): no ${NEED_WINDOW_MIN}-minute window; nothing changed"
    notify_warn "覆蓋索引:等不到 ${NEED_WINDOW_MIN} 分鐘的空檔,本次未建(什麼都沒動)"
    exit 75
  fi
  if in_radar_quiet_window; then sleep 300; continue; fi
  mins="$(minutes_until_next_scheduled_writer 2>/dev/null || echo 0)"
  if [ "${mins:-0}" -lt "$NEED_WINDOW_MIN" ]; then sleep 300; continue; fi
  exec 9>/tmp/radar-db.lock
  if flock -n 9; then break; fi
  exec 9>&-            # 回補或某一輪正握著鎖:放手、稍後再看
  sleep 300
done
echo "--- window ok $(taipei_date -Is): ${mins} min until next scheduled writer"

# 本腳本不呼叫 radar(沒有 lib.sh 的密鑰清理 EXIT trap 要串接);暫停檔的清理要一起保留。
trap 'unpause_bf_containers; release_pause' EXIT
pause_bf_containers

free_bytes="$(df --output=avail -B1 "$REPO/data" | tail -1 | tr -d ' ')"
if [ "$free_bytes" -lt "$NEED_FREE_BYTES" ]; then
  notify "覆蓋索引未建:磁碟可用 $((free_bytes / 1048576)) MiB,少於 4 GiB(峰值約需 2.5–3 GB)。什麼都沒動" high "失敗"
  exit 1
fi

t0=$(date +%s)
size_before="$(stat -c %s data/radar.db)"
echo "--- CREATE INDEX start $(taipei_date -Is) free=$((free_bytes / 1048576))MiB db=$((size_before / 1048576))MiB"
if ! db_py "CREATE INDEX IF NOT EXISTS ${INDEX} ON branch_trades_raw (stock_id, date, branch_id, net_lots, sell_lots, pct)" >/dev/null; then
  notify "覆蓋索引建立失敗(交易已回滾,正式資料不受影響);請看 ~/cover-index.log" high "失敗"
  exit 1
fi
db_py "PRAGMA wal_checkpoint(TRUNCATE)" >/dev/null
t1=$(date +%s)
size_after="$(stat -c %s data/radar.db)"
free_after="$(df --output=avail -B1 "$REPO/data" | tail -1 | tr -d ' ')"
exists="$(db_py "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='${INDEX}'")"
echo "--- done $(taipei_date -Is) elapsed=$((t1 - t0))s db ${size_before}->${size_after} (+$(((size_after - size_before) / 1048576))MiB) free_after=$((free_after / 1048576))MiB exists=${exists}"
if [ "$exists" != "1" ]; then
  notify "覆蓋索引:指令成功但查不到索引,請看 ~/cover-index.log" high "失敗"
  exit 1
fi
notify_ok "覆蓋索引已建立:耗時 $(((t1 - t0) / 60)) 分鐘,資料庫 +$(((size_after - size_before) / 1048576)) MiB,磁碟剩 $((free_after / 1048576)) MiB"
