"""分點鏡像站平行爬:每站一個 worker、各自禮貌、單一寫者、結果照原順序回傳。

為什麼平行(docs/47 §8):循序爬是「全域 1 秒一請求、五站輪替」,每檔的耗時 =
max(1 秒, 來源回應時間) + 寫入。正式機實測 1.66 秒/檔(2026-10-07,54 分鐘)、
3.1 秒/檔(2026-10-05,102 分鐘)——來源一慢,整輪就跟著慢,而五站裡只要有一站
拖(ReadTimeout 30 秒 × 3 次重試),循序爬 1/5 的標的都要陪它等。

平行的形狀刻意保守:

* **每站一個 worker,釘在那一站**,間隔 = 循序爬的全域間隔 × 站數(1.0 × 5 = 5 秒)。
  單站看到的節奏與循序爬的**上限**一模一樣(循序爬輪替到同一站最快也是 5 秒一次),
  所以來源端的負載沒有變,只是不再讓一站的延遲拖住其他四站。總吞吐的上限是
  1 請求/秒(= 五站各 0.2/秒),2,000 檔約 33 分鐘,**不隨來源變慢而變長**(只要單站
  回應 < 5 秒)。
* **共用一條工作佇列**:慢的站自然拿得少、快的站拿得多;連續失敗 ``dead_after`` 次的站
  視為死站退出,剩下的標的由活站接手(第一輪抓失敗的標的照舊在重試輪再抓一次,
  重試輪只用活站)。
* **不寫資料庫**:worker 只抓與解析;寫入由呼叫端(主執行緒)在所有結果到齊之後
  **照目標原順序**做。順序承重:``branch_dim`` 的 id 是插入順序決定的,新分點的 id
  要與循序爬完全相同,資料才位元級一致(`test_branch_crawl_parity.py`)。
"""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field

from .providers import NoDataError

# 連續失敗幾次就把一站當死站(退出本輪;重試輪不再用它)。5 次 × (30 秒逾時 ×
# 3 次重試 + 退避) 最多約 9 分鐘的白等,之後那一站就不再拖任何人。
DEAD_AFTER_CONSECUTIVE_FAILURES = 5


@dataclass
class HostStats:
    done: int = 0
    empty: int = 0
    failed: int = 0
    consecutive_failed: int = 0
    dead: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Result:
    target: str
    outcome: str          # done / empty / failed
    rows: list[dict] | None
    error: str | None
    host: str | None


def crawl_in_order(targets: list[str], fetch, hosts: list[str], per_host_interval: float,
                   *, dead_after: int = DEAD_AFTER_CONSECUTIVE_FAILURES,
                   on_failure=None) -> tuple[list[Result], dict[str, HostStats]]:
    """用 ``hosts`` 各一個 worker 抓完 ``targets``,回傳**照 targets 順序**的結果。

    ``fetch(target, host, interval)`` 回傳列(list[dict]);``NoDataError`` = empty,
    其他例外 = failed。``on_failure(target, host, exc)`` 可選,失敗時立刻呼叫(印 log)。
    沒有活站把佇列抓完時,剩下的標的一律 failed(error="no live mirror"),呼叫端的
    重試輪與覆蓋率閘門照常處理。
    """
    stats = {h: HostStats() for h in hosts}
    results: dict[int, Result] = {}
    results_lock = threading.Lock()
    work: queue.Queue = queue.Queue()
    for i, t in enumerate(targets):
        work.put((i, t))

    def worker(host: str) -> None:
        st = stats[host]
        while True:
            try:
                idx, target = work.get_nowait()
            except queue.Empty:
                return
            try:
                rows = fetch(target, host, per_host_interval)
                res = Result(target, "done", rows, None, host)
                st.done += 1
                st.consecutive_failed = 0
            except NoDataError:
                res = Result(target, "empty", None, None, host)
                st.empty += 1
                st.consecutive_failed = 0
            except Exception as e:  # noqa: BLE001 - one target never kills the crawl
                res = Result(target, "failed", None, f"{type(e).__name__}: {str(e)[:100]}", host)
                st.failed += 1
                st.consecutive_failed += 1
                st.errors.append(res.error)
                if on_failure is not None:
                    on_failure(target, host, e)
            with results_lock:
                results[idx] = res
            if st.consecutive_failed >= dead_after:
                st.dead = True
                return

    threads = [threading.Thread(target=worker, args=(h,), name=f"branch-{h}", daemon=True)
               for h in hosts]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ordered: list[Result] = []
    for i, target in enumerate(targets):
        res = results.get(i)
        if res is None:
            res = Result(target, "failed", None, "no live mirror", None)
        ordered.append(res)
    return ordered, stats


def live_hosts(stats: dict[str, HostStats]) -> list[str]:
    """重試輪可用的站:沒死、而且本輪至少成功抓到過一檔(一檔都沒抓到的站不信)。
    一站都不剩時退回所有沒死的站;連那也沒有時退回全部(讓重試輪至少試一次)。"""
    good = [h for h, s in stats.items() if not s.dead and s.done > 0]
    if good:
        return good
    alive = [h for h, s in stats.items() if not s.dead]
    return alive or list(stats)
