# Handoff — 2026-08-27（融資未更新修復）

## 下一對話可貼上（Executor / Auto）

```
你是 Trever Radar 的 Executor（Cursor Auto）。請用繁體中文回覆。

必讀：AGENTS.md、docs/STATUS.md、handoff.md、docs/08 §0、docs/35、vps/README.md。

2026-08-27 融資事故：
- 主因：git pull 後多數 vps/scripts 失去 +x → 22:10 daily-margin Permission denied；21:00 branches 同理。
- 次因：17:40 抓 margin 過早（TWSE ~21:00 產製）→ empty。
- 已修：sync_code 強制 chmod +x；crontab 改 bash 呼叫；margin 主輪改 22:40；branches 不再抓 margin；腳本 git 100755。
- 確認 VPS live crontab 是否已換成 bash + 22:40；補抓 08-26 margin 是否已 deploy。

先輸出理解與 Scope，等確認再改碼（除非我已給明確指令）。
```

---

## Handoff 表

- **Current Goal**: 修復融資未更新；優化抓取時點
- **Current Branch**: `main`
- **Work Completed**:
  1. 根因確認：Permission denied + 17:40 過早 empty
  2. `lib.sh` sync_code 後 `chmod +x`
  3. `crontab.example` 一律 `bash …`；margin **22:40**
  4. `daily-branches` 移除 margin；`daily-margin` 落後 warn
  5. git 全部 scripts → 100755
- **Next**: VPS pull + 安裝 crontab + 手動跑 daily-margin 補 08-26
- **Files That Should Not Be Modified**: workflows/secrets；adj_factor；WAL checkpoint
