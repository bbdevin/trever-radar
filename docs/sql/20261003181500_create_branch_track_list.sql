-- 分點追蹤名單（全站一份，只有管理員能改；取代 20261003145606_create_branch_track_prefs.sql 的每人偏好案）
-- 在 Supabase Dashboard → SQL Editor 貼上整段執行一次即可；可重跑（冪等）。
-- 只建表、限制、RLS、一支唯讀函式與初始種子，不含任何金鑰，可安全進版控。
-- 執行狀態：未執行（人工執行後在 STATUS／對應 plan 打勾）。
-- 依賴：20260819171000_create_app_profiles.sql（public.is_admin()、app_profiles.status／role）。
--
-- 行為（2026-10-03 使用者定案：站長＝管理員）：
--   1. branch_track_list：一個分點一列，state = track（追蹤）／mute（取消追蹤，夜間自動入選不得再加回）。
--      列不存在 = 中立（由 VPS 夜間演算法自行決定是否自動入選）。
--   2. 這份名單驅動 VPS 夜間管線：口袋「追蹤分點同買」、個股 branch_tags.tracked、
--      /branch「我的追蹤」與 track index（pipeline/radar/seed_branches.py 的 sync_tracked_branches）。
--   3. updated_by／updated_at 由 trigger 蓋章（auth.uid()／now()），不信任前端帶入的值。
--   4. 初始種子：原 seed_branches.py 寫死的 30 個分點，state = 'track'，on conflict do nothing，
--      上線當天行為不變；重跑本檔不會覆蓋管理員之後的修改。
--
-- 資安說明（threat model）：
--   - 讀：已登入且 app_profiles.status = 'approved' 的使用者可 select（比照 branch_track_prefs 的
--     exists 子查詢；app_profiles 的 RLS 讓使用者只看得到自己那列，子查詢因此只會命中本人）。
--   - 寫（insert／update／delete）：只有 public.is_admin()（role = 'admin' 且 status = 'approved'，
--     SECURITY DEFINER，見 20260819171000）。一般使用者、pending／rejected、anon 一律被 RLS 擋下。
--     app_profiles 對一般使用者無 insert 權、update 僅限管理員，使用者無法自行升級成 admin。
--   - anon 對表本身無任何權限：先 revoke all，再只把 select/insert/update/delete 給 authenticated
--     （由 RLS 決定實際能做什麼；不給 truncate／references／trigger）。
--   - ⚠️ VPS 夜間管線的讀取路徑：public.branch_track_list_public() —— SECURITY DEFINER、STABLE、
--     只回 (branch_name, state) 兩欄，execute 只授權給 anon。管線用的是前端同一把 publishable key
--     （本來就公開在 web/lib/supabase.ts），因此**任何人都能讀到這份名單**（分點名稱＋追蹤／取消）。
--     這是刻意的取捨：名單是低敏感度資料（券商分點名稱），換來批次管線不需要任何特權金鑰
--     （service_role 可繞過全部 RLS，含 app_profiles／watchlist）。函式不回 updated_by／updated_at，
--     不暴露管理員身分或操作時間；也沒有任何寫入路徑。若日後認定名單本身需保密，改案見
--     STATUS／handoff 的後續事項，不要把 service_role 金鑰放進批次容器。
--   - branch_name 是管理員輸入：長度 1–64、不得含 C0／DEL／C1 控制字元、不得有前後空白。
--     前端只能以 React 文字節點渲染（不得 dangerouslySetInnerHTML、不得拼進 URL/HTML/SQL）；
--     管線端讀回時再驗一次同樣規則，任一列不合規整批不套用（fail closed）。
--   - state 以 check 限定 'track'／'mute'。

create table if not exists public.branch_track_list (
  branch_name text primary key,
  state text not null,
  updated_by uuid references auth.users(id) on delete set null,
  updated_at timestamptz not null default now(),
  constraint branch_track_list_state_check
    check (state in ('track', 'mute')),
  constraint branch_track_list_branch_name_check
    check (
      char_length(branch_name) between 1 and 64
      and branch_name = btrim(branch_name)
      and branch_name !~ '[\x01-\x1f\x7f-\x9f]'
    )
);

alter table public.branch_track_list enable row level security;

-- 稽核欄位由 DB 蓋章：updated_by = 目前 JWT 的使用者（SQL Editor 執行時為 NULL），updated_at = now()。
create or replace function public.branch_track_list_stamp()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_by := auth.uid();
  new.updated_at := now();
  return new;
end;
$$;

revoke all on function public.branch_track_list_stamp() from public;
revoke all on function public.branch_track_list_stamp() from anon, authenticated;

drop trigger if exists branch_track_list_stamp on public.branch_track_list;
create trigger branch_track_list_stamp
  before insert or update on public.branch_track_list
  for each row execute function public.branch_track_list_stamp();

drop policy if exists "branch_track_list_select_approved" on public.branch_track_list;
create policy "branch_track_list_select_approved" on public.branch_track_list
  for select to authenticated
  using (
    exists (
      select 1 from public.app_profiles p
      where p.user_id = auth.uid() and p.status = 'approved'
    )
  );

drop policy if exists "branch_track_list_insert_admin" on public.branch_track_list;
create policy "branch_track_list_insert_admin" on public.branch_track_list
  for insert to authenticated
  with check (public.is_admin());

drop policy if exists "branch_track_list_update_admin" on public.branch_track_list;
create policy "branch_track_list_update_admin" on public.branch_track_list
  for update to authenticated
  using (public.is_admin())
  with check (public.is_admin());

drop policy if exists "branch_track_list_delete_admin" on public.branch_track_list;
create policy "branch_track_list_delete_admin" on public.branch_track_list
  for delete to authenticated
  using (public.is_admin());

-- 權限：先收回預設授權，再只給 authenticated 需要的四種（PostgREST 需明確授權）
revoke all on public.branch_track_list from anon, authenticated;
grant select, insert, update, delete on public.branch_track_list to authenticated;

-- VPS 夜間管線唯讀入口（見檔頭資安說明）：只回兩欄、無參數、無寫入。
-- 函式擁有者（SQL Editor = postgres）即表擁有者，因此 SECURITY DEFINER 下不受上面 RLS 限制；
-- search_path 設空字串、全名引用，避免被同名物件劫持。
create or replace function public.branch_track_list_public()
returns table (branch_name text, state text)
language sql
stable
security definer
set search_path = ''
as $$
  select l.branch_name, l.state
  from public.branch_track_list l
  order by l.branch_name;
$$;

-- Supabase 的 default privileges 會把新函式的 execute 給 anon／authenticated，
-- 只 revoke from public 收不掉，必須逐一收回後再只授權 anon。
revoke all on function public.branch_track_list_public() from public;
revoke all on function public.branch_track_list_public() from anon, authenticated;
grant execute on function public.branch_track_list_public() to anon;

-- 初始種子：原 pipeline/radar/seed_branches.py 寫死的 30 個分點（上線當天行為不變）。
-- on conflict do nothing：重跑本檔不會蓋掉管理員之後改成 mute 的列。
insert into public.branch_track_list (branch_name, state) values
  ('永豐金-匯立', 'track'),
  ('凱基-松山', 'track'),
  ('兆豐-復興', 'track'),
  ('富邦-南京', 'track'),
  ('元大-南京', 'track'),
  ('永豐金-南京', 'track'),
  ('統一-南京', 'track'),
  ('凱基-三多', 'track'),
  ('元大-南屯', 'track'),
  ('元大-信義', 'track'),
  ('康和-永和', 'track'),
  ('元大-館前', 'track'),
  ('港商麥格理', 'track'),
  ('元大-大天母', 'track'),
  ('凱基-信義', 'track'),
  ('592E', 'track'),
  ('法銀巴黎', 'track'),
  ('永豐金-板新', 'track'),
  ('永豐金-內湖', 'track'),
  ('兆豐-新竹', 'track'),
  ('兆豐-中壢', 'track'),
  ('富邦-南港', 'track'),
  ('富邦-新竹', 'track'),
  ('富邦-新店', 'track'),
  ('富邦-嘉義', 'track'),
  ('元大-土城永寧', 'track'),
  ('統一-城中', 'track'),
  ('富邦-建國', 'track'),
  ('凱基-市政', 'track'),
  ('群益金鼎-大安', 'track')
on conflict (branch_name) do nothing;

-- ---------------------------------------------------------------------------
-- 驗證（以下皆為註解，貼整檔不會執行；需要時逐段取消註解、單獨執行）
-- ---------------------------------------------------------------------------
-- (1) RLS 開啟、policy 四條、表權限只有 authenticated 四種（另有 postgres/service_role 屬正常）、
--     函式 execute 只有 anon（另有 postgres/service_role 屬正常）、種子 30 列：
-- select relrowsecurity from pg_class where oid = 'public.branch_track_list'::regclass;
-- select policyname, cmd, roles, qual, with_check from pg_policies
--   where schemaname = 'public' and tablename = 'branch_track_list' order by policyname;
-- select grantee, privilege_type from information_schema.role_table_grants
--   where table_schema = 'public' and table_name = 'branch_track_list' order by grantee, privilege_type;
-- select grantee, privilege_type from information_schema.role_routine_grants
--   where routine_schema = 'public' and routine_name = 'branch_track_list_public' order by grantee;
-- select state, count(*) from public.branch_track_list group by state;
--
-- (2) anon 讀不到表（預期 ERROR: permission denied for table branch_track_list），
--     但呼叫函式只拿到兩欄（預期 30 列 branch_name／state）：
-- begin; set local role anon; select count(*) from public.branch_track_list; rollback;
-- begin; set local role anon; select * from public.branch_track_list_public(); rollback;
--
-- (3) anon 改不了（預期 ERROR: permission denied for table branch_track_list）：
-- begin; set local role anon; delete from public.branch_track_list; rollback;
--
-- (4) 一般 approved 使用者可讀不可寫（<USER_UUID> 換成 role='user' 且 approved 的 user_id；
--     select 預期 30 列；insert 預期 ERROR: new row violates row-level security policy；
--     update／delete 預期 0 rows affected）：
-- begin;
-- set local role authenticated;
-- select set_config('request.jwt.claims', '{"sub":"<USER_UUID>","role":"authenticated"}', true);
-- select count(*) from public.branch_track_list;
-- update public.branch_track_list set state = 'mute';
-- delete from public.branch_track_list;
-- insert into public.branch_track_list (branch_name, state) values ('測試分點', 'track');
-- rollback;
--
-- (5) 管理員可寫，且 updated_by 由 trigger 蓋成管理員本人（<ADMIN_UUID> 換成管理員 user_id；
--     預期 updated_by = <ADMIN_UUID>，即使 insert 時帶了別的值）：
-- begin;
-- set local role authenticated;
-- select set_config('request.jwt.claims', '{"sub":"<ADMIN_UUID>","role":"authenticated"}', true);
-- insert into public.branch_track_list (branch_name, state, updated_by)
--   values ('測試分點', 'mute', '00000000-0000-0000-0000-000000000000')
--   returning branch_name, state, updated_by;
-- rollback;
--
-- (6) 名稱限制（預期 ERROR: violates check constraint "branch_track_list_branch_name_check"）：
-- begin;
-- set local role authenticated;
-- select set_config('request.jwt.claims', '{"sub":"<ADMIN_UUID>","role":"authenticated"}', true);
-- insert into public.branch_track_list (branch_name, state) values (E'美林\n', 'track');
-- rollback;
--
-- (7) 從 VPS（或任何機器）以 publishable key 驗證管線讀取路徑（不需特權金鑰；預期 JSON 陣列 30 筆）：
-- curl -s -X POST 'https://eroycvbgfitvyulfbbnw.supabase.co/rest/v1/rpc/branch_track_list_public' \
--   -H 'apikey: <PUBLISHABLE_KEY>' -H 'Content-Type: application/json' -d '{}'
