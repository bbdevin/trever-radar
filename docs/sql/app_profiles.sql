-- 應用使用者核准表(WP-B7 前端閘門)
-- 在 Supabase Dashboard → SQL Editor 貼上整段執行一次即可。
-- 只建表、觸發器與 RLS,不含任何金鑰,可安全進版控。
--
-- 行為:
--   1. 既有 auth.users(已登入過 Google)一律視為已核准。
--   2. a7033140327k@gmail.com 設為管理員(已存在或之後首次登入皆生效)。
--   3. 之後新登入者預設 pending,需管理員在站內 /admin 核准。
-- 本輪不拆除 Cloudflare Access;Worker JWT 驗簽仍屬後續獨立步驟。

create table if not exists public.app_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email text not null unique,
  role text not null default 'user' check (role in ('user', 'admin')),
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
  created_at timestamptz not null default now(),
  approved_at timestamptz,
  approved_by uuid references auth.users(id)
);

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

-- 新使用者自動建檔:管理員信箱直接核准,其餘 pending
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  admin_email constant text := 'a7033140327k@gmail.com';
  is_bootstrap boolean;
begin
  is_bootstrap := lower(coalesce(new.email, '')) = admin_email;
  insert into public.app_profiles (user_id, email, role, status, approved_at)
  values (
    new.id,
    lower(coalesce(new.email, new.id::text)),
    case when is_bootstrap then 'admin' else 'user' end,
    case when is_bootstrap then 'approved' else 'pending' end,
    case when is_bootstrap then now() else null end
  )
  on conflict (user_id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- 回填:已存在的 auth.users = 已核准
insert into public.app_profiles (user_id, email, role, status, approved_at)
select
  u.id,
  lower(coalesce(u.email, u.id::text)),
  case when lower(coalesce(u.email, '')) = 'a7033140327k@gmail.com' then 'admin' else 'user' end,
  'approved',
  now()
from auth.users u
on conflict (user_id) do nothing;

-- 指定管理員(無論先前角色/狀態)
update public.app_profiles
set
  role = 'admin',
  status = 'approved',
  approved_at = coalesce(approved_at, now())
where lower(email) = 'a7033140327k@gmail.com';

grant select, update on public.app_profiles to authenticated;
