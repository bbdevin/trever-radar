-- 自選「特定分點」組合綁帳號(docs/52 §6)
-- 執行狀態：**未執行**。資安審查 2026-10-20 已過（審查紀錄 docs/52 §6.2）；由人類在 Supabase Dashboard → SQL Editor
-- 貼上整檔執行一次即可。可重跑（冪等；整段包在 begin/commit，任何一句失敗整段不生效）。
-- 只建表、限制、一支驗證函式與 RLS，不含任何金鑰，可安全進版控。
-- 依賴：20260819171000_create_app_profiles.sql（app_profiles.status）。核准檢查寫法與
--       20261003181600_harden_user_tables_approved_writes.sql 完全相同。
--
-- 前端（web/lib/watchedBranchSet.ts＋watchedBranchSync.ts）已接好：表不存在時自動退回只存本機
-- （localStorage key watched_branch_set_v1），所以執行前後網站都能用；執行後已核准帳號的組合跟著帳號走。
--
-- 行為：
--   1. watched_branch_sets：每位使用者一列（主鍵 user_id）。branches = 選的分點名稱（1–6 個，有順序、不重複），
--      anchor = 主分點（必須是 branches 之一）。
--   2. updated_at 由前端 upsert 時帶入（本機改動時間，用於離線改動的合併；比照 user_ui_prefs，無 trigger）。
--      只影響本人那一列的合併結果，不是稽核欄位。
--
-- 資安說明（threat model）：
--   - 任何 Google 帳號都能登入取得 authenticated JWT（pending／rejected 也是），publishable key 公開在前端。
--   - 讀／刪：四條 policy 皆 `to authenticated` 且 auth.uid() = user_id，只碰得到自己的列。
--     select／delete 不要求 approved（與 watchlist／search_history／user_ui_prefs 相同：被拒者仍可讀、刪自己的資料）。
--   - 寫（insert／update）：本人列 AND app_profiles.status = 'approved'；update 的 using 與 with check 都檢查
--     （與 20261003181600 同一寫法）。exists 子查詢以呼叫者身分執行，受 app_profiles RLS 限制只命中本人列；
--     使用者無法自行改成 approved（app_profiles 無 insert／delete policy，update 限管理員）。
--   - 每人最多一列（主鍵），單列大小有上限（最多 6 個名稱 × 64 字），不需列數 trigger。
--   - anon 無任何權限：先 revoke all，再只 grant select/insert/update/delete 給 authenticated（不給 truncate／references／trigger）。
--   - 分點名稱是不受信任的使用者輸入：陣列一維、長度 1–6、元素非 NULL、不重複；每個名稱 1–64 字、無前後空白、
--     無 C0／DEL／C1 控制字元（與 branch_track_list_branch_name_check 同一條規則）。前端只以 React 文字節點渲染，
--     且只拿來對照 branches/watch/index.json 的已知分點；不拼進 URL／HTML／SQL。
--   - public.watched_branch_names_ok：SECURITY INVOKER（預設，非 definer）、IMMUTABLE、search_path 鎖空字串、
--     只讀參數、不讀任何表——沒有提權面。check constraint 在寫入者身分下求值，需要 authenticated 有 execute；
--     它因此也成為 PostgREST RPC（/rest/v1/rpc/watched_branch_names_ok），只回 true／false，不洩漏任何資料。
--     NULL 輸入回 false（不讓 NULL 讓 check 放行）。
--
-- 回滾（會刪掉所有人雲端上的組合；各裝置本機的組合仍在，前端自動退回只存本機）：
--   begin;
--   drop table if exists public.watched_branch_sets;
--   drop function if exists public.watched_branch_names_ok(text[]);
--   commit;

begin;

create or replace function public.watched_branch_names_ok(names text[])
returns boolean
language sql
immutable
security invoker
set search_path = ''
as $$
  select coalesce(
    array_ndims(names) = 1
    and array_length(names, 1) between 1 and 6
    and not exists (
      select 1 from unnest(names) as n
      where n is null
         or char_length(n) not between 1 and 64
         or n <> btrim(n)
         or n ~ '[\x01-\x1f\x7f-\x9f]'
    )
    and (select count(distinct n) from unnest(names) as n) = array_length(names, 1),
    false
  )
$$;

-- Supabase 的 default privileges 會把新函式 execute 給 anon／authenticated，逐一收回後只給 authenticated
-- （check constraint 求值時以寫入者身分檢查 execute）。
revoke all on function public.watched_branch_names_ok(text[]) from public;
revoke all on function public.watched_branch_names_ok(text[]) from anon, authenticated;
grant execute on function public.watched_branch_names_ok(text[]) to authenticated;

create table if not exists public.watched_branch_sets (
  user_id uuid primary key references auth.users(id) on delete cascade,
  branches text[] not null,
  anchor text not null,
  updated_at timestamptz not null default now()
);

-- 限制另外 drop/add，重跑時一定收斂成本檔版本（表很小，add 時驗全表不費事）。
alter table public.watched_branch_sets drop constraint if exists watched_branch_sets_names_check;
alter table public.watched_branch_sets add constraint watched_branch_sets_names_check
  check (public.watched_branch_names_ok(branches));

alter table public.watched_branch_sets drop constraint if exists watched_branch_sets_anchor_check;
alter table public.watched_branch_sets add constraint watched_branch_sets_anchor_check
  check (anchor = any(branches));

alter table public.watched_branch_sets enable row level security;

drop policy if exists "watched_branch_sets_select_own" on public.watched_branch_sets;
create policy "watched_branch_sets_select_own" on public.watched_branch_sets
  for select to authenticated
  using (auth.uid() = user_id);

drop policy if exists "watched_branch_sets_insert_own" on public.watched_branch_sets;
create policy "watched_branch_sets_insert_own" on public.watched_branch_sets
  for insert to authenticated
  with check (
    auth.uid() = user_id
    and exists (
      select 1 from public.app_profiles p
      where p.user_id = auth.uid() and p.status = 'approved'
    )
  );

drop policy if exists "watched_branch_sets_update_own" on public.watched_branch_sets;
create policy "watched_branch_sets_update_own" on public.watched_branch_sets
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

drop policy if exists "watched_branch_sets_delete_own" on public.watched_branch_sets;
create policy "watched_branch_sets_delete_own" on public.watched_branch_sets
  for delete to authenticated
  using (auth.uid() = user_id);

revoke all on public.watched_branch_sets from anon, authenticated;
grant select, insert, update, delete on public.watched_branch_sets to authenticated;

commit;

-- ---------------------------------------------------------------------------
-- 驗證（以下皆為註解，貼整檔不會執行；需要時逐段取消註解、單獨執行）
-- <MY_UUID> = 自己（approved）的 user_id：select user_id, email, status from public.app_profiles;
-- ---------------------------------------------------------------------------
-- (1) RLS 開啟（預期 true）、policy 四條且 roles = {authenticated}、insert／update 含 approved 子查詢：
-- select relrowsecurity from pg_class where oid = 'public.watched_branch_sets'::regclass;
-- select policyname, cmd, roles, qual, with_check from pg_policies
--   where schemaname = 'public' and tablename = 'watched_branch_sets' order by policyname;
--
-- (2) 表權限只有 authenticated 的 DELETE／INSERT／SELECT／UPDATE（另有 postgres／service_role 屬正常；不應出現 anon）；
--     函式 execute 只有 authenticated（另有 postgres／service_role 屬正常）；函式不是 security definer（預期 false）：
-- select grantee, privilege_type from information_schema.role_table_grants
--   where table_schema = 'public' and table_name = 'watched_branch_sets' order by grantee, privilege_type;
-- select grantee, privilege_type from information_schema.role_routine_grants
--   where routine_schema = 'public' and routine_name = 'watched_branch_names_ok' order by grantee;
-- select prosecdef, provolatile, proconfig from pg_proc where oid = 'public.watched_branch_names_ok(text[])'::regprocedure;
--
-- (3) anon 無權限（預期 ERROR: permission denied for table watched_branch_sets）：
-- begin; set local role anon; select count(*) from public.watched_branch_sets; rollback;
--
-- (4) 本人可寫可讀、upsert 可覆蓋（預期最後 select 一列、branches = {富邦-新店,元大-松江}）：
-- begin;
-- set local role authenticated;
-- select set_config('request.jwt.claims', '{"sub":"<MY_UUID>","role":"authenticated"}', true);
-- insert into public.watched_branch_sets (user_id, branches, anchor)
--   values ('<MY_UUID>', array['富邦-新店','永豐金-內湖','元大-松江'], '富邦-新店');
-- insert into public.watched_branch_sets (user_id, branches, anchor)
--   values ('<MY_UUID>', array['富邦-新店','元大-松江'], '元大-松江')
--   on conflict (user_id) do update set branches = excluded.branches, anchor = excluded.anchor, updated_at = now();
-- select * from public.watched_branch_sets;
-- rollback;
--
-- (5) 不能替別人寫（預期 ERROR: new row violates row-level security policy）：
-- begin;
-- set local role authenticated;
-- select set_config('request.jwt.claims', '{"sub":"<MY_UUID>","role":"authenticated"}', true);
-- insert into public.watched_branch_sets (user_id, branches, anchor)
--   values ('00000000-0000-0000-0000-000000000000', array['甲'], '甲');
-- rollback;
--
-- (6) pending／rejected 帳號寫不進去（<PENDING_UUID> 換成 status <> 'approved' 的 user_id；
--     預期 ERROR: new row violates row-level security policy）；沒有這種帳號可跳過：
-- begin;
-- set local role authenticated;
-- select set_config('request.jwt.claims', '{"sub":"<PENDING_UUID>","role":"authenticated"}', true);
-- insert into public.watched_branch_sets (user_id, branches, anchor) values ('<PENDING_UUID>', array['甲'], '甲');
-- rollback;
--
-- (7) 輸入限制（每句各自預期 ERROR: violates check constraint，逐句單獨跑，每句前同上 begin／set role／set_config）：
--     主分點不在清單 → watched_branch_sets_anchor_check；其餘 → watched_branch_sets_names_check。
-- insert into public.watched_branch_sets (user_id, branches, anchor) values ('<MY_UUID>', array['甲','乙'], '丙');
-- insert into public.watched_branch_sets (user_id, branches, anchor) values ('<MY_UUID>', array['甲','甲'], '甲');
-- insert into public.watched_branch_sets (user_id, branches, anchor) values ('<MY_UUID>', array['1','2','3','4','5','6','7'], '1');
-- insert into public.watched_branch_sets (user_id, branches, anchor) values ('<MY_UUID>', array[]::text[], '甲');
-- insert into public.watched_branch_sets (user_id, branches, anchor) values ('<MY_UUID>', array[E'甲\n'], E'甲\n');
-- insert into public.watched_branch_sets (user_id, branches, anchor) values ('<MY_UUID>', array[' 甲'], ' 甲');
-- insert into public.watched_branch_sets (user_id, branches, anchor) values ('<MY_UUID>', array[repeat('甲', 65)], repeat('甲', 65));
-- insert into public.watched_branch_sets (user_id, branches, anchor) values ('<MY_UUID>', array['甲', null], '甲');
-- insert into public.watched_branch_sets (user_id, branches, anchor) values ('<MY_UUID>', array[['甲','乙'],['丙','丁']], '甲');
--
-- (8) 函式本身（預期 true, false, false）：
-- select public.watched_branch_names_ok(array['富邦-新店']), public.watched_branch_names_ok(null), public.watched_branch_names_ok(array['a','a']);
