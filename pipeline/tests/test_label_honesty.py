"""使用者看得到的字串不得聲稱程式沒有算出來的東西。

本週抓到的例子(見 handoff / STATUS 的記錄):一個只靠「近 5 日淨買量」觸發、
價格與分位都不在條件裡的徽章被標成「關鍵分點」;策略卡與分點卡把
`fwd_5d > 0`(訊號日後 N 個交易日收盤有沒有比較高,沒有進場價以外的東西、沒有
出場規則、沒有回撤)印成「勝率」;同一組數字的平均值印成「平均報酬」;「融券
餘額下降」與「當日帶量大漲」的巧合被寫成「軋空」,兩者之間沒有任何因果檢驗;
「可信度分數」裸印一個數字,而那個數字有 55% 就是前面兩個統計量。每一個都是
人工細讀才抓到的,不會一直有人細讀。

**為什麼是白名單,不是分類器**
「不宣稱勝率」跟「勝率 68%」都含有被禁的詞,任何想自動分辨「這是免責聲明」還
是「這是誇大宣稱」的判準,兩個方向都會判錯。因此本檔不做語意分類:先用固定
詞彙表抓出「含有危險詞」的字串,再用一份人工審過的白名單放行——白名單裡的每
一條都要有人讀過、寫下判斷理由。新出現的字串(白名單裡沒有的組合)一律當作違
規,擋下 CI,直到有人審過、把它連同理由一起加進白名單。理由欄不是裝飾:它是
「這裡曾經有人判斷過」的紀錄,而審一行加白名單的 diff,正是抓下一個壞標籤的
時機。

**掃描範圍與作法**
- `web/**/*.tsx`、`web/**/*.ts`,排除 `web/.agents/**`(vendored skill 資料,大量
  無關英文命中)、`node_modules`、`.next`、`web/public/data`(產出的 payload,不
  是原始碼)。
- `pipeline/radar/**/*.py`——包含 `compute/scores.py` 的 `text=` 與 `pocket.py`
  的 tag `text`,這兩個模組把 reason/tag 文字整包塞進 JSON 送到瀏覽器,雖然人在
  Python 檔案裡,一樣是使用者看得到的字。

兩種語言都只抽「字串常值」,不是整行——banned word 出現在註解裡(解釋這個詞為
什麼危險的註解,正是我們想要人寫的)不算違規:
- **Python**:用 `ast` 解析,只取 `ast.Constant`(str)節點;module/function/class
  docstring(body 第一句、單獨一個字串 expression)另外標記後跳過——好幾個模組
  的長篇中文 docstring 合法地在討論「勝率」同時免責聲明它,不该因為在講這件事
  就被當成宣稱它。
- **TypeScript/TSX**:沒有現成的 Python AST 可用,改用一支小 tokenizer:依序找
  `/* 區塊註解 */`、`// 行註解`、或三種引號的字串,雙方在同一個 regex
  alternation 裡照原文順序比對,所以字串常值裡出現的 `//`(例如
  `"https://…"`)不會被誤判成註解起點;JSX 的 `{/* 註解 */}` 本身就是「一個區塊
  註解包在花括號運算式裡」,同一顆規則就處理掉了,不必另外處理。另外 JSX 的文
  字節點(`<div>本系統…</div>` 裡 `>` 與 `<` 之間那段)不是字串常值,tokenizer
  抓不到,所以額外把註解與字串換成空白後,在剩下的原文裡找「`>` 與 `<` 之間、
  不含 `{`/`}`、含中日韓字元」的片段——footer 那句全站免責聲明就是這樣寫的
  純文字,不是哪個變數的字串值。
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = REPO_ROOT / "web"
RADAR_DIR = REPO_ROOT / "pipeline" / "radar"

WEB_EXCLUDE_PARTS = {".agents", "node_modules", ".next"}


# 危險詞彙表:字面上聲稱「這個訊號會讓你賺錢/穩贏/因果已驗證」。
# 「報酬」單獨列為較軟的一條——repo 內目前只在 docstring/註解裡出現(讀者可用
# `git grep 報酬 -- pipeline/radar` 覆核),字串常值裡目前一次都沒有,noise 可控,
# 所以一併收進來,而不是只靠「報酬率」。
#
# 「關鍵分點」是保留名稱,不是危險詞彙的同一種——它在這裡是因為**這整件事就是
# 它引爆的**。那個徽章掛著這個名字上線了一段時間,而它的觸發條件裡沒有價格、
# 沒有分位;使用者自己看出來的,不是任何檢查抓到的。它現在專指「某分點在特定
# 個股上反覆低買高賣」(見 docs/13 §0、docs/27),而**產品中沒有任何東西有資格
# 這樣自稱**——量測顯示標籤再現率只有 1.6–5.4%,而唯一能授權它的方向 battery
# 還沒在修好的資料上跑過。在那之前,任何使用者看得到的字串出現這四個字都是錯的。
# battery 若通過並決定啟用這個名字,把這一條從表裡拿掉,連同一份決策紀錄。
BANNED_WORDS = [
    "勝率", "會賺錢", "賺錢", "獲利", "報酬率", "軋空", "保證",
    "必漲", "穩賺", "穩定獲利", "收益率", "盈利", "報酬",
    "關鍵分點",
]

# key: (相對 REPO_ROOT 的路徑, 完整字串常值)→ reason。
# 用路徑+完整字串而不是行號,是因為行號會在每次編輯後漂移,變成維護稅;用完整
# 字串當 key,搬動那一行不會讓白名單失效,但改了字才會——這正是我們要的效果。
#
# 下面 compute/ 底下那一批「不宣稱勝率」「不是損益」之類的免責聲明,就是這整類
# 缺陷之所以還抓得到的原因,不能被移掉;分組列一次原因,不逐條重複。
_PIT_DISCLAIMER_REASON = (
    "point-in-time / pctile 系列報表的免責字串:明講這裡只有價格分位與描述性"
    "觀察,沒有配對、沒有損益歸因、不宣稱勝率——這正是本檔要保護、不能被誤刪"
    "的那一類句子。"
)

ALLOWLIST: list[tuple[str, str, str]] = [
    (
        "pipeline/radar/compute/branch_point_in_time_report.py",
        "後續表現的描述性觀察；不是分點實際獲利、持倉成本或勝率。",
        _PIT_DISCLAIMER_REASON,
    ),
    (
        "pipeline/radar/compute/branch_point_in_time_series.py",
        "描述性觀察；不是分點實際獲利、持倉成本或勝率。",
        _PIT_DISCLAIMER_REASON,
    ),
    (
        "pipeline/radar/compute/branch_ranking_v2_shadow.py",
        "上述事件中 forward_returns fwd_5d 已可計算者;勝率與平均報酬只用這些。",
        "唯讀 shadow 報表(docs/13 §8 稽核用)裡 `definitions` 的一條說明文字,"
        "描述的是既有 V1 欄位『勝率/平均報酬』(本身已在別處免責揭露)的分母組"
        "成,不是新的宣稱;這份報表只給人類拿數字決定門檻,不對外呈現。",
    ),
    (
        "web/app/branch/page.tsx",
        "沒有進出場規則、不是損益,也不代表該分點實際獲利。",
        "分點頁『可信度分數』tooltip 的揭露句:明講分數裡量的東西不是損益、不"
        "代表實際獲利——同一顆 tooltip 也是 461a2cf 用來修正這批標籤問題的地"
        "方,句子本身是解法而不是問題。",
    ),
    (
        "web/app/layout.tsx",
        "本系統僅彙整公開市場資料供個人研究,非投資建議;訊號不保證獲利;投資人應自行判斷並承擔風險。資料來源:臺灣證券交易所、證券櫃檯買賣中心。",
        "全站 footer 的法遵免責聲明,明講訊號不保證獲利、非投資建議——這是唯"
        "一應該出現『保證』『獲利』兩個詞放在一起的地方。",
    ),
    (
        "web/lib/format.ts",
        "融券回補軋空",
        "S13 徽章改名(見 461a2cf)的顯示期轉場常數:VPS 尚未跑過新一輪 export "
        "前,舊 payload 的 `reasons[].text` 仍會是這個舊字串,`legacyReasonText` "
        "只用它來比對、換成新字樣『融券減少＋帶量大漲』後才顯示,這個舊字串本"
        "身從不直接印給使用者看;新 export 上線、舊字樣不再出現後可依註解裡的"
        "指示整段刪除。",
    ),
    (
        "web/components/PocketBadges.tsx",
        "關鍵分點同買",
        "K1_KEY_BUY → T1_TRACKED_BUY 改名(見 9a79fe7 / 998acaa)的顯示期轉場常"
        "數,與上面 format.ts 那條同一形狀:舊 payload 的 tag `text` 仍是這個舊"
        "字串,`displayText` 只拿它比對,換成『追蹤分點同買』之後才顯示,舊字串"
        "本身不會到畫面上。這是保留名稱『關鍵分點』唯一被允許存在的地方——因為"
        "它的用途正是把那個名字從畫面上拿掉。新 export 上線後與 META 裡的 "
        "K1_KEY_BUY 條目一起刪除。",
    ),
]


def _allowlist_reasons() -> dict[tuple[str, str], str]:
    seen: dict[tuple[str, str], str] = {}
    for rel, literal, reason in ALLOWLIST:
        key = (rel, literal)
        assert key not in seen, f"allowlist 重複的 key: {key!r}"
        seen[key] = reason
    return seen


# ---------------------------------------------------------------------------
# Python: 用 ast 抽字串常值,跳過 docstring。
# ---------------------------------------------------------------------------

def _docstring_ids(tree: ast.Module) -> set[int]:
    ids: set[int] = set()
    doc_holders = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if isinstance(node, doc_holders) and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                ids.add(id(first.value))
    return ids


def _py_string_literals(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    skip = _docstring_ids(tree)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in skip:
                continue
            out.append(node.value)
    return out


# ---------------------------------------------------------------------------
# TS/TSX: 一支小 tokenizer,依序比對「區塊註解 / 行註解 / 字串」,字串內容
# 原文照抄(不處理跳脫序列;本檔要比對的中文字串裡都沒有跳脫字元)。
# ---------------------------------------------------------------------------

_TS_TOKEN_RE = re.compile(
    r"/\*.*?\*/"                     # block comment(含 JSX 的 {/* ... */}）
    r"|//[^\n]*"                     # line comment
    r"|'(?:[^'\\\n]|\\.)*'"          # single-quoted
    r"|\"(?:[^\"\\\n]|\\.)*\""       # double-quoted
    r"|`(?:[^`\\]|\\.)*`",           # template literal(可跨行)
    re.S,
)


def _strip_ts_comments_and_strings(raw: str) -> str:
    """把註解與字串常值換成等長空白(換行留著),留下其餘原文——包含 JSX text。

    JSX 的文字節點(`<div>本系統…</div>` 裡 `>` 與 `<` 之間那段)不是字串常值,
    tokenizer 抓不到;要另外掃,而掃之前得先把字串與註解清乾淨,免得字串裡的
    `<`/`>`(理論上少見,但別假設沒有)被誤判成標籤邊界。
    """
    out = []
    last = 0
    for m in _TS_TOKEN_RE.finditer(raw):
        out.append(raw[last:m.start()])
        token = m.group(0)
        out.append("".join(ch if ch == "\n" else " " for ch in token))
        last = m.end()
    out.append(raw[last:])
    return "".join(out)


# `>` 與 `<` 之間、不含 `{`/`}`(避開 JSX 運算式)、含至少一個中日韓字元的一段
# ——JSX 文字節點就長這樣。
_JSX_TEXT_RE = re.compile(r">([^<>{}]*[一-鿿][^<>{}]*)<")


def _ts_string_literals(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8")
    out = []
    for m in _TS_TOKEN_RE.finditer(raw):
        tok = m.group(0)
        if tok.startswith("//") or tok.startswith("/*"):
            continue
        out.append(tok[1:-1])
    cleaned = _strip_ts_comments_and_strings(raw)
    for m in _JSX_TEXT_RE.finditer(cleaned):
        text = m.group(1).strip()
        if text:
            out.append(text)
    return out


def _web_files() -> list[Path]:
    files = []
    for ext in ("*.ts", "*.tsx"):
        for p in WEB_DIR.rglob(ext):
            rel_parts = p.relative_to(WEB_DIR).parts
            if any(part in WEB_EXCLUDE_PARTS for part in rel_parts):
                continue
            if rel_parts[0] == "public" and "data" in rel_parts:
                continue
            files.append(p)
    return sorted(files)


def _radar_files() -> list[Path]:
    return sorted(RADAR_DIR.rglob("*.py"))


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _scan() -> tuple[list[tuple[str, str, str]], set[tuple[str, str]]]:
    """回傳 (violations, all_flagged) — 皆為 (rel_path, literal, banned_word)/(rel_path, literal)。"""
    allowlist = _allowlist_reasons()
    violations: list[tuple[str, str, str]] = []
    flagged: set[tuple[str, str]] = set()

    for path in _radar_files():
        rel = _rel(path)
        for literal in _py_string_literals(path):
            for word in BANNED_WORDS:
                if word in literal:
                    flagged.add((rel, literal))
                    if (rel, literal) not in allowlist:
                        violations.append((rel, literal, word))
                    break

    for path in _web_files():
        rel = _rel(path)
        for literal in _ts_string_literals(path):
            for word in BANNED_WORDS:
                if word in literal:
                    flagged.add((rel, literal))
                    if (rel, literal) not in allowlist:
                        violations.append((rel, literal, word))
                    break

    return violations, flagged


class TestLabelHonesty(unittest.TestCase):
    def test_scanner_is_not_vacuous(self):
        """解析器壞掉、掃不到任何檔案時不能靜悄悄地全部通過。"""
        self.assertGreater(len(_radar_files()), 5, "pipeline/radar 下應該有多支 .py")
        self.assertGreater(len(_web_files()), 5, "web/ 下應該有多支 .ts/.tsx")
        # 白名單裡的字串至少要有一條真的能被目前的掃描邏輯找到,否則代表
        # BANNED_WORDS 或抽字串的邏輯壞了。
        _, flagged = _scan()
        self.assertTrue(flagged, "掃描邏輯找不到任何含危險詞的字串——解析器可能壞了")

    def test_no_unreviewed_assertive_label(self):
        """使用者看得到的字串裡,危險詞的每一次出現都必須是白名單裡審過的那一條。

        危險詞代表「這個標籤聲稱一個計算沒有算出來的機制」——本檔存在的理由見
        檔案開頭的事故記錄。若這裡失敗:
          1. 讀失敗訊息裡列出的檔案與完整字串,判斷它是不是誇大宣稱。
          2. 如果是誇大宣稱(字面上比程式實際算出來的東西講得更多)→ 改字串,
             讓它只描述真正被計算出來的東西,不要刪掉或放寬這個檢查。
          3. 如果它其實是免責聲明或其他正確用法(例如「不宣稱勝率」這種句子本
             身就含有被禁的詞)→ 把 (相對路徑, 完整字串) 連同一句實際理由加進
             本檔的 ALLOWLIST,而不是刪掉這個測試或這個詞。
        """
        violations, _ = _scan()
        if not violations:
            return
        lines = []
        for rel, literal, word in violations:
            lines.append(
                f"{rel}\n"
                f"  字串: {literal!r}\n"
                f"  命中危險詞: 「{word}」\n"
                f"  這個詞代表對使用者聲稱一種程式沒有算出來的機制(勝率/因果"
                f"軋空/穩賺保證之類)。若這段文字如實描述了計算出來的東西,把它"
                f"加進本檔的 ALLOWLIST 並寫下理由;否則請改字串本身。"
            )
        self.fail("\n\n".join(lines))


class TestAllowlistWellFormed(unittest.TestCase):
    def test_no_duplicate_keys(self):
        _allowlist_reasons()  # 內含 assert,壞了會直接炸在這裡

    def test_every_entry_has_a_reason(self):
        for rel, literal, reason in ALLOWLIST:
            self.assertTrue(
                reason and reason.strip(),
                f"{rel!r} / {literal!r} 的白名單項目沒有理由——理由是審核紀錄,"
                f"不是裝飾,不能留空",
            )

    def test_no_stale_entries(self):
        """白名單裡不能有指向『已經不存在的檔案/字串』的項目——那樣的項目

        看起來在放行什麼,實際上什麼都沒放行,等於悄悄把當初蓋住的洞重新打開
        (下次真的出現同樣字串時,人不會意識到需要重新審核)。
        """
        _, flagged = _scan()
        stale = [
            (rel, literal) for rel, literal, _ in ALLOWLIST
            if (rel, literal) not in flagged
        ]
        self.assertEqual(
            [], stale,
            "白名單裡有過時項目(檔案或字串已不存在,或字串裡已經沒有危險詞):"
            f"\n{stale}\n"
            "過時項目必須刪除,不能留著——它不再放行任何東西,只會讓人誤以為"
            "這裡曾經被審過而放鬆警覺。",
        )


if __name__ == "__main__":
    unittest.main()
