"""個股期貨的五個畫面元件**真的被掛上去**,由 `.tsx` 原始碼直接解析。

背景(defect):a0c7b06 修掉的那個 bug 是「整個 futures 切片從未在 production
顯示過,而且結構上不可能顯示」——export 拿現貨日去問期貨,而 production 的常態
形狀是現貨比期貨新一天。整份測試是綠的,因為每一個測試都在模擬一個 production
從來不會產生的世界。

這一次守的是同一種失敗的另一個成因:**元件寫好了、測過了、沒有被掛上去**。
今天刪掉底下任何一個 JSX 呼叫點,881 個 python 測試與 47 個 node 測試**全部
照樣綠**——它們測的是純函式(`web/lib/futures.ts`)與 payload(`export_json`),
沒有一個測試碰過「這個元件出現在哪一頁」。使用者看到的是空白,而 CI 說一切正常。
兩個元件的作者各自在註解裡提過這件事一次。

手法與 `test_daily_branches_exit_codes.py` / `test_step_failure_notify.py` 相同:
不執行任何東西(那需要 node、需要 Next.js build),要守住的性質全部寫在文字裡。
註解與字串常值先換成等長空白再比對,所以被註解掉的呼叫點**不算**掛上去——
那正是最容易發生的那一種刪除。

這個測試釘住的是**一個環節**:「頁面元件 → 期貨元件」。它不證明頁面元件自己有被
Next.js 掛上(那由 `npm run build` 與路由慣例保證),但那一環從來不是出問題的
地方——出問題的是最末端那一行 JSX。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB = REPO_ROOT / "web"

HOME = WEB / "app" / "page.tsx"
STOCK = WEB / "app" / "stock" / "page.tsx"

# (元件, 應該畫它的檔案, 來源, 少了這一行 production 會怎樣)
#
# 「來源」有兩種,因為這個功能刻意是兩種:市場層級那兩個是獨立檔案(它們有
# 自己的 node 測試),個股頁那三個是同檔的 local function(它們只讀
# `StockJson["futures"]`,搬出去只會多一層 import)。兩種都要驗「拿得到」與
# 「畫出來」,只是「拿得到」的形狀不同。
MOUNTS = (
    (
        "FuturesOpenInterestDirection",
        HOME,
        WEB / "components" / "FuturesOpenInterestDirection.tsx",
        "首頁期貨分頁的未平倉方向四個計數整塊消失。名單常態是空的,這四個計數"
        "才是那個分頁每一天都有內容的部分——少了它,期貨分頁多數日子是一片空白。",
    ),
    (
        "FuturesAnomalyList",
        HOME,
        WEB / "components" / "FuturesAnomalyList.tsx",
        "首頁期貨分頁不再有今日成交量異常名單,docs/38 §1「名單短到能逐檔看」"
        "那份名單在畫面上完全不存在。",
    ),
    (
        "FuturesBadge",
        STOCK,
        None,
        "個股頁不再顯示「有/無個股期貨」。那是一個恆常事實的三態徽章"
        "(docs/38),而三態裡的 none 是 TAIFEX 官方清單的正面主張,不是沒東西可說。",
    ),
    (
        "FuturesAnomalyBlock",
        STOCK,
        None,
        "個股頁不再顯示契約當天有沒有舉旗。市場層級的名單還在,但點進個股看不到"
        "任何對應的東西——名單指向一個講不出理由的頁面。",
    ),
    (
        "FuturesDailyBlock",
        STOCK,
        None,
        "個股頁不再顯示當日成交口數、未平倉水位與日變化(docs/38 §7.14)。"
        "一天約 320 個契約有這些數字,舉旗的通常個位數——刪掉它,絕大多數契約"
        "在畫面上什麼都沒有,而那與「這個功能還沒上線」長得一模一樣。",
    ),
)

FUTURES_COMPONENTS = frozenset(name for name, *_ in MOUNTS)

_TS_TOKEN_RE = re.compile(
    r"/\*.*?\*/"                     # block comment(含 JSX 的 {/* ... */})
    r"|//[^\n]*"                     # line comment
    r"|'(?:[^'\\\n]|\\.)*'"          # single-quoted
    r"|\"(?:[^\"\\\n]|\\.)*\""       # double-quoted
    r"|`(?:[^`\\]|\\.)*`",           # template literal(可跨行)
    re.S,
)

# 頂層宣告的元件/函式。JSX 呼叫點的「所在元件」就是它前面最近的這一個。
_TOP_LEVEL_FN_RE = re.compile(r"^(?:export default )?function (\w+)", re.M)


def _strip_comments_and_strings(raw: str) -> str:
    """註解與字串常值換成等長空白(換行留著),其餘原文不動。

    等長是為了讓位移仍然對得回原始碼的行號;而「換成空白」而不是「刪掉」正是
    這個測試的重點之一:`{/* <FuturesDailyBlock … /> */}` 是一個**被拿掉的**
    呼叫點,不可以算數。
    """
    out: list[str] = []
    last = 0
    for m in _TS_TOKEN_RE.finditer(raw):
        out.append(raw[last:m.start()])
        out.append("".join(ch if ch == "\n" else " " for ch in m.group(0)))
        last = m.end()
    out.append(raw[last:])
    return "".join(out)


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


class FuturesComponentsAreMountedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = {path: _strip_comments_and_strings(path.read_text(encoding="utf-8"))
                    for path in (HOME, STOCK)}

    # ── 解析器自己 ──────────────────────────────────────────────────
    def test_the_parser_is_not_vacuous(self):
        """兩份原始碼都讀得到、清乾淨之後仍然是一份程式。

        解析器壞掉的下場是這整個檔案變成一組永遠綠的測試——比沒有這個檔案更糟,
        因為它看起來像是一層保護。
        """
        for path, code in self.code.items():
            with self.subTest(file=_rel(path)):
                self.assertGreater(len(code), 5_000, f"{_rel(path)} 讀起來太短")
                self.assertRegex(code, r"\breturn\b")
                self.assertTrue(_TOP_LEVEL_FN_RE.search(code),
                                "找不到任何頂層元件宣告,tokenizer 可能吃掉了原文")

    def test_a_commented_out_call_site_does_not_count_as_mounted(self):
        """把註解換成空白這件事本身要可證偽,否則上面每一條都可能是假的綠。"""
        stripped = _strip_comments_and_strings(
            "const a = 1;\n{/* <FuturesDailyBlock futures={x} /> */}\n"
            "// <FuturesBadge />\nconst b = 2;\n")
        self.assertNotIn("FuturesDailyBlock", stripped)
        self.assertNotIn("FuturesBadge", stripped)
        self.assertIn("const a = 1;", stripped)
        self.assertIn("const b = 2;", stripped)
        self.assertEqual(stripped.count("\n"), 4, "行數要保持不變")

    # ── 五個掛載點 ──────────────────────────────────────────────────
    def _render_sites(self, name: str, path: Path) -> list[int]:
        return [m.start() for m in
                re.finditer(r"<" + name + r"(?=[\s/>])", self.code[path])]

    def test_every_futures_component_is_available_in_the_page_that_renders_it(self):
        """「畫得出來」的前一半:import 進來,或就地宣告。"""
        for name, page, module, consequence in MOUNTS:
            with self.subTest(component=name):
                code = self.code[page]
                if module is None:
                    self.assertRegex(
                        code, re.compile(r"^function " + name + r"\b", re.M),
                        f"{_rel(page)} 裡找不到 {name} 的宣告;"
                        f"少了它 → {consequence}")
                    continue
                self.assertTrue(module.exists(), f"{_rel(module)} 不存在")
                self.assertRegex(
                    module.read_text(encoding="utf-8"),
                    re.compile(r"^export default function " + name + r"\b", re.M),
                    f"{_rel(module)} 的 default export 不叫 {name}")
                # 綁定名在「清乾淨」的原文裡找(被註解掉的 import 不算);
                # 模組路徑是字串常值,已經被換成空白了,所以回頭到原文去比對。
                self.assertRegex(
                    code, re.compile(r"^import " + name + r" from\b", re.M),
                    f"{_rel(page)} 沒有 import {name};少了它 → {consequence}")
                self.assertIn(
                    f'import {name} from "@/components/{name}";',
                    page.read_text(encoding="utf-8"),
                    f"{_rel(page)} 的 {name} 不是從 @/components/{name} 來的")

    def test_every_futures_component_is_actually_rendered(self):
        """這個檔案存在的理由。

        元件被 import 進來卻沒有任何 JSX 呼叫點,TypeScript 只會給一個 unused
        的提示(而個股頁那三個是同檔 local function,連提示都沒有),測試全綠,
        使用者看到空白。失敗訊息帶著後果,是因為下一個撞到這條測試的人,第一個
        念頭會是「刪掉這個測試」而不是「我剛剛拆掉了一塊畫面」。
        """
        for name, page, _module, consequence in MOUNTS:
            with self.subTest(component=name):
                sites = self._render_sites(name, page)
                self.assertTrue(
                    sites,
                    f"{_rel(page)} 裡沒有 <{name} …> 這個呼叫點。"
                    f"上線後的後果:{consequence}")

    def test_no_futures_component_is_rendered_only_by_another_one(self):
        """呼叫點必須落在**頁面**的元件裡,不可以只被另一個期貨元件畫出來。

        五個互相畫來畫去而沒有任何一個掛在頁面上,是一個完全自洽、完全綠、而且
        在畫面上什麼都沒有的狀態——上面那條測試單獨擋不住它。
        """
        for name, page, _module, consequence in MOUNTS:
            for site in self._render_sites(name, page):
                owners = _TOP_LEVEL_FN_RE.findall(self.code[page][:site])
                with self.subTest(component=name, owner=owners[-1] if owners else None):
                    self.assertTrue(owners, f"<{name}> 不在任何頂層元件之內")
                    self.assertNotIn(
                        owners[-1], FUTURES_COMPONENTS,
                        f"<{name}> 只被 {owners[-1]} 畫出來,而那本身就是期貨元件;"
                        f"{owners[-1]} 若沒掛上,後果是:{consequence}")

    # ── 兩塊不可以合併 ──────────────────────────────────────────────
    def test_the_stock_page_keeps_the_everyday_facts_and_the_flag_apart(self):
        """`FuturesDailyBlock` 與 `FuturesAnomalyBlock` 是**兩件事**,同頁並存。

        每日事實(成交多少口、未平倉多少、比前一個期貨交易日多了還是少了)對
        **每一個**帶 `daily` 的契約都成立,一天約 320 個;舉旗是例外,通常個位數。
        把兩塊合成一塊是一個很像「簡化」的改動,而它只有兩種收法:要嘛只畫舉旗
        的契約(320 個契約裡 310 幾個的日常數字整個消失),要嘛對沒舉旗的契約也
        畫一張異常卡(把「看過了、沒創高」講成一個異常)。兩種都是 docs/38 §7.7
        明文擋下的那件事。
        """
        code = self.code[STOCK]
        daily = self._render_sites("FuturesDailyBlock", STOCK)
        anomaly = self._render_sites("FuturesAnomalyBlock", STOCK)
        self.assertTrue(daily and anomaly,
                        "個股頁必須同時畫日常事實與舉旗,兩者不是同一件事")
        self.assertNotEqual(
            code[code.index("function FuturesDailyBlock"):],
            code[code.index("function FuturesAnomalyBlock"):],
            "兩個元件不可以塌成同一份實作")
        # 而且兩者各自讀自己的三態鍵:日常事實看 `daily`,舉旗看 `anomaly`。
        # 合併最常見的做法就是讓其中一塊改讀另一個鍵,那在這裡就是紅的。
        bodies = {}
        for name in ("FuturesDailyBlock", "FuturesAnomalyBlock"):
            start = code.index(f"function {name}")
            ends = [code.find(f"\nfunction {other}", start)
                    for other in ("FuturesDailyBlock", "FuturesAnomalyBlock",
                                  "TechnicalPanel", "WarrantPanel")]
            end = min([e for e in ends if e > start], default=len(code))
            bodies[name] = code[start:end]
        self.assertIn("contractsWithDaily", bodies["FuturesDailyBlock"],
                      "日常事實那一塊要依 `daily` 這個鍵決定畫誰")
        self.assertIn("flaggedContracts", bodies["FuturesAnomalyBlock"],
                      "舉旗那一塊要依 `anomaly` 這個鍵決定畫誰")
        self.assertNotIn("flaggedContracts", bodies["FuturesDailyBlock"],
                         "日常事實不得只畫舉旗的契約:310 幾個契約的數字會消失")


LAYOUT = WEB / "app" / "layout.tsx"

# 期貨以外、但**同一種失敗**已經實際發生過的掛載點。
#
# 這一組是上面那份調查的產物,不是順手加的:掃「元件有沒有真的被掛上」時發現
# `FontScaleToggle` **在整個 repo 裡沒有任何地方渲染**,而 `docs/36` 把它打勾
# 列在已完成底下。整套機制其實都在——`UserPrefsProvider` 掛好了、`globals.css`
# 有三段 `html[data-font-scale]` 規則、`layout.tsx` 的防閃爍腳本本來就在讀
# localStorage 的 `font_scale` 並套用 `body.zoom`——**只有那顆按鈕從來沒進畫面**。
# 也就是說偏好會被記住、會被套用,而使用者沒有任何方法設定它。
#
# 這正是 a0c7b06 那個 bug 的同一種形狀,只是完全沒有測試壓力去揭發它:
# 一個被文件記為交付完成的功能,在畫面上不存在,而 CI 全綠。
NON_FUTURES_MOUNTS = (
    (
        "FontScaleToggle",
        LAYOUT,
        WEB / "components" / "FontScaleToggle.tsx",
        "header 不再有字級切換鈕。偏好仍會被記住也仍會被套用(防閃爍腳本與 CSS "
        "都還在),但使用者沒有任何方法可以設定它——功能在文件上是 [x],在畫面上不存在。",
    ),
)


class NonFuturesComponentsAreMountedTests(unittest.TestCase):
    """同一種「寫好了、沒掛上」的失敗,發生在期貨以外的地方。

    與上面那個類別分開,是因為守的東西不同:上面守一個**功能**的五個環節,
    這裡守的是一份**清單**——調查發現 44 個元件裡有 20 個只有單一呼叫點,刪一行
    就靜默消失。這裡先放已經真的出過事的那一個;要擴成全站清單是另一件事,
    不該夾帶在期貨的檔案裡默默長大。
    """

    @classmethod
    def setUpClass(cls):
        cls.code = {
            path: _strip_comments_and_strings(path.read_text(encoding="utf-8"))
            for _name, path, *_rest in NON_FUTURES_MOUNTS
        }

    def test_every_listed_component_is_imported_and_rendered(self):
        for name, page, module, consequence in NON_FUTURES_MOUNTS:
            with self.subTest(component=name):
                self.assertTrue(module.exists(), f"{name} 的元件檔不存在")
                code = self.code[page]
                self.assertRegex(
                    code, rf"import\s+{name}\s+from",
                    f"{_rel(page)} 沒有 import {name};少了它 → {consequence}")
                self.assertRegex(
                    code, rf"<{name}[\s/>]",
                    f"{_rel(page)} 裡沒有 <{name} …> 這個呼叫點;"
                    f"少了它 → {consequence}")

    def test_the_font_scale_mechanism_is_still_whole(self):
        """按鈕只是最後一環;缺任何一環,掛上它也沒有用。

        這條測試存在的理由是:當初缺的**只有**按鈕,其餘三環都好好的。
        若日後有人反過來拿掉別環,症狀會是「按鈕按了沒反應」,而那比
        「按鈕不見了」更難查。
        """
        layout = LAYOUT.read_text(encoding="utf-8")
        self.assertIn("UserPrefsProvider", layout, "偏好 provider 不見了")
        self.assertIn("font_scale", layout, "防閃爍腳本不再讀 localStorage 的 font_scale")
        css = (WEB / "app" / "globals.css").read_text(encoding="utf-8")
        for scale in ("md", "lg", "xl"):
            with self.subTest(scale=scale):
                self.assertIn(f'html[data-font-scale="{scale}"]', css,
                              f"globals.css 少了 {scale} 那一段;按鈕會按了沒反應")


if __name__ == "__main__":
    unittest.main()
