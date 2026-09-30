#!/usr/bin/env bash
# 週六 05:00 台北 — DB 快照上 Google Drive(docs/31 §4)。
# 紀律:checkpoint → integrity_check 必須 ok → gzip → 上傳;不 ok 絕不上傳覆蓋舊版。
# retention(2026-09-30 使用者核准):最近 2 份週快照 + 更舊者每月最新 1 份;
# 放不下時從最舊的月快照開始刪。GitHub 零資料原則,絕不上傳 release。
#
# 2026-09-30 改寫的理由:09-26 的快照因 Drive 配額滿而沒上傳,本機留著唯一的一份,
# 通知只說「執行到第 27 行失敗」。兩個成因:①清舊檔排在上傳**之後**,空間不夠時
# 根本走不到清理;②`rclone deletefile` 預設移到垃圾桶,垃圾桶照樣佔配額——保留
# 策略刪掉的 3 份在垃圾桶裡佔了 2.31 GiB。現在:先依策略算好要刪什麼(新快照算作
# 2 份週快照之一)、永久刪除、確認放得下才上傳、上傳後比對大小才刪本機檔。
source "$(dirname "$0")/lib.sh"

REMOTE="gdrive:trever-radar-backup"
# 上傳需要的額外餘裕:Drive 的 free 是估計值,貼著邊界上傳會在最後一段失敗。
MARGIN_BYTES=$((200 * 1024 * 1024))

# 拿 DB 鎖:快照期間不得有寫入者(export-json 可並行,但整檔 gzip 不行)
acquire_db_lock
cd "$REPO"

# 用管線映像的 python 跑 SQL,主機不需裝 sqlite3
db_sql() {
  docker run --rm -v "$REPO/data":/app/data radar-pipeline \
    python -c "import sqlite3,sys; print(sqlite3.connect('/app/data/radar.db').execute(sys.argv[1]).fetchone()[0])" "$1"
}

db_sql "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null
CHECK="$(db_sql 'PRAGMA integrity_check;')"
if [ "$CHECK" != "ok" ]; then
  notify "資料庫完整性檢查失敗（${CHECK}），本次快照未上傳" high "失敗"
  exit 1
fi

STAMP="$(taipei_date +%Y%m%d)"
NAME="radar-${STAMP}.db.gz"
SNAP="data/${NAME}"
gzip -c data/radar.db > "$SNAP"
SIZE="$(stat -c %s "$SNAP")"

# ── 上傳前:依策略決定刪哪些,並確認放得下 ─────────────────────────
FREE="$(rclone about "$REMOTE" --json | python3 -c 'import json,sys; print(int(json.load(sys.stdin).get("free", 0)))')"
PLAN_RC=0
if PLAN="$(rclone lsjson "$REMOTE/" --files-only \
    | python3 "$REPO/vps/scripts/backup_retention.py" \
        --new "$NAME" --need "$((SIZE + MARGIN_BYTES))" --free "$FREE")"; then
  PLAN_RC=0
else
  PLAN_RC=$?
fi
if [ "$PLAN_RC" -ne 0 ] && [ "$PLAN_RC" -ne 3 ]; then
  notify "週備份：保留策略計算失敗（碼 ${PLAN_RC}），未刪任何檔、未上傳；本機保留 ${SNAP}" high "失敗"
  exit "$PLAN_RC"
fi

# 策略內的舊快照照刪(永久刪除,不進垃圾桶);放不放得下另外判斷。
while IFS= read -r victim; do
  [ -n "$victim" ] || continue
  rclone deletefile --drive-use-trash=false "$REMOTE/$victim"
  echo "retention: deleted $victim"
done <<< "$PLAN"

if [ "$PLAN_RC" -eq 3 ]; then
  notify "週備份未上傳：Google Drive 空間不足（快照 $((SIZE / 1048576)) MiB，刪完舊快照仍放不下）。本機保留 ${SNAP}，那是這一週唯一的一份；請清出 Drive 空間" high "失敗"
  exit 3
fi

# ── 上傳並比對大小,才刪本機 ──────────────────────────────────────
rclone copyto "$SNAP" "$REMOTE/$NAME"
REMOTE_SIZE="$(rclone lsjson "$REMOTE/$NAME" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d[0]["Size"] if d else -1)')"
if [ "$REMOTE_SIZE" != "$SIZE" ]; then
  notify "週備份上傳後大小不符（Drive ${REMOTE_SIZE} ≠ 本機 ${SIZE}），本機保留 ${SNAP}" high "失敗"
  exit 1
fi
# 上一次失敗留在本機的舊快照,在新的一份確實上傳之後一起清掉(它已被取代)。
rm -f data/radar-*.db.gz

notify_ok "週備份完成：${NAME} 已上傳 Drive（$((SIZE / 1048576)) MiB）"
