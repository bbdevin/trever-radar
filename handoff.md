# Handoff — 2026-08-27（S4 V2 程式碼驗收完成，正式 DB 未回算）

## 下一對話可貼上

```
你是 Trever Radar Executor。必讀 AGENTS.md、docs/project-context.md、docs/STATUS.md、handoff.md、docs/20、docs/22、docs/04。
S4 V2 已完成程式碼驗收：`S4_COMPRESSION_SETUP_V2` →
`S4_COMPRESSION_BREAKOUT_V2`，legacy S4 凍結；首頁 phase 各自顯示 setup/breakout/legacy strategy_meta，
episode 去重依完整 `daily_prices` 交易日曆。正式 DB 尚未回算，需另次人工確認；依本輪 Workflow D 提交並 push main。
不可改 schema/workflow/VPS/adj_factor。
```

- **Done**: S4 V2 兩階段、S4 phase JSON／首頁標示；Terra Review = **APPROVE**，root pytest **92+52**、`npx tsc` 與 `npm run build` 成功；正式 DB 尚未回算，需另次人工確認。未記 commit hash。

## 勝率稽核後續（2026-08-27，唯讀）

- 已完成策略／分點勝率定義與資料鏈稽核；未改排名、schema 或正式資料，未回算。
- 低風險待另案：branch export 日期修正與「今日買超」文案／正負淨額一致（尚未做）。
- 高風險待確認：排行 V2（`events_count`／`matured_samples`、成熟門檻、隔日沖定義與 point-in-time shadow diff）；需人工確認後才改 schema／正式回算。
- **前次 Done**: margin cron **21:20**；branches 第二輪 **22:00**；08-26 已 catchup
- **Branch**: `main`
