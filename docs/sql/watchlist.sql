-- 自選股(watchlist)資料表 + RLS
-- 在 Supabase Dashboard → SQL Editor 貼上整段執行一次即可。
-- 只建表與權限規則,不含任何金鑰,可安全進版控。

create table if not exists watchlist (
  user_id uuid not null references auth.users(id) on delete cascade,
  stock_id text not null,
  note text,
  added_at timestamptz not null default now(),
  primary key (user_id, stock_id)
);

alter table watchlist enable row level security;

-- 每個登入使用者只能看到/新增/刪除自己的列;彼此看不到對方的自選股。
create policy "watchlist_select_own" on watchlist
  for select using (auth.uid() = user_id);

create policy "watchlist_insert_own" on watchlist
  for insert with check (auth.uid() = user_id);

create policy "watchlist_delete_own" on watchlist
  for delete using (auth.uid() = user_id);

-- 備註可编輯(例如加自選時想寫觀察理由)
create policy "watchlist_update_own" on watchlist
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
