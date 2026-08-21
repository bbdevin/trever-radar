## Handoff

- **Current Goal**: 盤中監控就緒（Fugle 免費 5 檔 + VPS 映像已重建）。
- **Current Branch**: `main` @ `55a2365`
- **Done**:
  - 導覽改「盤中監控／監控」
  - `FUGLE_WS_MAX_SUBSCRIBE=5`（基本用戶免費上限）
  - VPS `radar-worker` 重建煙測：`Loaded 5 … cap=5`，盤後正確收工
- **Note**: 今日 Armed≥5 時自選會被裁掉（未發動優先）；自選要進池需 Armed 少於 5，或之後付費／REST 補輪詢。
- **Next**: 下交易日 08:50 cron 自動跑。
