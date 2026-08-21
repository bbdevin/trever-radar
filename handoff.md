## Handoff

- **Current Goal**: 盤中監控 UX 第二輪（導覽／標籤／額度／排除 ETF）
- **Branch**: `main`
- **Human**: 請在 Supabase 執行一次 `docs/sql/worker_heartbeat_monitor_cap.sql`（否則額度顯示為 —/5）
- **Done**: 首頁拿掉盤中區塊；導覽首頁右側=監控；I1–I4 兩欄+色標；大單人話金額；ETF(00*)排除；VPS worker 需重建
- **Next**: 下交易日 08:50 觀察「監控 n/5」
