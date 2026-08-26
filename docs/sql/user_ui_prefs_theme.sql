-- 為既有 user_ui_prefs 補 theme 欄（深淺色綁帳號；預設 dark）
-- Supabase SQL Editor 執行一次即可。

alter table public.user_ui_prefs
  add column if not exists theme text not null default 'dark';

-- 可選：限制值（重複執行可能報 constraint 已存在，可忽略）
do $$
begin
  alter table public.user_ui_prefs
    add constraint user_ui_prefs_theme_check check (theme in ('dark', 'light'));
exception
  when duplicate_object then null;
end $$;

grant select, insert, update, delete on public.user_ui_prefs to authenticated;
