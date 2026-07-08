import { createClient } from "@supabase/supabase-js";

// publishable key 為公開級金鑰(僅能配合 RLS 使用),可進版控。
// 秘密金鑰(sb_secret_*)永遠不進前端與 repo。
const SUPABASE_URL = "https://eroycvbgfitvyulfbbnw.supabase.co";
const SUPABASE_PUBLISHABLE_KEY = "sb_publishable_J87KLXMpmKX_ED471I13ug_ABiACBQY";

export const supabase = createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY);
