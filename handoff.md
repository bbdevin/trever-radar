# Handoff — 2026-08-27（S4 V2／Armed A1 程式碼驗收完成，正式 DB 未回算）

## 下一對話可貼上

```
你是 Trever Radar Executor。必讀 AGENTS.md、docs/project-context.md、docs/STATUS.md、handoff.md、docs/20、docs/22、docs/04。
S4 V2 已完成程式碼驗收：`S4_COMPRESSION_SETUP_V2` →
`S4_COMPRESSION_BREAKOUT_V2`，legacy S4 凍結；首頁 phase 各自顯示 setup/breakout/legacy strategy_meta，
episode 去重依完整 `daily_prices` 交易日曆。正式 DB 尚未回算，需另次人工確認；依本輪 Workflow D 提交並 push main。
不可改 schema/workflow/VPS/adj_factor。
Codex Multi-Agent V2 執行偏好：Sol high 做整體架構／複雜跨模組決策，Terra high 做一般實作／整合／驗收，Luna 做搜尋分析／簡單修改／測試／文件，最終 Code Review 固定 high；Luna 能做不用 Terra、Terra 能做不用 Sol，獨立工作平行、dependency 依序，spawn 明確 model override。此偏好不取代 Cursor Grok/Auto 流程或角色模型中立原則，可由使用者當次覆寫。
```

- **Done**: S4 V2 兩階段、S4 phase JSON／首頁標示；Terra Review = **APPROVE**，root pytest **92+52**、`npx tsc` 與 `npm run build` 成功。Armed A1 匯出契約補強：state IDs 必可由 `radar.stocks` 解析、權證逐檔取最新資料且 stale row 不可作今日 state source、缺 1 日／5 日漲幅時 state fail closed；Luna High 最終 Review = **APPROVE**，針對性 pytest **17+3**、全 pipeline（排除本機缺 `supabase` 的 intraday worker）**191+55**，**未正式 DB 回算**。未記 commit hash。

## 勝率稽核後續（2026-08-27，唯讀）

- 已完成策略／分點勝率定義與資料鏈稽核；未改排名、schema 或正式資料，未回算。
- 低風險待另案：branch export 日期修正與「今日買超」文案／正負淨額一致（尚未做）。
- 高風險待確認：排行 V2（`events_count`／`matured_samples`、成熟門檻、隔日沖定義與 point-in-time shadow diff）；需人工確認後才改 schema／正式回算。
- **前次 Done**: margin cron **21:20**；branches 第二輪 **22:00**；08-26 已 catchup
- **Branch**: `main`

## S4 V2／A1 後續 Confirmed Scope（2026-08-27）

- 總規劃已落檔：`docs/37_company_theme_group_buyback_branch_plan.md`；`docs/27` 已同步 G3 分期與 KB2 決議，`docs/STATUS.md` 已同步狀態。
- A1 程式／測試完成：state list ID 可由 `radar.stocks` 解析；stale warrant 不作今日 state source；缺 1 日／5 日漲幅時 fail closed。**尚未正式 DB 回算**。
- A2 是下一個人類決策關卡：需確認策略、首頁 Quiet／Armed／Triggered／Extended／Faded、綜合分與策略／分點勝率的單一定義；未確認前不改分數、門檻、排行或 schema。
- B 公司地址／股務代理、C 題材分類與近期熱度、D 集團 mapping、E1 庫藏股官方來源與 KB1，均為分期規劃，尚未宣稱完成。E2 為 point-in-time shadow 統計，需人工確認 schema／歷史回算。
- **KB2 `BUYBACK_BRANCH` 明確不實作**；E2 **不做交易獲利歸因**。不得將舊版 KB2 規劃復活成推測徽章。
- 下一位 Executor 先讀 `docs/37` §9，依序做 A2 對照／確認 → B/C/D PoC → E1 KB1；E2 先 shadow。不得改 workflow、VPS 排程、正式 DB 或執行全市場回灌。
