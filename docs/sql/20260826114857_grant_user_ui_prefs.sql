-- 若表已建但搜尋歷史仍空白:補授權給 authenticated(PostgREST)
-- Supabase SQL Editor 執行本檔即可。

grant select, insert, update, delete on public.user_ui_prefs to authenticated;
grant select, insert, update, delete on public.search_history to authenticated;
