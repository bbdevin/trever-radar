"""整站掛載圖:每一個畫面元件都要從某個路由入口**真的被畫出來**。

背景(defect):這一週兩次撞見同一種失敗——功能寫好了、測過了、記成已出貨,
卻從來沒出現在任何一頁。一次是期貨切片(a0c7b06,結構上不可能渲染),一次是
字級按鈕(a5ae269,整套機制都在、只差畫面上那一顆)。兩次都是整份測試全綠。
`test_futures_components_are_mounted.py` 用**手抄清單**釘住了那六個元件,但手抄
清單守不到下一個:新元件沒有人記得登記,正是它會漏掉的原因。

這一份改成**自動發現**:從 Next.js 的路由入口(`app/**/page.tsx`、`layout.tsx`)的
default export 出發,沿著「import 進來**而且**在某個元件的函式本體裡寫了
`<Name`」的邊走,走不到的元件就是紅燈。邊的**起點是元件**,不是檔案:同一個檔案
裡,只被一個死元件畫出來的元件,不算掛上。

刻意不守的:`components/ui/*`(shadcn 的元件庫,整組 vendored 進來,未用到的
primitive 是正常的)與 `components/Icons.tsx`(圖示集)。兩者都是「庫」,不是功能;
它們的東西一旦被功能元件用到,就在圖裡。

與期貨那份一樣,不執行任何東西:註解與字串先換成等長空白,所以被註解掉的
`{/* <Foo /> */}` **不算**呼叫點。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_futures_components_are_mounted import _strip_comments_and_strings

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB = REPO_ROOT / "web"

ROUTE_FILES = ("page.tsx", "layout.tsx", "template.tsx", "not-found.tsx", "error.tsx",
               "loading.tsx")

# 庫,不是功能(理由見模組說明)。
LIBRARY_PREFIXES = ("components/ui/", "components/Icons.tsx")

# 只把註解換掉、字串留著——import 的路徑就在字串裡。
_COMMENT_RE = re.compile(
    r"/\*.*?\*/|//[^\n]*|'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"|`(?:[^`\\]|\\.)*`",
    re.S,
)
_IMPORT_RE = re.compile(r"import\s+(type\s+)?([^;]*?)\s+from\s+[\"']([^\"']+)[\"']", re.S)

# 頂層宣告:元件(大寫)與 helper(小寫)都切成各自的函式本體,呼叫點的「所在
# 元件」是它前面最近的那一個。helper 也是圖裡的節點——`renderRows()` 裡畫的東西,
# 要看 renderRows 自己有沒有被某個可達的元件呼叫。
_TOP_LEVEL_RE = re.compile(
    r"^(?:export\s+(?:default\s+)?)?(?:async\s+)?"
    r"(?:function\s+(\w+)|const\s+(\w+)\s*(?::[^=\n]+)?=)",
    re.M,
)


def _strip_comments_only(raw: str) -> str:
    def repl(m: re.Match) -> str:
        text = m.group(0)
        if text.startswith("/"):
            return "".join(ch if ch == "\n" else " " for ch in text)
        return text
    return _COMMENT_RE.sub(repl, raw)


def _rel(path: Path) -> str:
    return path.relative_to(WEB).as_posix()


def _resolve(spec: str, here: Path, files: dict[Path, str]) -> Path | None:
    if spec.startswith("@/"):
        base = WEB / spec[2:]
    elif spec.startswith("."):
        base = (here.parent / spec).resolve()
    else:
        return None
    for cand in (Path(str(base) + ".tsx"), Path(str(base) + ".ts"), base / "index.tsx"):
        if cand.resolve() in files:
            return cand.resolve()
    return None


def _imports(path: Path, raw: str, files: dict[Path, str]) -> dict[str, tuple[Path, str]]:
    """本地名稱 → (來源檔, 來源裡的匯出名)。type-only import 不算。"""
    out: dict[str, tuple[Path, str]] = {}
    for m in _IMPORT_RE.finditer(_strip_comments_only(raw)):
        if m.group(1):
            continue
        clause, spec = m.group(2).strip(), m.group(3)
        target = _resolve(spec, path, files)
        if target is None:
            continue
        default = re.match(r"(\w+)\s*(?:,|$)", clause)
        if default:
            out[default.group(1)] = (target, "default")
        brace = re.search(r"\{([^}]*)\}", clause)
        if brace:
            for part in brace.group(1).split(","):
                part = part.strip()
                if not part or part.startswith("type "):
                    continue
                exported, _, local = part.partition(" as ")
                out[(local or exported).strip()] = (target, exported.strip())
    return out


def _spans(code: str) -> list[tuple[str, int, int, bool]]:
    """(名稱, 起, 迄, 是否 default export) 依出現順序。"""
    found = [(m.group(1) or m.group(2), m.start(), m.group(0).startswith("export default"))
             for m in _TOP_LEVEL_RE.finditer(code)]
    return [(name, start, found[i + 1][1] if i + 1 < len(found) else len(code), is_default)
            for i, (name, start, is_default) in enumerate(found)]


def build_graph(sources: dict[Path, str]) -> dict:
    """回傳節點、邊與可達集合。節點是 (檔案, 名稱)。"""
    files = {p.resolve(): raw for p, raw in sources.items()}
    code = {p: _strip_comments_and_strings(raw) for p, raw in files.items()}
    nodes: set[tuple[Path, str]] = set()
    default_of: dict[Path, str] = {}
    spans = {}
    for p, text in code.items():
        spans[p] = _spans(text)
        for name, _, _, is_default in spans[p]:
            nodes.add((p, name))
            if is_default:
                default_of[p] = name
        # `const X = forwardRef(...)` 之後在檔尾 `export default X;`(BranchFlowSection)。
        tail = re.search(r"^export\s+default\s+([A-Za-z_]\w*)\s*;?\s*$", text, re.M)
        if tail and (p, tail.group(1)) in nodes:
            default_of[p] = tail.group(1)

    edges: dict[tuple[Path, str], set[tuple[Path, str]]] = {n: set() for n in nodes}
    for p, text in code.items():
        local_names = {name for name, *_ in spans[p]}
        imported = _imports(p, files[p], files)
        for owner, start, end, _ in spans[p]:
            body = text[start:end]
            for name in local_names - {owner}:
                if re.search(r"<" + re.escape(name) + r"[\s/>.]", body) or \
                        re.search(r"(?<![\w.])" + re.escape(name) + r"\s*\(", body):
                    edges[(p, owner)].add((p, name))
            for local, (target, exported) in imported.items():
                if not re.search(r"<" + re.escape(local) + r"[\s/>.]", body):
                    continue
                name = default_of.get(target) if exported == "default" else exported
                if name and (target, name) in nodes:
                    edges[(p, owner)].add((target, name))

    roots = {(p, default_of[p]) for p in files
             if p.name in ROUTE_FILES and p.is_relative_to(WEB / "app") and p in default_of}
    reached = set(roots)
    queue = list(roots)
    while queue:
        for nxt in edges[queue.pop()]:
            if nxt not in reached:
                reached.add(nxt)
                queue.append(nxt)
    return {"nodes": nodes, "edges": edges, "roots": roots, "reached": reached}


def _is_component(name: str) -> bool:
    """PascalCase 才是元件;`CREDIBILITY_TOOLTIP` 這種全大寫常數不是。"""
    return bool(re.fullmatch(r"[A-Z][A-Za-z0-9]*", name)) and name != name.upper()


def load_sources() -> dict[Path, str]:
    paths = [*(WEB / "app").rglob("*.tsx"), *(WEB / "components").rglob("*.tsx"),
             *(WEB / "lib").glob("*.tsx")]
    return {p.resolve(): p.read_text(encoding="utf-8") for p in paths}


def unmounted(graph: dict) -> list[str]:
    """功能元件裡走不到的(庫除外)。"""
    out = []
    for path, name in sorted(graph["nodes"]):
        rel = _rel(path)
        if not _is_component(name) or rel.startswith(LIBRARY_PREFIXES):
            continue
        if (path, name) not in graph["reached"]:
            out.append(f"{rel}:{name}")
    return out


class WholeSiteMountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = load_sources()
        cls.graph = build_graph(cls.sources)

    def test_every_feature_component_is_reachable_from_a_route(self):
        self.assertEqual(
            unmounted(self.graph), [],
            "這些元件寫好了,但從任何一個路由入口都畫不到——使用者看到的是空白,"
            "而其餘測試全綠(a0c7b06、a5ae269 都是這個形狀)",
        )

    def test_the_graph_is_not_vacuous(self):
        """解析壞掉時「沒有任何元件走不到」會同時成立——那不是通過。"""
        roots = {_rel(p) for p, _ in self.graph["roots"]}
        self.assertIn("app/page.tsx", roots)
        self.assertIn("app/layout.tsx", roots)
        self.assertIn("app/stock/page.tsx", roots)
        feature = [n for n in self.graph["reached"]
                   if _is_component(n[1]) and not _rel(n[0]).startswith(LIBRARY_PREFIXES)]
        self.assertGreaterEqual(len(feature), 60)
        for must in ("components/FontScaleToggle.tsx:FontScaleToggle",
                     "components/FuturesAnomalyList.tsx:FuturesAnomalyList",
                     "app/stock/page.tsx:FuturesDailyBlock",
                     # `export default X;` 寫在檔尾的那一種(第一版解析器漏了它)
                     "components/BranchFlowSection.tsx:BranchFlowSection",
                     "components/Sparkline.tsx:Sparkline"):
            path, name = must.split(":")
            self.assertIn(((WEB / path).resolve(), name), self.graph["reached"], must)

    def _mutated(self, rel: str, old: str, new: str) -> dict:
        path = (WEB / rel).resolve()
        raw = self.sources[path]
        self.assertEqual(raw.count(old), 1, f"{rel} 裡 {old!r} 應該恰好一次")
        return build_graph({**self.sources, path: raw.replace(old, new)})

    def test_removing_the_only_call_site_turns_it_red(self):
        """a5ae269 的形狀:按鈕從 layout 拿掉,其他一切照舊。"""
        graph = self._mutated("app/layout.tsx", "<FontScaleToggle />", "")
        self.assertIn("components/FontScaleToggle.tsx:FontScaleToggle", unmounted(graph))

    def test_a_commented_out_call_site_does_not_count(self):
        graph = self._mutated("app/layout.tsx", "<FontScaleToggle />",
                              "{/* <FontScaleToggle /> */}")
        self.assertIn("components/FontScaleToggle.tsx:FontScaleToggle", unmounted(graph))

    def test_a_component_drawn_only_by_a_dead_component_is_not_mounted(self):
        """邊的起點是元件,不是檔案:同檔的死元件畫它,不算。"""
        rel = "components/StockCard.tsx"
        path = (WEB / rel).resolve()
        raw = self.sources[path]
        dead = "\nfunction DeadHolder() {\n  return <OrphanThing />;\n}\n" \
               "function OrphanThing() {\n  return null;\n}\n"
        graph = build_graph({**self.sources, path: raw + dead})
        missing = unmounted(graph)
        self.assertIn(f"{rel}:OrphanThing", missing)
        self.assertIn(f"{rel}:DeadHolder", missing)

    def test_importing_without_rendering_is_not_mounted(self):
        """import 還在、JSX 拿掉了——最容易在重構裡發生的那一種。"""
        graph = self._mutated("components/StockCard.tsx", "<Sparkline", "<SparklineGone")
        self.assertIn("components/Sparkline.tsx:Sparkline", unmounted(graph))


if __name__ == "__main__":
    unittest.main()
