-- 使用者資料表寫入加固：watchlist／search_history／user_ui_prefs 只有 approved 帳號能新增／修改，並設每人列數與欄長上限
-- 在 Supabase Dashboard → SQL Editor 貼上整段執行一次即可；可重跑（冪等）。本體無註解，可直接整段貼上。
-- 不含任何金鑰，可安全進版控。
-- 執行狀態：未執行（人工執行後在 STATUS／README 打勾）。
-- 依賴：20260710002358_create_watchlist.sql、20260826114421_create_user_ui_prefs.sql（＋115525 theme 欄）、
--       20260819171000_create_app_profiles.sql（app_profiles.status）。
--
-- 為什麼（2026-10-03 審查發現，使用者核准加固）：任何 Google 帳號都能登入取得 authenticated JWT
-- （pending／rejected 也是），舊 policy 只檢查 auth.uid() = user_id，未核准帳號可無限灌列，耗盡免費額度儲存空間。
--
-- 行為：
--   1. insert／update policy（沿用原名，drop if exists + create）改為：本人列 AND app_profiles.status = 'approved'
--      （exists 子查詢，與 branch_track_list_select_approved 同一寫法；管理員必為 approved，故已涵蓋 is_admin()）。
--      update 的 using 與 with check 都加核准條件（比照 branch_track_list 的 update policy）。
--   2. select／delete policy 完全不動：rejected／pending 仍可讀、刪自己的資料。
--   3. 不新增 public.is_approved()：內嵌 exists 子查詢以呼叫者身分執行，受 app_profiles RLS
--      （profiles_select_own_or_admin）限制只命中本人列；不多開一支 SECURITY DEFINER 函式／PostgREST RPC 端點。
--      使用者無法自行改成 approved：app_profiles 無 insert／delete policy，update policy 限管理員。
--   4. 每人列數上限（BEFORE INSERT trigger，public.enforce_user_row_cap，SECURITY INVOKER）：
--      watchlist 500（前端無上限，台股約 2,700 檔，正常使用遠低於此）；
--      search_history 200（前端 HISTORY_LIMIT = 20：每次 upsert 後立刻刪到 20 筆，正常最多瞬間 21 筆；
--      即使刪除連續失敗到 200 筆，再點任何一筆既有歷史即走 upsert 既有列放行並觸發前端修剪，自動恢復）；
--      user_ui_prefs 主鍵即 user_id，本來就每人 1 列，不需 trigger。
--      - 已存在同 (user_id, stock_id) 的列直接放行：INSERT ... ON CONFLICT DO UPDATE 會先觸發 BEFORE INSERT。
--      - 以 pg_advisory_xact_lock(每表每人) 序列化同一人的並行寫入，避免平行請求各自 count 後一起超量；
--        同一條多列 insert 也逐列計數（VOLATILE plpgsql 看得到同語句先前插入的列）。
--      - new.user_id <> auth.uid() 時不計數直接交給 RLS 擋（避免替他人上鎖／以錯誤訊息探測他人列數）；
--        service_role／SQL Editor（auth.uid() 為 NULL）不受上限限制（本來就繞過 RLS）。
--      - SECURITY INVOKER：計數受呼叫者 RLS 限制，只看得到本人列。函式 execute 收回 public／anon／authenticated
--        （trigger 觸發時不檢查 execute 權限，比照 branch_track_list_stamp）。
--   5. 欄長上限（NOT VALID：不掃描、不因既有資料失敗；新寫入與更新一律檢查）：
--      stock_id 1–16 字（watchlist／search_history；台股代號 4–6 碼，個股頁的 id 來自網址可被竄改）、
--      watchlist.note ≤ 500 字（前端目前不寫 note）。沒有欄長上限時，列數上限擋不住單列塞大字串。
--   6. 權限：先 revoke all from anon, authenticated，再只 grant select/insert/update/delete 給 authenticated
--      （Supabase default privileges 可能已給 anon 全部權限；service_role 不受影響，盤中 worker 照常讀 watchlist）。
--
-- 回滾（還原成只檢查本人列、拿掉列數上限；欄長 constraint 可留，若要移除見最下方）：
--   1. 重跑 20260826114421_create_user_ui_prefs.sql（冪等；把 search_history／user_ui_prefs 的 policy 還原）。
--   2. 執行：
--   drop policy if exists "watchlist_insert_own" on public.watchlist;
--   create policy "watchlist_insert_own" on public.watchlist for insert with check (auth.uid() = user_id);
--   drop policy if exists "watchlist_update_own" on public.watchlist;
--   create policy "watchlist_update_own" on public.watchlist for update
--     using (auth.uid() = user_id) with check (auth.uid() = user_id);
--   drop trigger if exists watchlist_row_cap on public.watchlist;
--   drop trigger if exists search_history_row_cap on public.search_history;
--   drop function if exists public.enforce_user_row_cap();
--   （anon 權限不需還原：所有 policy 都要求 auth.uid()，anon 本來就寫不進去。）

begin;

alter table public.watchlist enable row level security;
alter table public.search_history enable row level security;
alter table public.user_ui_prefs enable row level security;

drop policy if exists "watchlist_insert_own" on public.watchlist;
create policy "watchlist_insert_own" on public.watchlist
  for insert to authenticated
  with check (
    auth.uid() = user_id
    and exists (
      select 1 from public.app_profiles p
      where p.user_id = auth.uid() and p.status = 'approved'
    )
  );

drop policy if exists "watchlist_update_own" on public.watchlist;
create policy "watchlist_update_own" on public.watchlist
  for update to authenticated
  using (
    auth.uid() = user_id
    and exists (
      select 1 from public.app_profiles p
      where p.user_id = auth.uid() and p.status = 'approved'
    )
  )
  with check (
    auth.uid() = user_id
    and exists (
      select 1 from public.app_profiles p
      where p.user_id = auth.uid() and p.status = 'approved'
    )
  );

drop policy if exists "search_history_insert_own" on public.search_history;
create policy "search_history_insert_own" on public.search_history
  for insert to authenticated
  with check (
    auth.uid() = user_id
    and exists (
      select 1 from public.app_profiles p
      where p.user_id = auth.uid() and p.status = 'approved'
    )
  );

drop policy if exists "search_history_update_own" on public.search_history;
create policy "search_history_update_own" on public.search_history
  for update to authenticated
  using (
    auth.uid() = user_id
    and exists (
      select 1 from public.app_profiles p
      where p.user_id = auth.uid() and p.status = 'approved'
    )
  )
  with check (
    auth.uid() = user_id
    and exists (
      select 1 from public.app_profiles p
      where p.user_id = auth.uid() and p.status = 'approved'
    )
  );

drop policy if exists "user_ui_prefs_insert_own" on public.user_ui_prefs;
create policy "user_ui_prefs_insert_own" on public.user_ui_prefs
  for insert to authenticated
  with check (
    auth.uid() = user_id
    and exists (
      select 1 from public.app_profiles p
      where p.user_id = auth.uid() and p.status = 'approved'
    )
  );

drop policy if exists "user_ui_prefs_update_own" on public.user_ui_prefs;
create policy "user_ui_prefs_update_own" on public.user_ui_prefs
  for update to authenticated
  using (
    auth.uid() = user_id
    and exists (
      select 1 from public.app_profiles p
      where p.user_id = auth.uid() and p.status = 'approved'
    )
  )
  with check (
    auth.uid() = user_id
    and exists (
      select 1 from public.app_profiles p
      where p.user_id = auth.uid() and p.status = 'approved'
    )
  );

alter table public.watchlist drop constraint if exists watchlist_stock_id_len_check;
alter table public.watchlist add constraint watchlist_stock_id_len_check
  check (char_length(stock_id) between 1 and 16) not valid;

alter table public.watchlist drop constraint if exists watchlist_note_len_check;
alter table public.watchlist add constraint watchlist_note_len_check
  check (note is null or char_length(note) <= 500) not valid;

alter table public.search_history drop constraint if exists search_history_stock_id_len_check;
alter table public.search_history add constraint search_history_stock_id_len_check
  check (char_length(stock_id) between 1 and 16) not valid;

create or replace function public.enforce_user_row_cap()
returns trigger
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  cap integer := tg_argv[0]::integer;
  already boolean;
  n integer;
begin
  if new.user_id is null or new.user_id is distinct from auth.uid() then
    return new;
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(tg_table_schema || '.' || tg_table_name || ':' || new.user_id::text, 0)
  );

  execute format(
    'select exists (select 1 from %I.%I where user_id = $1 and stock_id = $2)',
    tg_table_schema, tg_table_name
  ) into already using new.user_id, new.stock_id;
  if already then
    return new;
  end if;

  execute format(
    'select count(*) from %I.%I where user_id = $1',
    tg_table_schema, tg_table_name
  ) into n using new.user_id;
  if n >= cap then
    raise exception 'row cap reached: % allows at most % rows per user', tg_table_name, cap
      using errcode = 'P0001';
  end if;

  return new;
end;
$$;

revoke all on function public.enforce_user_row_cap() from public;
revoke all on function public.enforce_user_row_cap() from anon, authenticated;

drop trigger if exists watchlist_row_cap on public.watchlist;
create trigger watchlist_row_cap
  before insert on public.watchlist
  for each row execute function public.enforce_user_row_cap('500');

drop trigger if exists search_history_row_cap on public.search_history;
create trigger search_history_row_cap
  before insert on public.search_history
  for each row execute function public.enforce_user_row_cap('200');

revoke all on public.watchlist from anon, authenticated;
revoke all on public.search_history from anon, authenticated;
revoke all on public.user_ui_prefs from anon, authenticated;
grant select, insert, update, delete on public.watchlist to authenticated;
grant select, insert, update, delete on public.search_history to authenticated;
grant select, insert, update, delete on public.user_ui_prefs to authenticated;

commit;

-- ---------------------------------------------------------------------------
-- 驗證（以下皆為註解，貼整檔不會執行；需要時逐段取消註解、單獨執行）
-- ---------------------------------------------------------------------------
-- (1) policy：insert／update 含 app_profiles approved 子查詢、roles = {authenticated}；
--     select／delete 維持原樣（watchlist 的 select／delete 原本 roles = {public}，未改動）：
-- select tablename, policyname, cmd, roles, qual, with_check from pg_policies
--   where schemaname = 'public' and tablename in ('watchlist', 'search_history', 'user_ui_prefs')
--   order by tablename, policyname;
--
-- (2) 表權限只有 authenticated 四種（另有 postgres／service_role 屬正常；不應出現 anon）：
-- select table_name, grantee, privilege_type from information_schema.role_table_grants
--   where table_schema = 'public' and table_name in ('watchlist', 'search_history', 'user_ui_prefs')
--   order by table_name, grantee, privilege_type;
--
-- (3) trigger、函式權限（execute 不應出現 anon／authenticated）、欄長 constraint：
-- select tgrelid::regclass, tgname, tgenabled from pg_trigger
--   where tgname in ('watchlist_row_cap', 'search_history_row_cap');
-- select grantee, privilege_type from information_schema.role_routine_grants
--   where routine_schema = 'public' and routine_name = 'enforce_user_row_cap';
-- select conrelid::regclass, conname, convalidated from pg_constraint
--   where conname in ('watchlist_stock_id_len_check', 'watchlist_note_len_check', 'search_history_stock_id_len_check');
--
-- (4) 既有資料是否有超長列（預期全部 0；若都是 0 可選擇執行下方 validate 讓 convalidated = true）：
-- select
--   (select count(*) from public.watchlist where char_length(stock_id) not between 1 and 16) as wl_id,
--   (select count(*) from public.watchlist where note is not null and char_length(note) > 500) as wl_note,
--   (select count(*) from public.search_history where char_length(stock_id) not between 1 and 16) as sh_id;
-- alter table public.watchlist validate constraint watchlist_stock_id_len_check;
-- alter table public.watchlist validate constraint watchlist_note_len_check;
-- alter table public.search_history validate constraint search_history_stock_id_len_check;
--
-- (5) pending／rejected 帳號寫不進去、但仍讀得到自己的列（<PENDING_UUID> 換成 status <> 'approved' 的 user_id；
--     三個 insert 各自預期 ERROR: new row violates row-level security policy，故逐句單獨跑）：
-- begin;
-- set local role authenticated;
-- select set_config('request.jwt.claims', '{"sub":"<PENDING_UUID>","role":"authenticated"}', true);
-- select count(*) from public.watchlist;
-- insert into public.watchlist (user_id, stock_id) values ('<PENDING_UUID>', '2330');
-- rollback;
-- （search_history：insert into public.search_history (user_id, stock_id) values ('<PENDING_UUID>', '2330');
--   user_ui_prefs：insert into public.user_ui_prefs (user_id) values ('<PENDING_UUID>');）
--
-- (6) approved 帳號正常寫入、upsert 既有列不受上限影響、超量被擋（<MY_UUID> 換成 approved 的 user_id；
--     最後一句預期 ERROR: row cap reached: watchlist allows at most 500 rows per user）：
-- begin;
-- set local role authenticated;
-- select set_config('request.jwt.claims', '{"sub":"<MY_UUID>","role":"authenticated"}', true);
-- insert into public.search_history (user_id, stock_id) values ('<MY_UUID>', 'T0001')
--   on conflict (user_id, stock_id) do update set searched_at = now();
-- insert into public.user_ui_prefs (user_id, font_scale) values ('<MY_UUID>', 'md')
--   on conflict (user_id) do update set updated_at = now();
-- delete from public.watchlist where user_id = '<MY_UUID>';
-- insert into public.watchlist (user_id, stock_id) select '<MY_UUID>', 'T' || g from generate_series(1, 501) g;
-- rollback;
-- （search_history 同理：先 delete 本人列，再 insert ... generate_series(1, 201)，預期 at most 200）
--
-- (7) 欄長限制（預期 ERROR: violates check constraint "watchlist_stock_id_len_check"）：
-- begin;
-- set local role authenticated;
-- select set_config('request.jwt.claims', '{"sub":"<MY_UUID>","role":"authenticated"}', true);
-- insert into public.watchlist (user_id, stock_id) values ('<MY_UUID>', repeat('9', 17));
-- rollback;
--
-- (8) anon 無權限（預期 ERROR: permission denied for table watchlist）：
-- begin; set local role anon; select count(*) from public.watchlist; rollback;
--
-- 回滾欄長 constraint（如有需要）：
-- alter table public.watchlist drop constraint if exists watchlist_stock_id_len_check;
-- alter table public.watchlist drop constraint if exists watchlist_note_len_check;
-- alter table public.search_history drop constraint if exists search_history_stock_id_len_check;
