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
        self.assertEqual(sum(1 for r in results if r.outcome == "failed"), 6)
        self.assertEqual(sum(1 for r in results if r.outcome == "pending"
                             and r.error == "no live mirror"), 20 - 6,
                         "沒人抓的標成 pending(重試輪 / 續抓 / 覆蓋率閘門照常處理)")
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

    def test_standby_host_joins_once_its_check_passes(self):
        """HIGH 1(b):開爬時只有 a 就緒;b 待命,第二次檢查才過,之後要真的分到工作。"""
        checks = {"b": 0}
        lock = threading.Lock()

        def check(host):
            with lock:
                checks[host] = checks.get(host, 0) + 1
                return checks[host] >= 2

        def fetch(t, host, interval):
            time.sleep(0.01)
            return [{"t": t}]

        results, stats = crawl_in_order(
            [f"t{i}" for i in range(80)], fetch, ["a"], 0,
            standby_hosts=["b"], standby_check=check, standby_every=0.02)
        self.assertEqual(sum(1 for r in results if r.outcome == "done"), 80)
        self.assertIn("b", stats)
        self.assertTrue(stats["b"].joined_late)
        self.assertGreater(stats["b"].done, 0, "待命站加入後要分到工作")
        self.assertGreaterEqual(checks["b"], 2)

    def test_standby_check_stops_when_the_queue_is_drained(self):
        calls = {"n": 0}

        def check(host):
            calls["n"] += 1
            return False

        results, _ = crawl_in_order(["t0", "t1"], lambda t, h, i: [], ["a"], 0,
                                    standby_hosts=["b"], standby_check=check, standby_every=0.01)
        self.assertEqual(len(results), 2)
        self.assertLessEqual(calls["n"], 3, "佇列空了就不再問")

    def test_stop_event_leaves_the_rest_pending_and_calls_on_result_for_the_done_ones(self):
        """SIGTERM 路徑:set 之後 worker 不再領新工作;沒抓的回 pending/stopped。"""
        stop = threading.Event()
        seen = []

        def fetch(t, host, interval):
            if t == "t5":
                stop.set()
            time.sleep(0.005)
            return [{"t": t}]

        results, _ = crawl_in_order([f"t{i}" for i in range(50)], fetch, ["a"], 0,
                                    stop=stop, on_result=lambda i, r: seen.append(i))
        done = [r for r in results if r.outcome == "done"]
        pending = [r for r in results if r.outcome == "pending"]
        self.assertEqual(len(done), 6)
        self.assertEqual(len(pending), 44)
        self.assertTrue(all(r.error == "stopped" for r in pending))
        self.assertEqual(sorted(seen), list(range(6)), "on_result 只為抓到的呼叫,帶原索引")

    def test_supervisor_gives_up_when_no_worker_is_alive_and_standby_never_passes(self):
        """第二次驗證(2026-10-07):活站全死 + 待命站永遠不過 → 以前會等到 7200 秒硬上限。
        現在:沒有活 worker、這一輪待命站也沒進來 → 收工,剩下的 pending/"no live mirror"。"""
        checks = {"n": 0}

        def check(host):
            checks["n"] += 1
            return False

        def fetch(t, host, interval):
            raise RuntimeError("down")

        t0 = time.monotonic()
        results, stats = crawl_in_order(
            [f"t{i}" for i in range(40)], fetch, ["a"], 0, dead_after=2,
            standby_hosts=["b", "c"], standby_check=check, standby_every=60)
        self.assertLess(time.monotonic() - t0, 5, "不能等到 standby_every / 硬上限")
        self.assertTrue(stats["a"].dead)
        self.assertEqual(sum(1 for r in results if r.outcome == "failed"), 2)
        self.assertEqual(sum(1 for r in results if r.outcome == "pending"
                             and r.error == "no live mirror"), 38)
        self.assertGreaterEqual(checks["n"], 2, "待命站至少各問過一次")

    def test_supervisor_keeps_waiting_while_a_worker_is_alive(self):
        """活 worker 還在抓時,待命站沒過不算理由收工。"""
        def check(host):
            return False

        def fetch(t, host, interval):
            time.sleep(0.01)
            return []

        results, _ = crawl_in_order([f"t{i}" for i in range(30)], fetch, ["a"], 0,
                                    standby_hosts=["b"], standby_check=check, standby_every=0.01)
        self.assertEqual(sum(1 for r in results if r.outcome == "done"), 30)

    def test_on_result_exception_does_not_kill_the_worker(self):
        """checkpoint 寫檔失敗(磁碟滿)不准殺掉 worker:記一行、繼續抓。"""
        calls = {"n": 0}

        def on_result(i, r):
            calls["n"] += 1
            if calls["n"] == 3:
                raise OSError("disk full")

        results, stats = crawl_in_order([f"t{i}" for i in range(20)], lambda t, h, i: [{"t": t}],
                                        ["a"], 0, on_result=on_result)
        self.assertEqual(sum(1 for r in results if r.outcome == "done"), 20)
        self.assertEqual(calls["n"], 20, "之後的 on_result 照常被呼叫")
        self.assertFalse(stats["a"].dead)

    def test_live_hosts_prefers_hosts_that_actually_delivered(self):
        stats = {"a": HostStats(done=0, empty=5), "b": HostStats(done=3), "c": HostStats(dead=True)}
        self.assertEqual(live_hosts(stats), ["b"])
        stats = {"a": HostStats(done=0, empty=5), "c": HostStats(dead=True)}
        self.assertEqual(live_hosts(stats), ["a"])


if __name__ == "__main__":
    unittest.main()
