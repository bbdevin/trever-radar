# -*- coding: utf-8 -*-
"""`radar.mirror_crawl`:每站一個 worker、結果照原順序、死站退出、重試輪只用活站。"""
import threading
import time
import unittest

from radar.mirror_crawl import HostStats, crawl_in_order, live_hosts
from radar.providers import NoDataError

HOSTS = ["https://a", "https://b", "https://c"]


class CrawlInOrder(unittest.TestCase):
    def test_results_follow_target_order_whatever_the_workers_do(self):
        targets = [f"t{i}" for i in range(30)]

        def fetch(t, host, interval):
            # 站 a 慢,其他站快:完成順序與目標順序完全不同。
            time.sleep(0.02 if host == HOSTS[0] else 0.002)
            return [{"t": t, "host": host}]

        results, stats = crawl_in_order(targets, fetch, HOSTS, 0)
        self.assertEqual([r.target for r in results], targets)
        self.assertTrue(all(r.outcome == "done" for r in results))
        self.assertEqual(sum(s.done for s in stats.values()), 30)
        self.assertTrue(all(s.done > 0 for s in stats.values()), "三站都在幹活")
        slow = stats[HOSTS[0]].done
        self.assertLess(slow, max(stats[h].done for h in HOSTS[1:]),
                        "共用佇列:慢的站拿得少")

    def test_each_worker_is_pinned_to_its_host_and_gets_the_interval(self):
        seen = {}
        lock = threading.Lock()

        def fetch(t, host, interval):
            with lock:
                seen.setdefault(host, set()).add(threading.current_thread().name)
            self.assertEqual(interval, 5.0)
            time.sleep(0.005)
            return []

        crawl_in_order([f"t{i}" for i in range(12)], fetch, HOSTS, 5.0)
        self.assertEqual(set(seen), set(HOSTS))
        for host, threads in seen.items():
            self.assertEqual(len(threads), 1, f"{host} 只能有一個 worker")

    def test_empty_and_failed_are_classified_and_never_stop_the_crawl(self):
        def fetch(t, host, interval):
            if t == "t1":
                raise NoDataError("placeholder")
            if t == "t2":
                raise RuntimeError("HTTP 500")
            return [{"t": t}]

        results, stats = crawl_in_order(["t0", "t1", "t2", "t3"], fetch, HOSTS[:1], 0)
        self.assertEqual([r.outcome for r in results], ["done", "empty", "failed", "done"])
        self.assertEqual(results[2].error, "RuntimeError: HTTP 500")
        st = stats[HOSTS[0]]
        self.assertEqual((st.done, st.empty, st.failed, st.dead), (2, 1, 1, False))

    def test_a_dead_host_exits_and_the_others_finish_the_queue(self):
        targets = [f"t{i}" for i in range(40)]

        def fetch(t, host, interval):
            if host == HOSTS[0]:
                raise RuntimeError("timeout")
            time.sleep(0.002)
            return [{"t": t}]

        results, stats = crawl_in_order(targets, fetch, HOSTS, 0, dead_after=3)
        self.assertTrue(stats[HOSTS[0]].dead)
        self.assertEqual(stats[HOSTS[0]].failed, 3, "連續 3 次失敗就退出,不再拖")
        self.assertEqual(sum(1 for r in results if r.outcome == "failed"), 3)
        self.assertEqual(sum(1 for r in results if r.outcome == "done"), 37,
                         "死站沒抓到的由活站接手(死站手上那 3 檔留給重試輪)")
        self.assertEqual(live_hosts(stats), HOSTS[1:])

    def test_all_hosts_dead_marks_the_rest_failed_instead_of_hanging(self):
        def fetch(t, host, interval):
            raise RuntimeError("down")

        results, stats = crawl_in_order([f"t{i}" for i in range(20)], fetch, HOSTS, 0,
                                        dead_after=2)
        self.assertEqual(len(results), 20)
        self.assertTrue(all(r.outcome == "failed" for r in results))
        self.assertEqual(sum(1 for r in results if r.error == "no live mirror"), 20 - 6)
        self.assertEqual(live_hosts(stats), HOSTS, "全死時退回全部,讓重試輪至少試一次")

    def test_consecutive_counter_resets_on_success(self):
        n = {"calls": 0}

        def fetch(t, host, interval):
            n["calls"] += 1
            if n["calls"] % 2 == 0:
                raise RuntimeError("flaky")
            return []

        _, stats = crawl_in_order([f"t{i}" for i in range(20)], fetch, HOSTS[:1], 0, dead_after=3)
        self.assertFalse(stats[HOSTS[0]].dead, "交錯失敗不算連續失敗")

    def test_live_hosts_prefers_hosts_that_actually_delivered(self):
        stats = {"a": HostStats(done=0, empty=5), "b": HostStats(done=3), "c": HostStats(dead=True)}
        self.assertEqual(live_hosts(stats), ["b"])
        stats = {"a": HostStats(done=0, empty=5), "c": HostStats(dead=True)}
        self.assertEqual(live_hosts(stats), ["a"])


if __name__ == "__main__":
    unittest.main()
