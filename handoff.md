## Handoff

- **Current Goal**: 回補中途動態上線 — 規劃已落檔，等使用者確認 Scope
- **Branch**: `main`
- **Plan**: `docs/33_mid_backfill_publish_plan.md`
- **建議 Scope S1**: `mid-backfill-publish.sh` + 收編 `bf-cron-guard` + crontab 03/09/12/19（腳本內避開 daily 窗）；每次含 `compute-branch-stats`
- **備選 S2**: 只做腳本，不改 VPS crontab（手動觸發）
- **VPS 背景**: `radar-bf-*` 仍在跑（分點≈2025-12、權證≈2026-07）
- **Next**: 使用者勾選 S1/S2/S3 + stats 頻率後，Executor 實作
