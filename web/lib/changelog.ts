/**
 * 版本更新紀錄(/changelog 頁與 footer 版本號的唯一來源)。
 *
 * 版號規則:`主版.次版`。
 * - 次版:每一個「使用者看得到變化」的上線日 +1(同一天多次 commit 合併成一版;只動文件、
 *   排程、主機維運而畫面沒變的日子不發版)。次版可以超過 9(2.10 在 2.9 之後)。
 * - 主版:整站等級的里程碑才進位。
 *
 * 歷史是 2026-10-04 依 `git log`(2026-07-06 起約 590 個 commit)與 docs/STATUS.md
 * 的里程碑回推的,主版分界的理由:
 * - v1(2026-07-06):第一版上線——雷達頁、個股 K 線、評分榜、權證、分點、自選與策略,
 *   資料在雲端排程裡跑,網站對外公開。
 * - v2(2026-08-19):隔一個月後重新上線為「私人測試版」——Google 登入＋管理員核准門禁、
 *   資料改由獨立主機每日更新全市場(07-18 的資料搬家本身畫面沒變,使用者看得到的成果
 *   是這一波:全市場分點、資券、大戶、品牌與可安裝 App 都在 08-19 之後的幾天落地)。
 * - v3(2026-10-02):手機優先全面翻修——K 線/工具列重做、籌碼日報分段與分點標籤、
 *   權證與期貨分頁、區間損益(估算),以及 10-03/04 的速度優化。
 *
 * 之後每次使用者看得到的上線,在陣列**最前面**加一版(同日就併進當天那一版)。
 * 用字:寫使用者看到什麼變了,不寫檔名、程式或資料表;禁用詞由 changelog.test.ts 把關。
 */

export type ChangeKind = "new" | "improve" | "fix";

export type ChangeItem = { kind: ChangeKind; text: string };

export type Release = {
  version: string;
  date: string;
  title?: string;
  items: ChangeItem[];
};

export const KIND_LABEL: Record<ChangeKind, string> = {
  new: "新增",
  improve: "改善",
  fix: "修正",
};

export const CHANGELOG: Release[] = [
  {
    version: "3.2",
    date: "2026-10-04",
    title: "換頁變快、版本紀錄上線",
    items: [
      { kind: "new", text: "新增「版本更新紀錄」頁,頁尾隨時看得到目前是第幾版" },
      { kind: "new", text: "個股頁新增「多空」分頁(K線旁):把所有理由與風險分成多方、空方、背景三組列出" },
      { kind: "new", text: "多空分頁加入「價格位置」:上方壓力(前高、均線、成交密集區)、下方支撐、現價上下成交量比例" },
      { kind: "new", text: "K 線可開啟壓力/支撐虛線(預設關閉,在均線列切換)" },
      { kind: "improve", text: "多空分頁改成技術分析、籌碼分析、壓力分析三段,每段左多方、右空方全部列出;加入週K/月K、法人連續買賣超、分點囤貨出貨、大戶持股週變化與上方壓力價位" },
      { kind: "improve", text: "多空分頁每欄最上方新增「重點」,影響最大的事實(大額法人與分點買賣超、跌破或站回均線、接近壓力支撐等)排在前面;多方、空方欄改用淡紅、淡綠底色,分類標籤上色" },
      { kind: "improve", text: "技術指標併入多空分頁的「技術分析」:技術分、RSI14、量比、觀察價、失效價(含與收盤距離)放在段落最上方並依強弱上色,不再另外一張卡,也拿掉「技術訊號原文」收合區(每條訊號都已列在多空裡)" },
      { kind: "improve", text: "壓力分析併入多空分頁的「技術分析」,成為卡片裡的小標題段落,籌碼分析移到第二張;「怎麼算」改成直接顯示的幾行重點說明,不用再點開" },
      { kind: "improve", text: "多空分頁的籌碼分析加入低買高賣排行前段與區間損益估算前段分點的動向:近期買超、賣超或減碼點名列出,仍有持股的標示帳面為正或為負(估算)" },
      { kind: "improve", text: "個股頁上方評分卡精簡為「多方 N/空方 N」與最強一條多方、空方,K 線更早出現" },
      { kind: "improve", text: "站內換頁不再整頁重新載入,切換頁面明顯變快" },
      { kind: "improve", text: "點下去的當下就出現轉圈與頂部進度條,不會以為沒按到" },
      { kind: "improve", text: "首頁個股卡片預先載入,點進個股頁幾乎不用等" },
      { kind: "improve", text: "搜尋選定個股後立即跳轉,不再卡在寫入搜尋紀錄" },
      { kind: "improve", text: "可以左右滑動的分頁列、標籤列與表格,邊緣加上漸層與箭頭提示" },
      { kind: "improve", text: "網站圖示與程式檔改為長效快取,再次開啟更快" },
      { kind: "fix", text: "切換帳號或回到頁面時重新確認登入狀態,不會沿用上一個帳號的資料" },
    ],
  },
  {
    version: "3.1",
    date: "2026-10-03",
    title: "籌碼日報分點標籤、權證與期貨分頁",
    items: [
      { kind: "new", text: "籌碼日報的分點加上圓角標籤:地緣、隔日沖、追蹤、買低/賣高、總公司/外資" },
      { kind: "new", text: "籌碼日報新增「區間損益(估算)」,以平均成本估算各分點區間內的帳面變化" },
      { kind: "new", text: "期貨分頁:本檔的異常旗標、近 10 日紀錄與回測結果" },
      { kind: "new", text: "期貨每日摘要與近 10 日旗標歷史,合約名稱改成白話" },
      { kind: "new", text: "管理員可設定全站共用的追蹤分點名單" },
      { kind: "new", text: "囤貨/出貨分點新增 6 個月與 1 年區間" },
      { kind: "improve", text: "個股頁往下捲時,頂端固定一條精簡的股名與股價列" },
      { kind: "improve", text: "手機權證分頁:上方下拉切換券商,圖表放大到和 K 線一樣高" },
      { kind: "improve", text: "權證與期貨分頁移到籌碼日報後面" },
      { kind: "improve", text: "手機開啟 K 線時預設顯示主力買賣超" },
      { kind: "improve", text: "籌碼各區塊加上識別色與圖示,一眼分得出來" },
      { kind: "fix", text: "所有漲跌數字一律紅漲綠跌上色,未平倉增減也一樣" },
      { kind: "fix", text: "放大字級時權證區塊不再超出螢幕" },
      { kind: "fix", text: "上櫃公司地址改用中文解析,地緣分點判斷更準" },
    ],
  },
  {
    version: "3.0",
    date: "2026-10-02",
    title: "手機優先全面翻修",
    items: [
      { kind: "new", text: "囤貨/出貨分點卡:依區間內留下的張數判斷" },
      { kind: "new", text: "個股權證分頁:權證分點排行放在價格圖旁,各券商明細點開才載入" },
      { kind: "new", text: "券商代號與券商搜尋,每一家有掛牌的券商都能看走勢" },
      { kind: "new", text: "首頁期貨分頁先告訴你現貨有沒有跟上" },
      { kind: "improve", text: "手機 K 線工具列、圖例與價格軸重新設計,圖更大更好讀" },
      { kind: "improve", text: "籌碼日報分段呈現,手機上不再一長串" },
      { kind: "improve", text: "資料過期提示整合更新時間表" },
      { kind: "improve", text: "庫藏股資訊每日更新;個股 K 線預設看 3 個月" },
      { kind: "fix", text: "分點名稱亂碼、改名與已裁撤分點的顯示問題" },
      { kind: "fix", text: "權證分頁只排除有標記的席位,並標出同一發行商的權證" },
    ],
  },
  {
    version: "2.17",
    date: "2026-09-30",
    items: [{ kind: "improve", text: "期貨資訊移到個股頁自己的分頁,並說明旗標代表什麼" }],
  },
  {
    version: "2.16",
    date: "2026-09-24",
    items: [
      { kind: "fix", text: "當天評分會等分點資料到齊才定案,不再提早凍結" },
      { kind: "fix", text: "每日摘要標明是上市還是上櫃" },
    ],
  },
  {
    version: "2.15",
    date: "2026-09-23",
    items: [
      { kind: "new", text: "右上角加上字級切換按鈕(原本設定得到卻沒有按鈕)" },
      { kind: "improve", text: "期貨每個合約每天都有數字,未平倉方向也列出來" },
    ],
  },
  {
    version: "2.14",
    date: "2026-09-22",
    items: [
      { kind: "fix", text: "期貨資料改以期貨交易日對齊" },
      { kind: "fix", text: "期貨的資料新鮮度標示不再誤報過期" },
    ],
  },
  {
    version: "2.13",
    date: "2026-09-21",
    title: "期貨成交量異常",
    items: [{ kind: "new", text: "期貨成交量異常清單,上首頁分頁也在個股頁顯示" }],
  },
  {
    version: "2.12",
    date: "2026-09-15",
    items: [
      { kind: "new", text: "分點頁可以只看自己挑的分點" },
      { kind: "new", text: "個股頁標示這檔有沒有個股期貨" },
    ],
  },
  {
    version: "2.11",
    date: "2026-09-14",
    items: [
      { kind: "improve", text: "個股頁「技術」與「資券」分頁對調位置" },
      { kind: "fix", text: "分點資料偏少的日子,說明文字改得更正確" },
    ],
  },
  {
    version: "2.10",
    date: "2026-09-04",
    title: "用語更誠實",
    items: [
      { kind: "improve", text: "分點同買標章改名為「追蹤分點同買」,名稱只說明實際的判斷條件" },
      { kind: "improve", text: "各種標籤改成只描述實際算出來的東西,不誇大" },
      { kind: "improve", text: "可信度分數加上組成說明" },
      { kind: "fix", text: "個股頁補上籌碼事件理由" },
      { kind: "fix", text: "20 日價位分位改用還原價計算" },
    ],
  },
  {
    version: "2.9",
    date: "2026-09-03",
    items: [
      { kind: "new", text: "個股頁顯示各分點在這檔的買賣價位分位統計" },
      { kind: "new", text: "個股頁顯示分點隔日回吐次數" },
      { kind: "improve", text: "隔日沖分點的判定方式重新定義" },
    ],
  },
  {
    version: "2.8",
    date: "2026-09-02",
    items: [{ kind: "fix", text: "權證分點顯示真正的資料日期" }],
  },
  {
    version: "2.7",
    date: "2026-08-31",
    items: [
      { kind: "improve", text: "分點排行可以點進去看明細" },
      { kind: "fix", text: "追蹤分點的最新動向標示更準確" },
    ],
  },
  {
    version: "2.6",
    date: "2026-08-28",
    title: "個股頁版面整理",
    items: [
      { kind: "improve", text: "個股頁手機版重新排版:股名、報價與重點資訊層次更清楚" },
      { kind: "improve", text: "個股決策細節預設收合,需要時再展開" },
      { kind: "improve", text: "首頁雷達分頁重新排序" },
      { kind: "fix", text: "個股頁一開啟就停在最上方" },
    ],
  },
  {
    version: "2.5",
    date: "2026-08-27",
    items: [
      { kind: "new", text: "公司基本資料與集團關係,可以點進去看同集團公司" },
      { kind: "new", text: "庫藏股資訊" },
      { kind: "new", text: "新增「兩段壓縮」策略" },
      { kind: "improve", text: "個股基本資訊重新整理" },
    ],
  },
  {
    version: "2.4",
    date: "2026-08-26",
    title: "大戶持股與帳號偏好",
    items: [
      { kind: "new", text: "大戶持股分頁(集保週資料)與董監持股" },
      { kind: "new", text: "搜尋紀錄與字級跟著帳號走,換裝置也一樣" },
      { kind: "new", text: "右上角重新整理按鈕;主題與字級移進頭像選單" },
      { kind: "new", text: "K 線新增 6 個月區間" },
      { kind: "improve", text: "全市場個股每天都有分點資料" },
      { kind: "improve", text: "全站選取中的按鈕統一高對比樣式" },
    ],
  },
  {
    version: "2.3",
    date: "2026-08-25",
    title: "資券",
    items: [
      { kind: "new", text: "資券分頁:融資成本估算與使用率排行" },
      { kind: "improve", text: "所有個股都有自己的資料頁,不限評分名單" },
      { kind: "improve", text: "首頁分頁加上說明,資券放上首頁" },
      { kind: "improve", text: "盤中訊號最新的排最上面,並排除 ETF" },
      { kind: "improve", text: "籌碼分頁標示這檔有多久的分點歷史" },
    ],
  },
  {
    version: "2.2",
    date: "2026-08-21",
    items: [
      { kind: "new", text: "盤中「監控」頁,自選股自動納入監控" },
      { kind: "new", text: "權證分頁顯示權證分點買賣超" },
    ],
  },
  {
    version: "2.1",
    date: "2026-08-20",
    title: "Trever Radar 品牌與 App",
    items: [
      { kind: "new", text: "Trever Radar 品牌,可以安裝到手機主畫面" },
      { kind: "new", text: "首頁依當日最熱題材分組" },
      { kind: "new", text: "個股卡片顯示當日走勢小圖" },
      { kind: "new", text: "口袋名單分頁與理由標章" },
      { kind: "new", text: "個股頁新增三大法人與技術分頁,K 線與籌碼日報分開" },
      { kind: "fix", text: "iPhone 上返回鍵不再被狀態列擋住" },
    ],
  },
  {
    version: "2.0",
    date: "2026-08-19",
    title: "私人測試版上線",
    items: [
      { kind: "new", text: "改為 Google 登入,經管理員核准才能使用" },
      { kind: "new", text: "資料改由獨立主機每日自動更新全市場" },
      { kind: "new", text: "策略標示目前狀態,樣本不足會說明" },
      { kind: "improve", text: "手機 K 線工具列分成兩行,按鈕都看得到" },
      { kind: "improve", text: "分點頁統計卡改成 2×2 排列" },
      { kind: "fix", text: "個股頁不再左右溢出" },
    ],
  },
  {
    version: "1.8",
    date: "2026-07-19",
    items: [{ kind: "fix", text: "桌機 K 線副圖固定最小高度,比例設定確實生效" }],
  },
  {
    version: "1.7",
    date: "2026-07-18",
    items: [{ kind: "improve", text: "桌機 K 線副圖加大,分隔線可以拖曳調整" }],
  },
  {
    version: "1.6",
    date: "2026-07-14",
    items: [
      { kind: "improve", text: "K 線與分點進出圖手機版全面優化" },
      { kind: "improve", text: "分點進出標示籌碼日期,資料落後時提示" },
    ],
  },
  {
    version: "1.5",
    date: "2026-07-12",
    title: "任務導向介面",
    items: [
      { kind: "new", text: "盤中雷達即時面板" },
      { kind: "new", text: "未發動/已發動狀態追蹤,可一鍵加入今日追蹤" },
      { kind: "improve", text: "首頁榜單合併,分點頁改成左右主從版面" },
      { kind: "improve", text: "策略分成四類,理由與風險用顏色區分" },
      { kind: "fix", text: "首頁多處錯字" },
    ],
  },
  {
    version: "1.4",
    date: "2026-07-11",
    items: [
      { kind: "new", text: "淺色模式" },
      { kind: "new", text: "常見分點近 1/5/10/20 日買超排行" },
      { kind: "new", text: "個股 K 線下方顯示分點進出與主力買賣超副圖" },
      { kind: "improve", text: "首頁與自選股更好掃讀,榜單與表格樣式一致" },
    ],
  },
  {
    version: "1.3",
    date: "2026-07-10",
    title: "自選股與選股策略",
    items: [
      { kind: "new", text: "自選股,可設觀察價與停損價" },
      { kind: "new", text: "13 項選股策略與策略說明" },
      { kind: "new", text: "權證分點追蹤(依個股/依分點,近半年)" },
      { kind: "new", text: "分點可信度排行" },
      { kind: "new", text: "產業可往下看子題材" },
      { kind: "improve", text: "全站換上新介面元件" },
    ],
  },
  {
    version: "1.2",
    date: "2026-07-08",
    items: [
      { kind: "new", text: "資金流向樹狀圖,可切換產業/題材" },
      { kind: "new", text: "日/週/月 K 與全站搜尋" },
      { kind: "new", text: "籌碼日報、分點排行與個股分點進出" },
      { kind: "new", text: "個股卡片顯示公司簡介與題材" },
      { kind: "improve", text: "盤後資料分段更新,當天先到的先顯示" },
    ],
  },
  {
    version: "1.1",
    date: "2026-07-07",
    items: [
      { kind: "new", text: "手機優先的新版面" },
      { kind: "new", text: "權證雷達" },
      { kind: "new", text: "綜合評分榜與類股資金流向" },
      { kind: "new", text: "專業 K 線圖:均線、布林、MACD、KD、RSI" },
      { kind: "improve", text: "價格改用還原權值計算" },
    ],
  },
  {
    version: "1.0",
    date: "2026-07-06",
    title: "第一版上線",
    items: [
      { kind: "new", text: "籌碼雷達首頁" },
      { kind: "new", text: "個股 K 線頁與走勢小圖" },
      { kind: "new", text: "個股上市以來的完整歷史" },
    ],
  },
];

export const CURRENT_VERSION = CHANGELOG[0].version;

/** "2.10" → [2, 10];比較用。 */
export function versionParts(v: string): [number, number] {
  const [a, b] = v.split(".").map(Number);
  return [a, b];
}
