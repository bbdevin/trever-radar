# docs/sql — Supabase migration 命名原則

> 適用：**Supabase** 手跑 SQL（Dashboard → SQL Editor）。  
> **不適用**：VPS `radar.db`（SQLite schema 仍以 `pipeline/radar/schema.py` 為準，無本目錄 runner）。

## 檔名格式

```
YYYYMMDDHHMMSS_snake_case_description.sql
```

| 段 | 說明 |
|---|---|
| `YYYYMMDDHHMMSS` | 建立時刻（台北）；同秒衝突再加 1 秒 |
| `snake_case` | 動詞開頭：`create_` / `add_` / `grant_` / `fix_` / `drop_`… |
| 副檔名 | 一律 `.sql` |

範例：`20260826114421_create_user_ui_prefs.sql`

## 規則

1. **新檔必須用時間戳前綴**；目錄排序＝建議執行順序。
2. **只做 additive／冪等**（`if not exists`、`add column if not exists`）；destructive 須另案經使用者確認。
3. **不自動套用**——仍由人工在 Supabase 執行；執行後在 `STATUS`／對應 plan 打勾。
4. 檔頭註解寫：用途、是否已執行、依賴的前一個 migration（若有）。
5. 舊檔名已統一改為時間戳（2026-08-26）；文件引用請用新路徑。

## 現有清單（依時間）

| 檔名 | 用途 |
|---|---|
| `20260710002358_create_watchlist.sql` | 自選股 |
| `20260712011048_create_intraday_signals.sql` | 盤中訊號 |
| `20260819171000_create_app_profiles.sql` | WP-B7 核准閘門 |
| `20260821145158_add_worker_heartbeat_monitor_cap.sql` | 監控額度欄位 |
| `20260826114421_create_user_ui_prefs.sql` | 字級／搜尋歷史／theme |
| `20260826114857_grant_user_ui_prefs.sql` | prefs 表 GRANT |
| `20260826115525_add_user_ui_prefs_theme.sql` | 既有表補 theme 欄 |
| `20261003145606_create_branch_track_prefs.sql` | ~~分點追蹤／靜音偏好（綁帳號）~~ **已作廢（未執行），改用 `20261003181500_create_branch_track_list.sql`；請勿執行** |
| `20261003181500_create_branch_track_list.sql` | 全站分點追蹤名單（只有管理員可寫、approved 可讀；`branch_track_list_public()` 供 VPS 夜間管線以 publishable key 唯讀；含原 30 分點種子）**✅ 2026-10-03 已執行** |
