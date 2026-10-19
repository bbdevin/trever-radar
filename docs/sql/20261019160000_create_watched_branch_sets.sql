-- 自選「特定分點」組合綁帳號(docs/52 §6)
-- 執行狀態：**草稿,未執行**。須人類(建議資安審查)審過後,在 Supabase Dashboard → SQL Editor 貼上整段執行一次；可重跑（冪等）。
-- 只建表、限制與 RLS,不含任何金鑰,可安全進版控。
-- 依賴：20260819171000_create_app_profiles.sql（寫入需 app_profiles.status = 'approved'）。
--
-- 在這張表建好之前,前端(web/lib/watchedBranchSet.ts)只把組合存在本機 localStorage
-- (key watched_branch_set_v1),換裝置不會跟著走。表建好後前端要另外接上讀寫(比照 user_ui_prefs),
-- 本檔執行本身不會改變網站行為。
--
-- 行為：
--   1. watched_branch_sets：每位使用者一列。branches = 選的分點名稱(1–6 個,有順序、不重複),
--      anchor = 主分點(必須是 branches 之一)。
--   2. updated_at 由前端 upsert 時帶入（比照 user_ui_prefs,無 trigger）。
--
-- 資安說明（threat model,與 20261003145606 草稿同一套）：
--   - 使用者只能讀／寫／刪自己的列：四條 policy 皆 `to authenticated` 且 auth.uid() = user_id。
--   - anon 無任何權限：先 revoke all,再只 grant select/insert/update/delete 給 authenticated。
--   - 寫入另需 app_profiles.status = 'approved'(任何 Google 帳號都能取得 authenticated JWT)。
--   - 分點名稱是不受信任的使用者輸入：陣列長度 1–6、不重複;每個名稱 1–64 字、無前後空白、
--     無 C0／DEL／C1 控制字元。前端只以 React 文字節點渲染,且只對照 index.json 的已知分點使用。

-- check constraint 不能用子查詢,逐元素檢查放在 immutable 函式裡。
create or replace function public.watched_branch_names_ok(names text[])
returns boolean
language sql
immutable
set search_path = ''
as $$
  select coalesce(array_length(names, 1), 0) between 1 and 6
     and array_ndims(names) = 1
     and not exists (
       select 1 from unnest(names) as n
       where n is null
          or char_length(n) not between 1 and 64
          or n <> btrim(n)
          or n ~ '[\x01-\x1f\x7f-\x9f]'
     )
     and (select count(distinct n) from unnest(names) as n) = array_length(names, 1)
$$;

create table if not exists public.watched_branch_sets (
  user_id uuid primary key references auth.users(id) on delete cascade,
  branches text[] not null,
  anchor text not null,
  updated_at timestamptz not null default now(),
  constraint watched_branch_sets_names_check check (public.watched_branch_names_ok(branches)),
  constraint watched_branch_sets_anchor_check check (anchor = any(branches))
);

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
  using (auth.uid() = user_id)
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
revoke all on function public.watched_branch_names_ok(text[]) from public, anon;
grant execute on function public.watched_branch_names_ok(text[]) to authenticated;

-- ---------------------------------------------------------------------------
-- 驗證（以下皆為註解；需要時逐段取消註解、單獨執行）
-- ---------------------------------------------------------------------------
-- (1) RLS 開啟、policy 四條、權限只有 authenticated 四種：
-- select relrowsecurity from pg_class where oid = 'public.watched_branch_sets'::regclass;
-- select policyname, cmd, roles from pg_policies where tablename = 'watched_branch_sets' order by policyname;
--
-- (2) anon 無權限（預期 permission denied）：
-- begin; set local role anon; select count(*) from public.watched_branch_sets; rollback;
--
-- (3) 本人可寫可讀（<MY_UUID> = 自己 approved 的 user_id）：
-- begin;
-- set local role authenticated;
-- select set_config('request.jwt.claims', '{"sub":"<MY_UUID>","role":"authenticated"}', true);
-- insert into public.watched_branch_sets (user_id, branches, anchor)
--   values ('<MY_UUID>', array['富邦-新店','永豐金-內湖','元大-松江'], '富邦-新店');
-- select * from public.watched_branch_sets;
-- rollback;
--
-- (4) 限制（各自預期 check constraint 錯誤）：主分點不在清單、重複名稱、7 個、含換行。
-- ... values ('<MY_UUID>', array['甲','乙'], '丙');
-- ... values ('<MY_UUID>', array['甲','甲'], '甲');
-- ... values ('<MY_UUID>', array['1','2','3','4','5','6','7'], '1');
-- ... values ('<MY_UUID>', array[E'甲\n'], E'甲\n');
