-- 應用使用者核准表(WP-B7 前端閘門)
-- 在 Supabase Dashboard → SQL Editor 貼上整段執行一次即可。
-- 只建表、觸發器與 RLS,不含任何金鑰,可安全進版控。
--
-- 行為:
--   1. 既有 auth.users(已登入過 Google)一律視為已核准。
--   2. a7033140327k@gmail.com 設為管理員(已存在或之後首次登入皆生效)。
--   3. 之後新登入者預設 pending,需管理員在站內 /admin 核准。
-- `/data` Worker 查本表 status=approved 才回 JSON。
-- Cloudflare Access 已於 2026-08-20 關閉。

create table if not exists public.app_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email text not null unique,
  display_name text,
  avatar_url text,
  role text not null default 'user' check (role in ('user', 'admin')),
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
  created_at timestamptz not null default now(),
  approved_at timestamptz,
  approved_by uuid references auth.users(id)
);

-- 已執行過舊版 SQL 的專案可重跑本檔;這兩欄是後補的。
alter table public.app_profiles add column if not exists display_name text;
alter table public.app_profiles add column if not exists avatar_url text;

create index if not exists app_profiles_status_idx on public.app_profiles (status);
create index if not exists app_profiles_email_idx on public.app_profiles (email);

alter table public.app_profiles enable row level security;

-- 管理員判定(SECURITY DEFINER 避開 RLS 遞迴)
create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.app_profiles
    where user_id = auth.uid()
      and role = 'admin'
      and status = 'approved'
  );
$$;

revoke all on function public.is_admin() from public;
grant execute on function public.is_admin() to authenticated;

drop policy if exists "profiles_select_own_or_admin" on public.app_profiles;
create policy "profiles_select_own_or_admin" on public.app_profiles
  for select to authenticated
  using (user_id = auth.uid() or public.is_admin());

drop policy if exists "profiles_update_admin" on public.app_profiles;
create policy "profiles_update_admin" on public.app_profiles
  for update to authenticated
  using (public.is_admin())
  with check (
    public.is_admin()
    and (
      user_id <> auth.uid()
      or (role = 'admin' and status = 'approved')
    )
  );

-- 新使用者自動建檔:管理員信箱直接核准,其餘 pending;同步 Google 名稱/大頭貼
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  admin_email constant text := 'a7033140327k@gmail.com';
  is_bootstrap boolean;
  meta_name text;
  meta_avatar text;
begin
  is_bootstrap := lower(coalesce(new.email, '')) = admin_email;
  meta_name := nullif(coalesce(new.raw_user_meta_data->>'full_name', new.raw_user_meta_data->>'name', ''), '');
  meta_avatar := nullif(new.raw_user_meta_data->>'avatar_url', '');
  insert into public.app_profiles (user_id, email, display_name, avatar_url, role, status, approved_at)
  values (
    new.id,
    lower(coalesce(new.email, new.id::text)),
    meta_name,
    meta_avatar,
    case when is_bootstrap then 'admin' else 'user' end,
    case when is_bootstrap then 'approved' else 'pending' end,
    case when is_bootstrap then now() else null end
  )
  on conflict (user_id) do update set
    email = excluded.email,
    display_name = coalesce(excluded.display_name, public.app_profiles.display_name),
    avatar_url = coalesce(excluded.avatar_url, public.app_profiles.avatar_url);
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- 回填:已存在的 auth.users = 已核准,並帶入 Google 名稱/大頭貼
insert into public.app_profiles (user_id, email, display_name, avatar_url, role, status, approved_at)
select
  u.id,
  lower(coalesce(u.email, u.id::text)),
  nullif(coalesce(u.raw_user_meta_data->>'full_name', u.raw_user_meta_data->>'name', ''), ''),
  nullif(u.raw_user_meta_data->>'avatar_url', ''),
  case when lower(coalesce(u.email, '')) = 'a7033140327k@gmail.com' then 'admin' else 'user' end,
  'approved',
  now()
from auth.users u
on conflict (user_id) do update set
  display_name = coalesce(excluded.display_name, public.app_profiles.display_name),
  avatar_url = coalesce(excluded.avatar_url, public.app_profiles.avatar_url);

-- 補既有列的名稱/大頭貼(欄位後加時)
update public.app_profiles p
set
  display_name = coalesce(p.display_name, nullif(coalesce(u.raw_user_meta_data->>'full_name', u.raw_user_meta_data->>'name', ''), '')),
  avatar_url = coalesce(p.avatar_url, nullif(u.raw_user_meta_data->>'avatar_url', ''))
from auth.users u
where u.id = p.user_id;

-- 指定管理員(無論先前角色/狀態)
update public.app_profiles
set
  role = 'admin',
  status = 'approved',
  approved_at = coalesce(approved_at, now())
where lower(email) = 'a7033140327k@gmail.com';

grant select, update on public.app_profiles to authenticated;
