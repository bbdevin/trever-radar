-- 分點追蹤／靜音偏好（每位使用者各自一份，綁帳號）
-- 在 Supabase Dashboard → SQL Editor 貼上整段執行一次即可；可重跑（冪等）。
-- 只建表、限制與 RLS，不含任何金鑰，可安全進版控。
-- 執行狀態：未執行（人工執行後在 STATUS／對應 plan 打勾）。
-- 依賴：20260819171000_create_app_profiles.sql（寫入需 app_profiles.status = 'approved'）。
--
-- 行為：
--   1. branch_track_prefs：(user_id, branch_name) 一列，state = track／mute。
--      取消偏好 = 刪除該列（不另設 'none' 狀態）。
--   2. updated_at 由前端 upsert 時帶入（比照 user_ui_prefs，無 trigger）。
--
-- 資安說明（threat model）：
--   - 使用者只能讀／寫／刪自己的列：四條 policy 皆 `to authenticated` 且 auth.uid() = user_id；
--     insert／update 的 with check 同樣綁 auth.uid()，無法寫入或把列改到別人的 user_id 下。
--   - anon 無任何權限：先 revoke all（Supabase 預設 privileges 可能已授權 anon），
--     再只 grant select/insert/update/delete 給 authenticated（不給 truncate／references／trigger）。
--   - 寫入（insert／update）另需 app_profiles.status = 'approved'：任何 Google 帳號都能登入取得
--     authenticated JWT（pending／rejected 也是），不設此閘門則未核准帳號可無限灌列。
--     讀與刪仍只限本人列，不受核准狀態影響（被停權者仍可清掉自己的資料）。
--     app_profiles 對一般使用者無 insert 權、update 僅限管理員，使用者無法自行改成 approved。
--   - branch_name 是不受信任的使用者輸入：長度 1–64、不得含 C0／DEL／C1 控制字元、不得有前後空白。
--     前端只能以 React 文字節點渲染（不得 dangerouslySetInnerHTML、不得拼進 URL/HTML/SQL）；
--     DB 端不驗證名稱是否為真實分點，前端讀回時應只對照已知分點清單使用。
--   - state 以 check 限定 'track'／'mute'。

create table if not exists public.branch_track_prefs (
  user_id uuid not null references auth.users(id) on delete cascade,
  branch_name text not null,
  state text not null,
  updated_at timestamptz not null default now(),
  primary key (user_id, branch_name),
  constraint branch_track_prefs_state_check
    check (state in ('track', 'mute')),
  constraint branch_track_prefs_branch_name_check
    check (
      char_length(branch_name) between 1 and 64
      and branch_name = btrim(branch_name)
      and branch_name !~ '[\x01-\x1f\x7f-\x9f]'
    )
);

alter table public.branch_track_prefs enable row level security;

drop policy if exists "branch_track_prefs_select_own" on public.branch_track_prefs;
create policy "branch_track_prefs_select_own" on public.branch_track_prefs
  for select to authenticated
  using (auth.uid() = user_id);

drop policy if exists "branch_track_prefs_insert_own" on public.branch_track_prefs;
create policy "branch_track_prefs_insert_own" on public.branch_track_prefs
  for insert to authenticated
  with check (
    auth.uid() = user_id
    and exists (
      select 1 from public.app_profiles p
      where p.user_id = auth.uid() and p.status = 'approved'
    )
  );

drop policy if exists "branch_track_prefs_update_own" on public.branch_track_prefs;
create policy "branch_track_prefs_update_own" on public.branch_track_prefs
  for update to authenticated
  using (auth.uid() = user_id)
  with check (
    auth.uid() = user_id
    and exists (
      select 1 from public.app_profiles p
      where p.user_id = auth.uid() and p.status = 'approved'
    )
  );

drop policy if exists "branch_track_prefs_delete_own" on public.branch_track_prefs;
create policy "branch_track_prefs_delete_own" on public.branch_track_prefs
  for delete to authenticated
  using (auth.uid() = user_id);

-- 權限：先收回預設授權，再只給 authenticated 需要的四種（PostgREST 需明確授權，比照 user_ui_prefs）
revoke all on public.branch_track_prefs from anon, authenticated;
grant select, insert, update, delete on public.branch_track_prefs to authenticated;

-- ---------------------------------------------------------------------------
-- 驗證（以下皆為註解，貼整檔不會執行；需要時逐段取消註解、單獨執行）
-- ---------------------------------------------------------------------------
-- (1) RLS 開啟、policy 四條、權限只有 authenticated 四種（另有 postgres/service_role 屬正常）：
-- select relrowsecurity from pg_class where oid = 'public.branch_track_prefs'::regclass;
-- select policyname, cmd, roles, qual, with_check from pg_policies
--   where schemaname = 'public' and tablename = 'branch_track_prefs' order by policyname;
-- select grantee, privilege_type from information_schema.role_table_grants
--   where table_schema = 'public' and table_name = 'branch_track_prefs' order by grantee, privilege_type;
--
-- (2) anon 無權限（預期 ERROR: permission denied for table branch_track_prefs）：
-- begin; set local role anon; select count(*) from public.branch_track_prefs; rollback;
--
-- (3) 本人可寫可讀（<MY_UUID> 換成自己 app_profiles 中 approved 的 user_id；預期結果含「測試分點」且只有自己的列）：
-- begin;
-- set local role authenticated;
-- select set_config('request.jwt.claims', '{"sub":"<MY_UUID>","role":"authenticated"}', true);
-- insert into public.branch_track_prefs (user_id, branch_name, state) values ('<MY_UUID>', '測試分點', 'track');
-- select * from public.branch_track_prefs;
-- rollback;
--
-- (4) 寫到別人 user_id 被擋（預期 ERROR: new row violates row-level security policy）：
-- begin;
-- set local role authenticated;
-- select set_config('request.jwt.claims', '{"sub":"<MY_UUID>","role":"authenticated"}', true);
-- insert into public.branch_track_prefs (user_id, branch_name, state) values ('<OTHER_UUID>', '美林', 'track');
-- rollback;
--
-- (5) 名稱限制（預期 ERROR: violates check constraint "branch_track_prefs_branch_name_check"）：
-- begin;
-- set local role authenticated;
-- select set_config('request.jwt.claims', '{"sub":"<MY_UUID>","role":"authenticated"}', true);
-- insert into public.branch_track_prefs (user_id, branch_name, state) values ('<MY_UUID>', E'美林\n', 'track');
-- rollback;
