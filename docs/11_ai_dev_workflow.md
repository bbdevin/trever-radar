# 11 AI 輔助開發與 Token 策略

## 1. 核心原則

1. **文件即上下文**:AI 每次任務只讀 `project-context.md`(<150 行)+ 該任務對應的 1 份規格文件 + 目標檔案。永遠不丟整個專案。
2. **規則進文件,不進對話**:任何架構決策做完立刻寫進 project-context.md 的「已做取捨」;下次任何模型(大小不拘)接手都從文件出發,對話歷史可拋棄。
3. **純函式評分層是省 token 的關鍵**:`Modules/Scoring` 無 I/O、無框架依賴,AI 修改評分規則時只需讀 04 文件 + 單一 Score 類 + 其測試,300 行上下文搞定。
4. **小模型可讀**:文件用表格與短句;每個模組資料夾放 10 行內的 `README.md`(這模組做什麼、入口在哪、別碰什麼)。

## 2. 每類任務的「該讀檔案清單」

| 任務 | 讀 |
|---|---|
| 改評分規則 | project-context + 04 + `Modules/Scoring/{該類}Score.php` + 對應 test |
| 加資料源 | project-context + 03 + `DataProviders/Contracts/{介面}` + 一個現有實作當範本 |
| 改前端頁 | project-context + 07 對應章節 + 該 Page.vue + 該頁 API controller |
| 改排程 | project-context + 08 + 該 Job |
| 改資料表 | project-context + 05 + migration(**改 05 文件先於改 code**) |

## 3. 防 AI 改壞(比省 token 更重要)

1. **Golden-file 測試**:`tests/fixtures/` 放固定日資料集(CSV),評分輸出快照比對;AI 動評分必跑,分數變了就會被看見——變動要嘛是預期(更新快照 + 在 PR 說明),要嘛是 bug。
2. Provider 測試:每個 Provider 用錄下的真實 API response(fixture)測 parser;來源改版時 fixture 更新即回歸。
3. CI(GitHub Actions):pint + phpstan(level 6)+ phpunit;不綠不併。
4. **一次一模組**:給 AI 的任務切到「單一模組單一行為」;跨模組需求先拆單。禁止「順手重構」——重構是獨立任務。
5. 驗收腳本:`php artisan radar:dry-run --date=2026-07-03` 用 fixture 全流程跑一遍出清單,人眼比對。

## 4. 分支與節奏

- trunk-based:`main` 保護,短分支(`feat/warrant-score`)+ PR + CI;自己開發也走 PR(給 AI code review 的掛載點)。
- Conventional Commits;每版打 tag(v0.1 = 匯入齊、v0.2 = 評分齊、v0.3 = 清單頁 = V1 MVP)。
- `CHANGELOG.md` 記「決策變更」而非流水帳。

## 5. V1 開發順序(每步可獨立驗收)

1. 專案骨架 + Docker + Breeze + CI(1 週)
2. 股票主檔 + 日K Provider(TWSE/TPEx)+ import_logs + 健檢(1 週)
3. 其餘盤後 Provider(法人/融資券/權證/注意處置)+ FinMind 分點(1–1.5 週)
4. 指標計算 + 還原價(0.5 週)
5. Scoring 全模組 + golden-file 測試(1.5 週)★ 最重要
6. 觀察清單管線 + 首頁(1 週)
7. 個股頁 + 籌碼 K 線 V1(1.5 週)
8. 探索頁 Tabs + 自選 + 系統頁(1 週)
→ 合計約 8 週兼職。每步結束更新對應文件。

## 6. 歷史回補策略(省 API 額度)

FinMind 免費額度有限:回補腳本做成可斷點續傳的 queue job(記錄已完成 stock×dataset×年份),夜間慢慢跑,一週內補完 1 年資料;分點資料最花額度,先補監控會用到的(市值前 800 檔),冷門股 lazy 補(首次被點開個股頁時排隊補)。
