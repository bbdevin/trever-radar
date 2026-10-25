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
#
# 2026-10-25 加上傳重試:10-24 05:17 保留策略永久刪掉 radar-20261003.db.gz(2.1 GB)後,
# 緊接著的上傳(copyto)在一秒內失敗 4 次(`Error 403 … storageQuotaExceeded`);
# 隔天手動重跑同一行立刻成功(Drive 剩 1.94 GiB)。Google 的配額帳在永久刪除之後
# 有延遲。現在上傳失敗會等一下再試(預設共 3 次,間隔 5、10 分鐘),每次重試前重新
# `rclone about` 記下 Drive 剩多少。DB 鎖只保護 checkpoint/integrity_check/gzip,
# gzip 完就放掉——之後的保留策略、上傳、重試都不碰 radar.db,不該讓回補與週六 06:30
# 大戶持股等著這段網路 I/O。
source "$(dirname "$0")/lib.sh"

REMOTE="gdrive:trever-radar-backup"
# 上傳需要的額外餘裕:Drive 的 free 是估計值,貼著邊界上傳會在最後一段失敗。
MARGIN_BYTES=$((200 * 1024 * 1024))
UPLOAD_ATTEMPTS="${BACKUP_UPLOAD_ATTEMPTS:-3}"
# 非數字(.env 打錯)會讓 `[ -ge ]` 永遠為假、重試迴圈停不下來並一直握著備份鎖:退回 3。
case "$UPLOAD_ATTEMPTS" in ''|*[!0-9]*) UPLOAD_ATTEMPTS=3 ;; esac
UPLOAD_RETRY_SLEEPS="${BACKUP_UPLOAD_RETRY_SLEEPS:-300 600}"

# 備份自己的互斥鎖(fd 7):放掉 DB 鎖之後,仍不能讓第二個 weekly-backup(例如
# manual-catchup.sh 呼叫的那一個)在上傳/重試期間插進來改寫同一份快照。
exec 7>/tmp/radar-backup.lock
if ! flock -n 7; then
  notify_skip "上一次週備份還在上傳／重試，本次略過"
  exit 0
fi

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

# 快照已落地,之後不再碰 radar.db:放掉 DB 鎖(關 fd 9)。上傳與重試可能要十幾分鐘。
exec 9>&-
echo "db lock released after snapshot (${SIZE} bytes)"

drive_free() {
  rclone about "$REMOTE" --json | python3 -c 'import json,sys; print(int(json.load(sys.stdin).get("free", 0)))'
}
local_free_mib() {
  df -Pm "$REPO/data" | awk 'NR==2 {print $4}'
}
# 失敗通知共用的後半句:本機快照留著、多大,以及 VPS 磁碟因此少了多少。
kept_note() {
  echo "本機保留 ${SNAP}（$((SIZE / 1048576)) MiB），那是這一週唯一的一份；VPS 磁碟因此只剩 $(local_free_mib || echo '?') MiB 可用"
}

# ── 上傳前:依策略決定刪哪些,並確認放得下 ─────────────────────────
FREE="$(drive_free)"
PLAN_RC=0
if PLAN="$(rclone lsjson "$REMOTE/" --files-only \
    | python3 "$REPO/vps/scripts/backup_retention.py" \
        --new "$NAME" --need "$((SIZE + MARGIN_BYTES))" --free "$FREE")"; then
  PLAN_RC=0
else
  PLAN_RC=$?
fi
if [ "$PLAN_RC" -ne 0 ] && [ "$PLAN_RC" -ne 3 ]; then
  notify "週備份：保留策略計算失敗（碼 ${PLAN_RC}），未刪任何檔、未上傳；$(kept_note)" high "失敗"
  exit "$PLAN_RC"
fi

# 策略內的舊快照照刪(永久刪除,不進垃圾桶);放不放得下另外判斷。
DELETED=""
while IFS= read -r victim; do
  [ -n "$victim" ] || continue
  rclone deletefile --drive-use-trash=false "$REMOTE/$victim"
  echo "retention: deleted $victim"
  DELETED="${DELETED:+${DELETED}、}${victim}"
done <<< "$PLAN"

if [ "$PLAN_RC" -eq 3 ]; then
  notify "週備份未上傳：Google Drive 空間不足（快照 $((SIZE / 1048576)) MiB，刪完舊快照仍放不下）。$(kept_note)；請清出 Drive 空間" high "失敗"
  exit 3
fi

# ── 上傳(失敗就等一下再試)並比對大小,才刪本機 ─────────────────────
# 剛永久刪掉的舊快照,Drive 的配額帳可能還沒退回來(10-24 事故),所以任何失敗都
# 重試;每次重試前重新查 Drive 剩多少並記一行 log。此時已不握 DB 鎖(fd 9 已關)。
attempt=0
UPLOAD_RC=0
UPLOAD_OUT=""
while :; do
  attempt=$((attempt + 1))
  UPLOAD_RC=0
  UPLOAD_OUT="$(rclone copyto "$SNAP" "$REMOTE/$NAME" 2>&1)" || UPLOAD_RC=$?
  [ -z "$UPLOAD_OUT" ] || printf '%s\n' "$UPLOAD_OUT"
  echo "upload attempt ${attempt}/${UPLOAD_ATTEMPTS} rc=${UPLOAD_RC}"
  if [ "$UPLOAD_RC" -eq 0 ] || [ "$attempt" -ge "$UPLOAD_ATTEMPTS" ]; then
    break
  fi
  # 第 N 次失敗睡清單的第 N 個;清單用完就沿用最後一個。
  pause=600
  for s in $(echo "$UPLOAD_RETRY_SLEEPS" | cut -d' ' -f"1-${attempt}"); do pause="$s"; done
  echo "upload: copyto failed (rc=${UPLOAD_RC}), retrying in ${pause}s"
  sleep "$pause"
  FREE_NOW="$(drive_free 2>/dev/null)" || FREE_NOW="?"
  echo "upload: drive free before retry $((attempt + 1)): ${FREE_NOW} bytes (need ${SIZE} + margin)"
done

if [ "$UPLOAD_RC" -ne 0 ]; then
  if printf '%s' "$UPLOAD_OUT" | grep -q storageQuotaExceeded; then
    REASON="Google Drive 回報配額已滿（storageQuotaExceeded）"
  else
    REASON="rclone copyto 碼 ${UPLOAD_RC}"
  fi
  notify "週備份上傳失敗：試了 ${attempt} 次仍失敗（${REASON}）。$(kept_note)。已依保留策略從 Drive 永久刪除：${DELETED:-無}。確認 Drive 空間後手動執行 rclone copyto ${SNAP} ${REMOTE}/${NAME}" high "失敗"
  exit 4
fi

REMOTE_SIZE="$(rclone lsjson "$REMOTE/$NAME" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d[0]["Size"] if d else -1)')"
if [ "$REMOTE_SIZE" != "$SIZE" ]; then
  notify "週備份上傳後大小不符（Drive ${REMOTE_SIZE} ≠ 本機 ${SIZE}），$(kept_note)" high "失敗"
  exit 1
fi
# 上一次失敗留在本機的舊快照,在新的一份確實上傳之後一起清掉(它已被取代)。
rm -f data/radar-*.db.gz

notify_ok "週備份完成：${NAME} 已上傳 Drive（$((SIZE / 1048576)) MiB）"
