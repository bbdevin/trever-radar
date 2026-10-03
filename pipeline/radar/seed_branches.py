"""追蹤分點名單:從 Supabase 全站名單同步到 VPS 的 tracked_branches(2026-10-03)。

名單的真相在 Supabase ``public.branch_track_list``(只有管理員能改,
docs/sql/20261003181500_create_branch_track_list.sql)。本模組在每晚
``radar seed-branches`` 時把它鏡像進本機 SQLite:

  * ``track`` → ``tracked_branches`` source='manual'(已是 manual 的列不動,保留 added_at)。
  * ``mute``  → 該名稱的列改成 source='muted'。muted 列是「管理員說不要追蹤」的
    本機紀錄:compute_branch_stats 的自動入選看到它就跳過,所有讀
    ``tracked_branches`` 的地方都把 source='muted' 當成「不在名單上」
    (常數 ``MUTED_SOURCE``;消費端見 pocket.load_tracked_keys、json_export、
    compute_branch_stats、branch_point_in_time_report 只取 source='manual')。
  * 名單上沒有的名稱 = 中立:本機的 manual／muted 列移除,auto 列不動
    (由演算法照常決定自動入選／移出)。

讀取路徑(最小權限):只呼叫 ``branch_track_list_public()`` 這支 SECURITY DEFINER
函式,它只回 (branch_name, state)。用的是前端那把公開的 publishable key,
批次容器不需要、也**拒絕使用**任何能繞過 RLS 的金鑰(service_role／sb_secret_)。

失敗處理:抓取或驗證有任何問題 → 印一行 WARN、本機名單原封不動、**本輪照常
繼續**(本步驟永不使整輪失敗)。只有在本機從未同步過(沒有任何 manual／muted 列)
時才退回寫入下面那份舊的寫死名單,行為與改版前的 seed 相同。
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime
from urllib.parse import urlsplit

import requests
from sqlalchemy import text

from radar.branch_names import canonical_name
from radar.db import get_engine, init_db

# 原本寫死的種子名單。現在只用在兩個地方:SQL 的初始種子(同一份 30 個名稱),
# 以及本機從未同步過、而這一輪又抓不到線上名單時的退路。
branches = [
    "永豐金-匯立", "凱基-松山", "兆豐-復興", "富邦-南京", "元大-南京",
    "永豐金-南京", "統一-南京", "凱基-三多", "元大-南屯", "元大-信義",
    "康和-永和", "元大-館前", "港商麥格理", "元大-大天母", "凱基-信義",
    "592E", "法銀巴黎", "永豐金-板新", "永豐金-內湖", "兆豐-新竹",
    "兆豐-中壢", "富邦-南港", "富邦-新竹", "富邦-新店",
    "富邦-嘉義", "元大-土城永寧", "統一-城中", "富邦-建國", "凱基-市政", "群益金鼎-大安"
]
SEED_BRANCHES = branches

MANUAL_SOURCE = "manual"
MUTED_SOURCE = "muted"

# 公開值:與 web/lib/supabase.ts、cloudflare-data-worker/wrangler.toml 相同的專案 URL 與
# publishable key(設計上就是公開的,權限完全由 RLS 決定)。可用環境變數覆寫,但覆寫的
# key 一樣要通過 _is_low_privilege_key。
DEFAULT_SUPABASE_URL = "https://eroycvbgfitvyulfbbnw.supabase.co"
DEFAULT_SUPABASE_PUBLISHABLE_KEY = "sb_publishable_J87KLXMpmKX_ED471I13ug_ABiACBQY"
ENV_URL = "RADAR_SUPABASE_URL"
ENV_KEY = "RADAR_SUPABASE_PUBLISHABLE_KEY"
RPC_PATH = "/rest/v1/rpc/branch_track_list_public"

FETCH_TIMEOUT = (5, 10)          # (connect, read) 秒;這一步不值得拖住整輪
MAX_BYTES = 256 * 1024           # 30 列約 2 KB;超過就是有東西不對
MAX_ROWS = 1000
NAME_MAX_LEN = 64
VALID_STATES = ("track", "mute")

LOG_PREFIX = "branch-track-sync"


class TrackListError(Exception):
    """抓取／驗證失敗。訊息一律不含金鑰(見 _redact)。"""


def _redact(msg: str, secret: str | None) -> str:
    if secret:
        msg = msg.replace(secret, "***")
    return msg[:300]


def _is_low_privilege_key(key: str) -> bool:
    """只接受 publishable key 或 role=anon 的 legacy JWT;其他一律拒絕。

    批次容器處理的是第三方網站的資料,不應持有能繞過 RLS 的金鑰——即使有人
    誤把 service_role 設進環境變數,這裡也不會把它送出去。
    """
    if not key or any(c.isspace() for c in key):
        return False
    if key.startswith("sb_publishable_"):
        return True
    if key.startswith("sb_secret_"):
        return False
    parts = key.split(".")
    if len(parts) != 3:
        return False
    try:
        seg = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(seg.encode("ascii")))
    except (ValueError, UnicodeError):
        return False
    return isinstance(payload, dict) and payload.get("role") == "anon"


def _endpoint() -> tuple[str, str]:
    base = (os.environ.get(ENV_URL) or DEFAULT_SUPABASE_URL).strip().rstrip("/")
    key = (os.environ.get(ENV_KEY) or DEFAULT_SUPABASE_PUBLISHABLE_KEY).strip()
    parts = urlsplit(base)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in ("", "/")):
        raise TrackListError("supabase url rejected (must be a bare https origin)")
    if not _is_low_privilege_key(key):
        raise TrackListError(
            f"{ENV_KEY} rejected: only a publishable/anon key may be used by the batch pipeline")
    return base + RPC_PATH, key


def _valid_name(name) -> bool:
    """與 SQL check 同一規則:1–64 字、前後無半形空白(btrim)、無 C0／DEL／C1 控制字元。"""
    if not isinstance(name, str) or not (1 <= len(name) <= NAME_MAX_LEN):
        return False
    if name != name.strip(" "):
        return False
    return not any(ord(c) <= 0x1F or 0x7F <= ord(c) <= 0x9F for c in name)


def parse_track_list(payload) -> dict[str, str]:
    """驗證 RPC 回傳並回 {正規名稱: state}。任一列不合規 → 整批拒絕(fail closed)。"""
    if not isinstance(payload, list):
        raise TrackListError("response is not a JSON array")
    if len(payload) > MAX_ROWS:
        raise TrackListError(f"response has {len(payload)} rows (> {MAX_ROWS})")
    out: dict[str, str] = {}
    for i, row in enumerate(payload):
        if not isinstance(row, dict):
            raise TrackListError(f"row {i} is not an object")
        name, state = row.get("branch_name"), row.get("state")
        if not _valid_name(name):
            raise TrackListError(f"row {i} has an invalid branch_name")
        if state not in VALID_STATES:
            raise TrackListError(f"row {i} has an invalid state")
        key = canonical_name(name)
        # 兩個舊/新名正規化成同一家:mute 優先(管理員對其中一個說了不要)。
        if out.get(key) == "mute":
            continue
        out[key] = state
    return out


def fetch_track_list(session: requests.Session | None = None,
                     timeout=FETCH_TIMEOUT) -> dict[str, str]:
    url, key = _endpoint()
    http = session or requests.Session()
    try:
        try:
            resp = http.post(
                url,
                headers={"apikey": key, "Accept": "application/json",
                         "Content-Type": "application/json"},
                json={},
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as e:
            raise TrackListError(
                _redact(f"request failed: {type(e).__name__}: {e}", key)) from None
        try:
            if resp.status_code != 200:
                # 不印 body:可能很大,也可能夾帶伺服器端細節;狀態碼足以判斷。
                raise TrackListError(f"HTTP {resp.status_code}")
            buf = bytearray()
            for chunk in resp.iter_content(chunk_size=16384):
                buf.extend(chunk)
                if len(buf) > MAX_BYTES:
                    raise TrackListError(f"response larger than {MAX_BYTES} bytes")
        except requests.RequestException as e:
            raise TrackListError(
                _redact(f"read failed: {type(e).__name__}: {e}", key)) from None
        finally:
            resp.close()
    finally:
        if session is None:
            http.close()
    try:
        payload = json.loads(bytes(buf).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise TrackListError("response is not valid UTF-8 JSON") from None
    return parse_track_list(payload)


def _local_sources(conn) -> dict[str, str]:
    return {r[0]: r[1] for r in conn.execute(text(
        "SELECT branch_name, source FROM tracked_branches"))}


def apply_track_list(conn, wanted: dict[str, str], now: str) -> dict[str, int]:
    """把 {名稱: track|mute} 鏡像進 tracked_branches(在呼叫端的交易內)。"""
    local = _local_sources(conn)
    stats = {"track": 0, "mute": 0, "added": 0, "muted": 0, "removed": 0}
    for name, state in sorted(wanted.items()):
        stats[state] += 1
        cur = local.get(name)
        if state == "track":
            if cur == MANUAL_SOURCE:
                continue  # 保留原 added_at(branch_point_in_time_report 以它判斷何時入名單)
            conn.execute(text(
                "INSERT INTO tracked_branches (branch_name, source, note, added_at) "
                "VALUES (:n, :s, :note, :now) "
                "ON CONFLICT(branch_name) DO UPDATE SET source = excluded.source, "
                "note = excluded.note, added_at = excluded.added_at"),
                {"n": name, "s": MANUAL_SOURCE, "note": "管理員追蹤名單", "now": now})
            stats["added"] += 1
        else:
            if cur == MUTED_SOURCE:
                continue
            conn.execute(text(
                "INSERT INTO tracked_branches (branch_name, source, note, added_at) "
                "VALUES (:n, :s, :note, :now) "
                "ON CONFLICT(branch_name) DO UPDATE SET source = excluded.source, "
                "note = excluded.note, added_at = excluded.added_at"),
                {"n": name, "s": MUTED_SOURCE, "note": "管理員取消追蹤(自動入選略過)", "now": now})
            stats["muted"] += 1
    # 名單上已沒有的名稱 → 中立:manual／muted 列移除;auto 列交給演算法。
    for name, src in local.items():
        if src in (MANUAL_SOURCE, MUTED_SOURCE) and name not in wanted:
            conn.execute(text(
                "DELETE FROM tracked_branches WHERE branch_name = :n AND source = :s"),
                {"n": name, "s": src})
            stats["removed"] += 1
    return stats


def _seed_fallback(conn, now: str) -> int:
    """舊行為:INSERT OR IGNORE 寫死名單為 manual。只在本機從未同步過時使用。"""
    n = 0
    for b in SEED_BRANCHES:
        res = conn.execute(text(
            "INSERT OR IGNORE INTO tracked_branches (branch_name, source, note, added_at) "
            "VALUES (:name, 'manual', '使用者指定種子分點', :now)"),
            {"name": b, "now": now})
        n += res.rowcount or 0
    return n


def _has_synced_state(conn) -> bool:
    return conn.execute(text(
        "SELECT 1 FROM tracked_branches WHERE source IN (:m, :x) LIMIT 1"),
        {"m": MANUAL_SOURCE, "x": MUTED_SOURCE}).first() is not None


def sync_tracked_branches(fetch=None, engine=None) -> str:
    """同步線上名單 → tracked_branches。永不 raise;回傳結果代碼(ok/kept/fallback/refused/error)。"""
    fetch = fetch or fetch_track_list
    engine = engine or get_engine()
    now = datetime.now().isoformat()
    try:
        wanted = fetch()
    except Exception as e:  # noqa: BLE001 — 任何失敗都不得使整輪失敗
        reason = str(e) if isinstance(e, TrackListError) else type(e).__name__
        try:
            with engine.begin() as conn:
                if _has_synced_state(conn):
                    print(f"WARN {LOG_PREFIX}: fetch failed ({reason}); "
                          "keeping existing tracked_branches unchanged", flush=True)
                    return "kept"
                added = _seed_fallback(conn, now)
            print(f"WARN {LOG_PREFIX}: fetch failed ({reason}); never synced before, "
                  f"seeded {added} built-in branches as fallback", flush=True)
            return "fallback"
        except Exception as db_e:  # noqa: BLE001
            print(f"WARN {LOG_PREFIX}: fetch failed ({reason}) and local fallback failed "
                  f"({type(db_e).__name__}); tracked_branches unchanged", flush=True)
            return "error"

    try:
        with engine.begin() as conn:
            if not wanted and _has_synced_state(conn):
                # 空名單會把所有 manual 列清掉。管理員要停掉全部追蹤應逐一改成 mute;
                # 一個空回應更可能是設定錯誤,寧可不動。
                print(f"WARN {LOG_PREFIX}: online list is empty; refusing to clear "
                      "local manual/muted rows (mute entries instead to untrack)", flush=True)
                return "refused"
            stats = apply_track_list(conn, wanted, now)
    except Exception as e:  # noqa: BLE001
        print(f"WARN {LOG_PREFIX}: applying list failed ({type(e).__name__}); "
              "tracked_branches unchanged", flush=True)
        return "error"
    print(f"{LOG_PREFIX}: ok track={stats['track']} mute={stats['mute']} "
          f"(+{stats['added']} manual, {stats['muted']} newly muted, "
          f"-{stats['removed']} cleared)", flush=True)
    return "ok"


def run():
    init_db()
    # 結果只寫 log(WARN 行);本步驟刻意永遠以 0 結束,不讓名單同步擋住整輪分點管線。
    sync_tracked_branches()


if __name__ == "__main__":
    run()
