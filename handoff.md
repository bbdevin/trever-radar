# Handoff — 2026-08-27（A2 + docs/37 B+C+D 程式完成，正式 VPS 未執行）

## 下一對話可貼上

```
你是 Trever Radar Executor。必讀 AGENTS.md、docs/project-context.md、docs/STATUS.md、handoff.md、docs/37；依任務再讀 docs/20、docs/22、docs/04。
S4 V2、Armed A1 與 A2 code contract 已完成並通過測試。A2：綜合榜嚴格 `final>=65`（不再不足15保底；同分依 branch_score、再成交額）；S12 無 `concentration_avg20`／基期<=0 fail closed；strategy_meta 為版本化 status/effective_date/rationale/decision_ref/version，S2/S5 Retired 只在首頁「歷史資料」展開區。舊 JSON 缺 metadata 前端完整 fallback。正式 DB 尚未回算，不可改 schema/workflow/VPS/adj_factor。
B+C+D 已完成程式/fixture/UI：`company_profiles` additive 官方公司欄位、題材 lifecycle、舊 SQLite runtime additive migration、個股 `industry/company_profile` safe fallback；C 只有完整來源成功才 active，partial／empty／`--limit`／失敗保留舊資料 stale、不自動 retired，TTL 35 日；個股 `company_themes/recent_theme_heat` 的 stale／retired／unknown、報價日不一致或未來資料均不得產生 H1／「近期可能相關題材」。官方華新麗華集團 mapping (`1605/2344/2492/5469/6116`)→`groups.json`/個股 `company_groups`→次要 `/group?id=`。群組摘要不依賴 radar pool。正式 VPS `import-themes`/`import-geo`/`export-json`、正式 DB migration/回算、排程/workflow/secrets 均未執行；不可自行執行。
Codex Multi-Agent V2 執行偏好：Sol high 做整體架構／複雜跨模組決策，Terra high 做一般實作／整合／驗收，Luna 做搜尋分析／簡單修改／測試／文件，最終 Code Review 固定 high；Luna 能做不用 Terra、Terra 能做不用 Sol，獨立工作平行、dependency 依序，spawn 明確 model override。此偏好不取代 Cursor Grok/Auto 流程或角色模型中立原則，可由使用者當次覆寫。
```

- **Done**: S4 V2 兩階段、S4 phase JSON／首頁標示；Armed A1 匯出契約；A2 綜合榜、S12 fail-closed 與 versioned strategy lifecycle contract；docs/37 B+C+D 公司資訊、題材 freshness 與集團鑽取。C targeted pytest **29 passed**（lifecycle／完整、partial、empty、來源失敗、`--limit`、retired 保護、同名去重、舊 schema migration、H1 與日期 future-leak）；完整 pytest **236 passed、55 subtests**；`npx tsc --noEmit` 與乾淨快取 `npm run build`（12/12 static pages、2/2 export）均通過。repo 沒有 `npm run typecheck` script，勿把該指令記為驗收結果。非阻塞環境債仍是 Node 20 未來不受 `@supabase/supabase-js` 支援。**未正式 VPS import/export、未正式 DB 回算**。

## 勝率稽核後續（2026-08-27，唯讀）

- 已完成策略／分點勝率定義與資料鏈稽核；未改排名、schema 或正式資料，未回算。
- 低風險待另案：branch export 日期修正與「今日買超」文案／正負淨額一致（尚未做）。
- 高風險待確認：排行 V2（`events_count`／`matured_samples`、成熟門檻、隔日沖定義與 point-in-time shadow diff）；需人工確認後才改 schema／正式回算。
- **前次 Done**: margin cron **21:20**；branches 第二輪 **22:00**；08-26 已 catchup
- **Branch**: `main`

## S4 V2／A1／A2 後續 Confirmed Scope（2026-08-27）

- 總規劃已落檔：`docs/37_company_theme_group_buyback_branch_plan.md`；`docs/27` 已同步 G3 分期與 KB2 決議，`docs/STATUS.md` 已同步狀態。
- A1 程式／測試完成：state list ID 可由 `radar.stocks` 解析；stale warrant 不作今日 state source；缺 1 日／5 日漲幅時 fail closed。**尚未正式 DB 回算**。
- A2 code-level single definitions 已落地並文件化：綜合榜 `final>=65`（同分 branch_score→成交額）、S12 基期 fail-closed、state 同日／缺值 fail-closed、策略／分點 win 口徑、strategy lifecycle v1。正式 DB 回算、排行 V2、schema 與任何門檻／權重調整仍需另案人工確認。
- B 公司地址／股務代理、C 題材 lifecycle 與 D 集團 mapping 的程式／fixture／UI 已完成，正式 VPS `import-themes`／`import-geo`／`export-json` 尚未執行；E1 庫藏股官方來源與 KB1 仍為分期規劃。E2 為 point-in-time shadow 統計，需人工確認 schema／歷史回算。
- **KB2 `BUYBACK_BRANCH` 明確不實作**；E2 **不做交易獲利歸因**。不得將舊版 KB2 規劃復活成推測徽章。
- 下一位 Executor 先讀 `docs/37` §9；A2、B、C、D code 已完成，接續 E1 KB1；E2 先做唯讀 shadow。B/C/D 的正式 VPS import/export 仍不得自行執行；不得改 workflow、VPS 排程、正式 DB 或執行全市場回灌。
