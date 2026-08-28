# Handoff — 2026-08-28（個股資訊補強；權證全市場分點 code-ready）

## 2026-08-28 最新交接

- **個股首屏 UI 已部署並完成正式站 QA（HEAD `55beda9`）**：名稱與報價／漲跌同行；產業下的活躍題材為嚴格 `eligible + active + heat_date=quote_date` 的 2+N 琥珀 chips；Decision Header 預設收合但分數／首要判讀常駐；其後為單一卡片行情 `dl`、單列可點基本資料概況與固定八 tab。`BasicInfoPanel` 的公司資料／題材／庫藏股連續三 section 及地址／股務／來源／題材／庫藏股／集團資訊均保留。正式 QA 抓到 `scrollIntoView` 讓初始頁面垂直偏移 189px，已改為只調 tablist 水平 `scrollLeft`；複驗 `scrollY=0`、無水平 overflow、Decision 可展開／收合、概況實際觸控後選中基本資料且三 heading 可見。深／淺色與基本資料圖證據在 `design-qa.md`；使用者深色偏好已恢復。未改 API／JSON／pipeline／schema／workflow／globals／KChart。

- 權證分點已完成安全 code-ready，**未碰正式 VPS／DB／cron／deploy**：新 `import-warrant-branch-trades --market all` 將 TWSE＋TPEx 當日有量有額的認購／認售、且標的是 active 普通股的權證合併抓取；ETF／指數、牛熊、未映射／inactive 標的排除。`--top` 是 cap，超出 fail closed、不偷裁；state JSON 原子記錄 ok／empty／error／pending，error 可 retry。既有 `backfill-warrant-branches` 可明確加 `--market all` 使用同一標的口徑；為相容正式 supervisor／舊手動指令，其預設仍是上市 Top 200，單一市場的 `--top` 仍為排序裁剪。
- `daily-branches.sh` 已明列 legacy `--warrants 200`；因全市場獨立輪尚未啟用，17:40／22:00 暫時保留上市 Top 200，避免過渡期資料斷層，正式切換時才改 `0`。新增未排程 `daily-warrant-branches-poc.sh`（20GB free-space、DB/source lock、owned-only BF pause/resume、hard timeout、未完整不發布）。唯讀 VPS 實數：TWSE 16,225 + TPEx 3,856 = 20,081，sleep=1.0 約 6–8h；DB 約 4.7GB／free 7.6GB < 20GB，故未啟用任何正式 cron、未寫正式資料，下一步必先容量／1日、5日與三日 benchmark，並獲人工批准。
- 本輪驗證：targeted pytest **12 passed**；完整 pipeline pytest **273 passed、58 subtests passed**；`compileall` 與 `git diff --check` 通過；PoC script 與 `lib.sh` 已透過 SSH stdin 交由 VPS `bash -n -s` 唯讀解析，兩者 exit 0（未 pull、未寫 DB、未動 cron）。

- 個股 UI 已補開高低收、量額／資料日與 compact 公司概況；點概況切至既有「基本資料」一級 tab。完整公司地址、股務代理電話／地址、官方來源、題材 lifecycle／來源與庫藏股 MOPS 事實仍保留；活躍題材仍須 `eligible + active + heat_date=quote_date`，沒有放寬。
- 個股權證分點不再被全市場 500 萬門檻清空：export 保留 `branches/warrant_branches.json`（全市場 `>=500萬`），另產出 `branches/warrant-stock-details/index.json` 與 `{stock_id}.json` 分片（個股 `>=100萬`）；100–499 萬只標「觀察」，500 萬以上「大額」。個股 code deploy 早於下一次資料 export 時會誠實 fallback 舊 500 萬檔。W5、首頁／Armed 2,000 萬與 `/branch` 均未改。
- `vps/scripts/daily-insti.sh` 已改成 quotes→insti→best-effort 權證主檔→當日權證彙總→indicators→scores→export/deploy；修正原本 master 在 aggregate 後執行造成當輪新權證 mapping 未反映。正式 crontab 仍是 16:10，沒有新增腳本／cron。
- 新測試 `pipeline/tests/test_warrant_branch_export.py` 覆蓋 2M detail-only、6M 兩檔皆有、<1M 皆無，以及五個 timeframe 與排序。完整 pipeline pytest `263 passed, 58 subtests passed`；TypeScript 通過；Terra 回報 Next build 通過。主協調重跑 Next build 在 Windows 長時間無新輸出後中止，不重複宣稱第二次成功；repo 未安裝 `playwright`，手機 verifier 已嘗試但無法執行，未做 QA bypass。
- **尚未執行正式資料寫入**：`import-themes`、`import-buybacks`、DB migration／全市場回算均未跑；也未手動改正式 crontab。push main 後 Pages 先部署 code，個股權證會 fallback；VPS 下一輪拉碼並 `export-json` 後才會產出 100 萬 index 與 per-stock shards。

## 下一對話可貼上

```
你是 Trever Radar Executor。必讀 AGENTS.md、docs/project-context.md、docs/STATUS.md、handoff.md、docs/37；依任務再讀 docs/20、docs/22、docs/04。
S4 V2、Armed A1 與 A2 code contract 已完成並通過測試。A2：綜合榜嚴格 `final>=65`（不再不足15保底；同分依 branch_score、再成交額）；S12 無 `concentration_avg20`／基期<=0 fail closed；strategy_meta 為版本化 status/effective_date/rationale/decision_ref/version。lifecycle v2（2026-08-27）依使用者恢復觀察決策把 S2/S5 設為 Shadow、回主要策略選擇器；不代表有效，未改公式、權重、`final`、selector cap 或 DB。舊 JSON 缺 metadata 前端完整 fallback。正式 DB 尚未回算，不可改 schema/workflow/VPS/adj_factor。
B+C+D 已完成程式/fixture/UI：`company_profiles` additive 官方公司欄位、題材 lifecycle、舊 SQLite runtime additive migration、個股 `industry/company_profile` safe fallback；C 只有完整來源成功才 active，partial／empty／`--limit`／失敗保留舊資料 stale、不自動 retired，TTL 35 日；個股 `company_themes/recent_theme_heat` 的 stale／retired／unknown、報價日不一致或未來資料均不得產生 H1／「近期可能相關題材」。官方華新麗華集團 mapping (`1605/2344/2492/5469/6116`)→`groups.json`/個股 `company_groups`→次要 `/group?id=`。群組摘要不依賴 radar pool。**2026-08-27 16:58 已受控正式 VPS `import-geo` 1,985、股務代理 1,985／1,985、3376 驗證及 `export-json` 2,410，Worker version `b377bc68-3c19-42eb-86f5-4e3c20d977d4`；回補 pause 後已 resume，備份為 `/home/huang/geo-before-import-20260827-1658.sql.gz`。**`import-themes`／`import-buybacks`、正式 DB migration／回算、排程/workflow/secrets 均未執行；不可自行執行。
個股 UI 已依使用者確認整併：一級順序為 K線／籌碼日報／三大法人／資券／大戶／基本資料／技術／權證；公司資料、題材、庫藏股在「基本資料」以連續三 section 顯示，沒有內部分頁。題材每筆連續列保留 name/status、分類日、來源更新日與來源（缺值誠實顯示，來源連結達 44px）；名稱區只會顯示最多兩個「活躍題材」+N，條件必須同時是 `eligible=true`、`status=active`、熱度日等於報價日；stale／retired／unknown 或日期不一致資料只在面板如實顯示。集團鑽取、官方資料日、MOPS 事實與舊 JSON fallback 均保留；純前端，未動資料契約。
E1 KB1 code 已完成：官方 MOPS `ajax_t35sc09` POST redirect→短效 `mopsov` HTML，兩步都帶 browser User-Agent／MOPS Referer；stdlib parser 只接受含 `出表日`（相容 `出表日期`）的正式 20 欄表（序號＋代號＋名稱…＋KB1 link 忽略…＋未完成原因），ROC→ISO、空值不補 0；數字序號的正式候選列即使代號空白／損壞也會整批 fail closed，不會部分匯入。`buybacks` additive table 用 deterministic plan ID 保留同股多計畫；`import-buybacks --as-of YYYY-MM-DD --days 1..366` 是手動 CLI，sii/otc 都成功才同一 transaction upsert，任一失敗只記 error log、零資料寫入。export／KB1 都要求 report/source 更新日不晚於資料日；KB1 只在 N 且期間 inclusive 時加既有 BUYBACK 15 分，不改 final／分項／H1；個股 compact 區只呈現 MOPS 事實，無 KB2／執行分點。**E1＋pocket＋JSON targeted pytest 45 passed、3 subtests；`import-buybacks` 未跑、未加排程或改 workflow/secrets。16:58 `export-json`／data Worker deploy 只發布既有快照，未更新庫藏股官方來源資料。**
E2 唯讀 shadow contract 已完成：`python -m radar branch-point-in-time-report --as-of YYYY-MM-DD --from YYYY-MM-DD --to YYYY-MM-DD --out PATH` 只接受既存實體 SQLite，以專用 `mode=ro` engine SELECT；DB 不存在或 out=DB 均 fail closed。輸出固定 JSON 的 universe／coverage、branch×stock rows、**獨立**買／賣 episode、unknown、low-buy／high-sell 與描述性 fwd5；市場日曆合併、20 日分位不讀未來、前15大缺列不當作沒有賣出。**不做 buy→sell 配對或配對 coverage，該規則 deferred 待另確認。**未跑正式 DB/VPS、未接 UI、未定門檻；不做交易獲利歸因或勝率宣稱。
Codex Multi-Agent V2 執行偏好：Sol high 做整體架構／複雜跨模組決策，Terra high 做一般實作／整合／驗收，Luna 做搜尋分析／簡單修改／測試／文件，最終 Code Review 固定 high；Luna 能做不用 Terra、Terra 能做不用 Sol，獨立工作平行、dependency 依序，spawn 明確 model override。此偏好不取代 Cursor Grok/Auto 流程或角色模型中立原則，可由使用者當次覆寫。
正式 VPS 2026-08-27 查核：SSH alias 是 `trever-vps`（不是 `trever_vps`）。16:57 實測 repo HEAD 為 `2b0de0c`、tracked clean；不要在分點回補活躍時自行 pull／migration／import。正式 crontab 已掛 TDCC 週六 06:30 與董監每月 16 日 07:00。權證回補已完成：`bf-warrant.done=2026-08-27T00:25:33+08:00`，`warrant_branch_hist` 12,644 rows／status ok。歷史分點尚未完成：最後完成 2025-10-29、累計 fetched 23,156；以 490 交易日目標估算目前走過 201 日（約 41%），仍餘約 289 日，這只是日期走訪進度、不是資料完整率，舊日期缺口較大，勿線性推 ETA。DB 4.3G＋WAL 91M、磁碟餘 7.9G。14:10 TPEx empty、15:00 10,629 筆成功。已清掉兩個殘留診斷 shell，並安全重啟 guard/supervisor；分點容器在 14:05–15:45 安靜窗內為 `paused=true`，15:46:05 自動 `UNPAUSE`，15:46:11 實測 `running|paused=false`，無 duplicate／restart。其後 16:58 受控完成 geo import/export（1,985／代理 1,985／1,985／3376 驗證／2,410 JSON／Worker `b377bc68-3c19-42eb-86f5-4e3c20d977d4`）及 data Worker deploy，回補已 resume；該 16:58 歷史事件當時未做程式碼 deploy、migration 或全市場重算。17:34 依使用者要求快速正式發布：VPS ff-only 至 `9d1dd69`，從新版 source-controlled `_build_strategy_meta` 僅原子更新 `radar.json.strategy_meta`（未重算／未改 DB／未全量 export），驗證 S2／S5 Shadow、version2、`retired_count=0`；data Worker version `d4f7df6a-dcaf-40be-b033-3c9a901971cb`。cleanup 已移除 flag／釋放 lock 並恢復回補；17:35:50 發現 cleanup 在 guard 記錄 `STATE=paused` 後 unpause，guard 未重驗 container 的 state-cache race，container 仍 running；17:36 已手動 pause 並確認 `paused=true`。本輪未改 guard 程式，19:30 應由既有 guard 依 state 自動 unpause，待後續驗證；GitHub Actions Pages code deploy 成功。
```

- **Done**: S4 V2 兩階段、S4 phase JSON／首頁標示；Armed A1 匯出契約；A2 綜合榜、S12 fail-closed 與 versioned strategy lifecycle contract；lifecycle v2 已依使用者決策將 S2/S5 恢復為 Shadow（JSON export targeted pytest **9 passed**）；docs/37 B+C+D 公司資訊、題材 freshness 與集團鑽取；E1 MOPS KB1 code／fixture／個股 UI；E2 唯讀 shadow contract。E1＋既有 pocket／JSON export pytest **45 passed、3 subtests passed**；完整 pipeline pytest **262 passed、58 subtests passed**；`npx tsc --noEmit` 與乾淨快取 `npm run build`（12/12 static pages、2/2 export）通過。repo 沒有 `npm run typecheck` script，勿把該指令記為驗收結果。目前工作站 `pipeline/.venv` 已依既有 `requirements.txt` 安裝 `supabase 2.31.0`；非阻塞環境債仍是 Node 20 未來不受 `@supabase/supabase-js` 支援。**16:58 正式 geo import/export 與 data Worker deploy 已完成；`import-themes`／`import-buybacks`、正式 DB 回算及 E1/E2 官方來源資料更新均未跑。**

- **2026-08-27 個股 UI（legacy QA 紀錄）**：當時已完成「基本資料」tab 整併、題材列的分類日／來源更新／來源可稽核顯示，以及名稱區活躍題材嚴格顯示；題材 URL 以「查看來源」呈現，保留 href、完整 title 與 aria-label。當時 verifier 使用 iPhone 13 descriptor／390×838；**目前已由 2026-08-28 最新交接取代，verifier 固定 375×812**。工作站仍未安裝獨立 `playwright`；最新正式站視覺與互動證據以本檔頂部及根目錄 `design-qa.md` 為準。未改 API／JSON／pipeline／schema／評分／VPS／workflow，勿把 UI 調整視為正式資料 import/export 授權。

## 勝率稽核後續（2026-08-27，唯讀）

- 已完成策略／分點勝率定義與資料鏈稽核；未改排名、schema 或正式資料，未回算。
- 低風險待另案：branch export 日期修正與「今日買超」文案／正負淨額一致（尚未做）。
- 高風險待確認：排行 V2（`events_count`／`matured_samples`、成熟門檻、隔日沖定義與 point-in-time shadow diff）；需人工確認後才改 schema／正式回算。
- **前次 Done**: margin cron **21:20**；branches 第二輪 **22:00**；08-26 已 catchup
- **Branch**: `main`

## S4 V2／A1／A2 後續 Confirmed Scope（2026-08-27）

- 總規劃已落檔：`docs/37_company_theme_group_buyback_branch_plan.md`；`docs/27` 已同步 G3 分期與 KB2 決議，`docs/STATUS.md` 已同步狀態。
- A1 程式／測試完成：state list ID 可由 `radar.stocks` 解析；stale warrant 不作今日 state source；缺 1 日／5 日漲幅時 fail closed。**尚未正式 DB 回算**。
- A2 code-level single definitions 已落地並文件化：綜合榜 `final>=65`（同分 branch_score→成交額）、S12 基期 fail-closed、state 同日／缺值 fail-closed、策略／分點 win 口徑、strategy lifecycle v2（S2/S5 Shadow）。正式 DB 回算、排行 V2、schema 與任何門檻／權重調整仍需另案人工確認。
- B 公司地址／股務代理、C 題材 lifecycle 與 D 集團 mapping 的程式／fixture／UI已完成；E1 MOPS KB1 code／fixture／UI 已完成。16:58 已受控完成 VPS `import-geo`／`export-json`（1,985、代理 1,985／1,985、3376 驗證、2,410 JSON、Worker `b377bc68-3c19-42eb-86f5-4e3c20d977d4`）；`import-themes`／`import-buybacks` 尚未執行。E2 point-in-time shadow CLI／JSON contract（獨立 buy／sell，無配對）已完成且測試通過；schema／歷史回算仍需人工確認。
- **KB2 `BUYBACK_BRANCH` 明確不實作**；E2 **不做交易獲利歸因**。不得將舊版 KB2 規劃復活成推測徽章。
- 下一位 Executor 先讀 `docs/37` §9；A2、B、C、D、E1 KB1 與 E2 shadow code 已完成，接續需先取人類確認的 E2 schema／歷史回算或其他 Confirmed Scope。B/D geo 與既有 JSON 已於 16:58 受控發布；C 題材 `import-themes` 與 E1 庫藏股 `import-buybacks` 仍不得自行執行，故該次 export 未更新其官方來源資料；不得改 workflow、VPS 排程、正式 DB 或執行全市場回灌。
