# 14 功能波段二(2026-07-08 使用者需求)

> 五項需求的規劃與取捨。UI 依 ui-ux-pro-max fintech 準則(SVG 圖示、4.5:1 對比、375/768/1024/1440 斷點、忌螢光紫粉)。
> 實作順序:1 → 2 → 3 本回合;4 需使用者開帳號(步驟見 §4);5 之後獨立回合。

## 1. K 線 日K/週K/月K ✅本回合

- **做法**:前端重取樣(日K → 週/月 bucket:開=首日開、高=區間最高、低=區間最低、收=末日收、量=加總)。零後端改動;均線/布林/MACD/KD/RSI 對重取樣後序列自動生效(如週K的 MA20 = 20週線,主流 App 慣例)。
- **UI**:K線工具列最前加「日K|週K|月K」segmented,記 localStorage;區間鈕依週期調整(週K:1年/3年/全部;月K:5年/全部)。
- **限制**:週/月K品質取決於日K深度——榜單股有上市以來全史;搜尋池個股 600 根日K → 週K約 120 根、月K約 28 根(可用但短),全市場深歷史回補完成後自然變完整。

## 2. 全站搜尋框 ✅本回合

- **資料**:export 產出 `stocks_index.json`(全市場 id/名稱/市場/產業,~2,400 筆 ~150KB),搜尋框聚焦時才載入。
- **UI**:頂欄搜尋框(手機:底欄放大鏡展開全螢幕搜尋)。前綴比對代號 + 子字串比對名稱,鍵盤上下 + Enter,點選 → `/stock?id=`。
- **個股 JSON 池擴大**:從「榜單聯集 82 檔」擴到「**全部評分池 ~950 檔**」;非聯集股 K 線裁近 600 交易日(控制部署體積 ~50MB)。搜尋到池外冷門股 → 顯示基本資料 + 「未入評分池(20日均額 <3,000萬),無K線快取」。全覆蓋等日後 JSON 搬 R2 再做。

## 3. 權證分點張數 ✅本回合(上市權證)

- **驗證結果**:富邦 zco 頁支援**上市權證代號**(069191 實測 15 列:群益金鼎買 1,054 張——多為發行商造市/避險部位);**上櫃權證(7 開頭)該頁無資料**,列為限制。
- **做法**:每晚對「權證榜 15 檔標的的當日成交金額第一大上市權證」各抓一次分點(≤15 請求),存同一張 `branch_trades` 表(stock_id = 權證代號)。
- **UI**:個股頁權證 Tab 的熱門權證表 → 龍頭權證列可展開「分點進出」小表(分點|買張|賣張|淨張)。
- **判讀提醒(UI 標註)**:權證分點大宗是發行商造市部位,異常訊號要看「非發行商分點」的大額買超。

## 4. 登入管理(Google OAuth)⏸ 等使用者開通金鑰

- **選型:Supabase Auth 免費層**(50,000 MAU,Google OAuth 內建,純前端 SDK 相容靜態站)。Cloudflare Access 仍是「真隔離」選項,但使用者要的是站內登入體驗 + 名單管理 → Supabase。
- **架構**:前端加 AuthGate(未登入 → 登入頁;Google 登入後查 `allowed_users` 表,不在名單顯示「待核准」);admin 頁面管名單(Supabase RLS:僅 admin email 可寫)。
- **誠實限制(已在 10/12 文件定調)**:資料 JSON 仍是靜態公開檔,前端登入是「體驗層」不是「安全層」;要真鎖資料需 CF Access 或把 JSON 搬進 Supabase/R2 + signed URL——名單想真保密再做。
- **使用者待辦**(做完貼給我 URL+anon key,我一回合接完):
  1. supabase.com 免費註冊 → New project
  2. Google Cloud Console → OAuth 同意畫面 + 憑證(Web),redirect URI 填 Supabase 提供的 callback
  3. Supabase Auth → Providers → Google 貼 Client ID/Secret
  4. 給我:Project URL + anon public key(可公開級金鑰)
- **不做**:自建帳密、email 註冊流(Google only,10 人夠用)。

## 5. LINE 推播機器人 📋 規劃(之後獨立回合)

- **選型**:LINE Notify 已停服 → 用 **Messaging API 免費層(500 則推播/月)**。10 人 × 每日 1 則 ≈ 220 則/月 ✓。
- **架構(維持零伺服器例外最小化)**:
  1. LINE Developers 建 Messaging API channel(免費)
  2. Webhook 用 **Cloudflare Worker 免費層**(唯一新增的常駐件,免費額度綽綽有餘):使用者加好友 → Worker 收 follow 事件 → userId 存 Workers KV
  3. nightly workflow 收尾加一步:讀 KV 名單 → push「今日綜合榜前 5 + 資金湧入族群」摘要(curl Messaging API)
- **訊息內容 V1**:文字摘要 + 網站連結;不做互動指令(那是聊天機器人,另一個坑)。
- **使用者待辦**:LINE Developers 帳號 + channel token(屆時給步驟)。

## 效益/成本總表

| # | 功能 | 後端 | 前端 | 阻塞 |
|---|---|---|---|---|
| 1 | 週/月K | 無 | 重取樣+工具列 | 無 |
| 2 | 搜尋 | index 匯出+池擴大 | 搜尋元件 | 部署體積 +~50MB(可接受) |
| 3 | 權證分點 | 夜抓 ≤15 請求 | 展開表 | 上櫃權證無來源 |
| 4 | Google 登入 | 無(Supabase 託管) | AuthGate+名單頁 | 使用者開 Supabase/GCP 金鑰 |
| 5 | LINE 推播 | Worker+KV+workflow 一步 | 無 | 使用者開 LINE channel;500則/月上限 |
