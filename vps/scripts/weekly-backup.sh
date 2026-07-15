#!/usr/bin/env bash
# 週六 05:00 台北 — DB 快照上 Google Drive(docs/31 §4)。
# 紀律:checkpoint → integrity_check 必須 ok → gzip → 上傳;不 ok 絕不上傳覆蓋舊版。
# retention:保留最近 4 份週快照 + 每月 1 份;GitHub 零資料原則,絕不上傳 release。
source "$(dirname "$0")/lib.sh"

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
  notify "integrity_check FAILED: ${CHECK} — snapshot NOT uploaded"
  exit 1
fi

STAMP="$(taipei_date +%Y%m%d)"
SNAP="data/radar-${STAMP}.db.gz"
gzip -c data/radar.db > "$SNAP"
rclone copyto "$SNAP" "gdrive:trever-radar-backup/radar-${STAMP}.db.gz"
rclone lsf gdrive:trever-radar-backup/ | grep -q "radar-${STAMP}.db.gz"
rm -f "$SNAP"

# retention:排除最新 4 份;更舊者每月保留最新一份,其餘刪除
rclone lsf gdrive:trever-radar-backup/ --files-only \
  | grep -E '^radar-[0-9]{8}\.db\.gz$' | sort -r \
  | awk 'NR<=4 {next} { ym=substr($0,7,6); if (!(ym in seen)) { seen[ym]=1; next } print }' \
  | while read -r f; do rclone deletefile "gdrive:trever-radar-backup/$f"; done

notify "weekly snapshot ok: radar-${STAMP}.db.gz" default
