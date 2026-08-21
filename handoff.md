## Handoff

- **Current Goal**: 個股權證分頁已加「權證分點動向」(買／賣超萬元 + 權證展開)
- **Branch**: `main`
- **Done**: `WarrantBranchPanel` 讀 `/data/branches/warrant_branches.json` 依標的篩選;區間 1/2/5/30/120 日;門檻同分點頁 ≥500 萬
- **VPS 背景**: `radar-bf-*` 回補 + `bf-cron-guard`(cron 窗 pause)
- **Next**: push 後 Cloudflare Pages 部署;回補完可選再 stats/export
