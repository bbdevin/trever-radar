-- 使用者 UI 偏好：文字縮放 + 搜尋歷史（docs/36）
-- 在 Supabase Dashboard → SQL Editor 貼上整段執行一次即可。
-- 只建表與 RLS，不含金鑰，可安全進版控。
--
-- 行為：
--   1. user_ui_prefs.font_scale：md／lg／xl；theme：dark／light（預設 dark）。本機 + 帳號。
--   2. search_history：每位使用者最近搜尋的股票代號（前端上限 20 筆）。
--   3. RLS：authenticated 只能 CRUD 自己的列（比照 watchlist）。
-- 表已存在時補 theme：另跑 docs/sql/user_ui_prefs_theme.sql

create table if not exists public.user_ui_prefs (
  user_id uuid primary key references auth.users(id) on delete cascade,
  font_scale text not null default 'md'
    check (font_scale in ('md', 'lg', 'xl')),
  theme text not null default 'dark'
    check (theme in ('dark', 'light')),
  updated_at timestamptz not null default now()
);

create table if not exists public.search_history (
  user_id uuid not null references auth.users(id) on delete cascade,
  stock_id text not null,
  searched_at timestamptz not null default now(),
  primary key (user_id, stock_id)
);

create index if not exists search_history_user_recent_idx
  on public.search_history (user_id, searched_at desc);

alter table public.user_ui_prefs enable row level security;
alter table public.search_history enable row level security;

drop policy if exists "user_ui_prefs_select_own" on public.user_ui_prefs;
create policy "user_ui_prefs_select_own" on public.user_ui_prefs
  for select to authenticated
  using (auth.uid() = user_id);

drop policy if exists "user_ui_prefs_insert_own" on public.user_ui_prefs;
create policy "user_ui_prefs_insert_own" on public.user_ui_prefs
  for insert to authenticated
  with check (auth.uid() = user_id);

drop policy if exists "user_ui_prefs_update_own" on public.user_ui_prefs;
create policy "user_ui_prefs_update_own" on public.user_ui_prefs
  for update to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists "user_ui_prefs_delete_own" on public.user_ui_prefs;
create policy "user_ui_prefs_delete_own" on public.user_ui_prefs
  for delete to authenticated
  using (auth.uid() = user_id);

drop policy if exists "search_history_select_own" on public.search_history;
create policy "search_history_select_own" on public.search_history
  for select to authenticated
  using (auth.uid() = user_id);

drop policy if exists "search_history_insert_own" on public.search_history;
create policy "search_history_insert_own" on public.search_history
  for insert to authenticated
  with check (auth.uid() = user_id);

drop policy if exists "search_history_update_own" on public.search_history;
create policy "search_history_update_own" on public.search_history
  for update to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists "search_history_delete_own" on public.search_history;
create policy "search_history_delete_own" on public.search_history
  for delete to authenticated
  using (auth.uid() = user_id);

-- PostgREST 需明確授權(與 app_profiles 相同慣例)
grant select, insert, update, delete on public.user_ui_prefs to authenticated;
grant select, insert, update, delete on public.search_history to authenticated;
