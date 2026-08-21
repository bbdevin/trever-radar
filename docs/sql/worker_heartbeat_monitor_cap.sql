-- Additive: 盤中監控額度顯示(監控 n / 上限)
-- 在 Supabase SQL Editor 執行一次即可;失敗不影響既有 heartbeat。

alter table public.worker_heartbeat
  add column if not exists monitor_used int;

alter table public.worker_heartbeat
  add column if not exists monitor_cap int;
