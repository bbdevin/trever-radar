"""Compute results must be a function of the data, not of the physical row order (docs/43 §1).

branch_trades_raw / daily_prices become WITHOUT ROWID, which changes the order
rows come back in when a query has no full ORDER BY.  Every spot that used to
depend on that order now uses an explicit total order or an order-free rule;
these tests feed the same rows in every order and require identical output.
"""
import itertools
import math
import random
import unittest

from radar.compute.branch_same_day import combine, merge_by_date
from radar.compute.scores import score_branch

DATES = ["2026-10-09", "2026-10-08", "2026-10-07", "2026-10-06", "2026-10-05", "2026-10-04"]
VOL = {d: 1_000_000 for d in DATES}    # 1,000 lots/day


def row(key, net):
    return {"branch_key": key, "branch_name": "N" + key, "net_lots": net,
            "buy_lots": max(net, 0), "sell_lots": max(-net, 0), "pct": None}


def permuted(rows_by_date, perm_seed):
    rnd = random.Random(perm_seed)
    out = {}
    for d, rows in rows_by_date.items():
        rows = list(rows)
        rnd.shuffle(rows)
        out[d] = rows
    return out


def _head_score_branch(rows_by_date, dates, volumes_by_date):
    """score_branch exactly as it was before docs/43 (commit b8720be), as the reference.

    The only differences in the current code are the tie-breaks of its two sorts
    (`branch_key` after net_lots); the selection rules are unchanged.
    """
    from radar.compute.scores import _branch_rows, _volume_lots, buy_concentration
    today = dates[0] if dates else None
    today_rows = _branch_rows(rows_by_date, today)
    if not today_rows:
        return None, [], []
    score = 0
    penalty = 0
    reasons, risks = [], []
    volume_lots = _volume_lots(volumes_by_date, today)
    buy_rows = sorted([r for r in today_rows if (r.get("net_lots") or 0) > 0],
                      key=lambda r: r["net_lots"], reverse=True)

    def add(points, code, txt, value=None):
        nonlocal score
        score += points
        reasons.append({"code": code, "points": points, "text": txt, "value": value})

    def hit(points, code, txt, value=None):
        nonlocal penalty
        penalty += points
        risks.append({"code": code, "points": -points, "text": txt, "value": value})

    best = None
    for r0 in buy_rows:
        key = r0["branch_key"]
        streak = cum_lots = cum_volume = 0
        branch_name = r0["branch_name"]
        for date in dates:
            match = next((r for r in _branch_rows(rows_by_date, date) if r["branch_key"] == key), None)
            if not match or (match.get("net_lots") or 0) <= 0:
                break
            v_lots = _volume_lots(volumes_by_date, date)
            streak += 1
            cum_lots += match["net_lots"] or 0
            cum_volume += v_lots or 0
        share = cum_lots / cum_volume if cum_volume > 0 else 0
        if streak >= 3 and share >= 0.03:
            candidate = (streak, cum_lots, branch_name, share)
            if best is None or candidate[0] > best[0] or candidate[1] > best[1]:
                best = candidate
    if best:
        streak, cum_lots, branch_name, share = best
        points = 30 if streak >= 5 else 20
        add(points, "B1_BRANCH_STREAK",
            f"分點【{branch_name}】連{streak}日買超{cum_lots:,.0f}張,佔期間成交量{share:.1%}",
            {"branch": branch_name, "streak": streak, "lots": round(cum_lots)})
    if volume_lots:
        significant = [r for r in buy_rows if (r["net_lots"] or 0) / volume_lots >= 0.01]
        if len(significant) >= 3:
            names = "、".join(r["branch_name"] for r in significant[:3])
            add(15, "B2_MULTI_BRANCH", f"{len(significant)}個分點同步買超逾成交量1%({names})",
                len(significant))
    buy_conc, avg_conc = buy_concentration(rows_by_date, dates, volumes_by_date)
    if avg_conc and buy_conc >= 0.15 and buy_conc >= avg_conc * 1.5:
        add(15, "B3_BUY_CONCENTRATION",
            f"前5大買超分點佔成交量{buy_conc:.0%},為近期均值{buy_conc / avg_conc:.1f}倍",
            round(buy_conc, 3))
    flows = []
    for date in dates[:3]:
        rows = _branch_rows(rows_by_date, date)
        if rows:
            flows.append(sum(r.get("net_lots") or 0 for r in rows))
    if len(flows) == 3 and all(f > 0 for f in flows):
        add(10, "B6_BIG_MONEY_FLOW", "前15大分點大戶淨流連3日為正", round(sum(flows)))
    yesterday_rows = _branch_rows(rows_by_date, dates[1]) if len(dates) > 1 else []
    for prev in sorted([r for r in yesterday_rows if (r.get("net_lots") or 0) > 0],
                       key=lambda r: r["net_lots"], reverse=True)[:5]:
        today_match = next((r for r in today_rows if r["branch_key"] == prev["branch_key"]), None)
        if today_match and (today_match.get("net_lots") or 0) < 0 \
                and abs(today_match["net_lots"]) >= prev["net_lots"] * 0.7:
            hit(20, "B_RISK_REVERSAL", f"分點【{prev['branch_name']}】昨日大買後今日反手賣出,疑似倒貨",
                prev["branch_name"])
            break
    return max(0, min(100, score - penalty)), reasons, risks


def random_case(rnd, distinct_nets):
    n = rnd.randint(2, 6)
    keys = [f"K{i:02d}" for i in range(n)]
    rows = {}
    for di, d in enumerate(DATES):
        if distinct_nets:
            # distinct non-zero nets on every day (HEAD's sorts were order-free then)
            nets = rnd.sample([v for v in range(-300, 301) if v], n)
        else:
            nets = [rnd.choice([-50, 30, 30, 120, 120]) for _ in keys]
        rows[d] = [row(k, v) for k, v in zip(keys, nets)]
    return rows


def _without_b1(result):
    score, reasons, risks = result
    b1 = sum(r["points"] for r in reasons if r["code"] == "B1_BRANCH_STREAK")
    return (None if score is None else score - b1,
            [r for r in reasons if r["code"] != "B1_BRANCH_STREAK"], risks)


def _expected_b1(rows_by_date):
    """B1 by its definition (docs/04 §2): the strongest qualifying branch under the
    total order streak↓, cumulative lots↓, share↓, branch_key↑."""
    best = None
    for r0 in rows_by_date[DATES[0]]:
        if r0["net_lots"] <= 0:
            continue
        streak = cum = vol = 0
        for d in DATES:
            m = next((r for r in rows_by_date[d] if r["branch_key"] == r0["branch_key"]), None)
            if not m or m["net_lots"] <= 0:
                break
            streak += 1
            cum += m["net_lots"]
            vol += VOL[d] / 1000
        share = cum / vol if vol else 0
        if streak >= 3 and share >= 0.03:
            rank = (-streak, -cum, -share, r0["branch_key"])
            if best is None or rank < best[0]:
                best = (rank, r0["branch_name"], 30 if streak >= 5 else 20)
    return None if best is None else (best[1], best[2])


class ScoreBranchOrderTests(unittest.TestCase):
    def test_everything_but_b1_equals_head_when_net_lots_are_distinct(self):
        """Only B1's selection rule changed (user-approved 2026-10-04); B2/B3/B6 and the
        reversal deduction must equal HEAD exactly whenever HEAD was order-free."""
        rnd = random.Random(43)
        changed_b1 = 0
        for i in range(3000):
            case = random_case(rnd, distinct_nets=True)
            shuffled = permuted(case, i)
            new, head = score_branch(shuffled, DATES, VOL), _head_score_branch(shuffled, DATES, VOL)
            self.assertEqual(_without_b1(new), _without_b1(head), (i, case))
            got = next(((r["value"]["branch"], r["points"]) for r in new[1]
                        if r["code"] == "B1_BRANCH_STREAK"), None)
            self.assertEqual(got, _expected_b1(case), (i, case))
            changed_b1 += new != head
        self.assertLess(changed_b1, 3000 * 0.05)   # the rule fix touches a small minority

    def test_tied_cases_are_permutation_invariant(self):
        rnd = random.Random(7)
        for i in range(300):
            case = random_case(rnd, distinct_nets=False)
            outs = {repr(score_branch(permuted(case, s), DATES, VOL)) for s in range(6)}
            self.assertEqual(len(outs), 1, (i, case))

    def test_b1_picks_the_longest_streak_whatever_the_row_order(self):
        # verifier repro b1.py: A 5-day streak/500 lots, B 3 days/600 lots. HEAD's
        # pairwise rule gave 20 or 30 depending on row order; now always A, 30.
        a = [100, 100, 100, 100, 100, -1]
        b = [100, 100, 400, -1, -1, -1]
        base = {d: [row("K_B", b[i]), row("K_A", a[i])] for i, d in enumerate(DATES)}
        outs = {repr(score_branch(permuted(base, s), DATES, VOL)) for s in range(12)}
        self.assertEqual(len(outs), 1)
        b1 = score_branch(base, DATES, VOL)[1][0]
        self.assertEqual((b1["points"], b1["value"]["branch"]), (30, "NK_A"))

    def test_b1_full_tie_is_broken_by_branch_key(self):
        a = [100, 100, 100, -1, -1, -1]
        base = {d: [row("K_Z", a[i]), row("K_M", a[i])] for i, d in enumerate(DATES)}
        branches = {score_branch(permuted(base, s), DATES, VOL)[1][0]["value"]["branch"]
                    for s in range(8)}
        self.assertEqual(branches, {"NK_M"})

    def test_reversal_top5_with_ties_is_order_free(self):
        # Six tied buyers yesterday; only one of them reverses today.  Which five
        # make the top 5 used to depend on row order (verifier repro b1.py).
        y = [row(f"K{i}", 50) for i in range(6)]
        t = [row(f"K{i}", 1) for i in range(5)] + [row("K5", -50)]
        outs = set()
        for perm in itertools.permutations(range(6)):
            rows = {DATES[1]: [y[i] for i in perm], DATES[0]: list(reversed(t))}
            outs.add(repr(score_branch(rows, DATES, VOL)))
        self.assertEqual(len(outs), 1)


class DateWindowSourceTests(unittest.TestCase):
    """radar/branch_source.py: same rows as the branch_trades view on both layouts."""

    def _rows(self, db_path, sql_from_conn):
        from sqlalchemy import create_engine, text
        eng = create_engine("sqlite:///" + db_path.as_posix())
        try:
            with eng.connect() as conn:
                return sorted(conn.execute(text(sql_from_conn(conn))).fetchall())
        finally:
            eng.dispose()

    def test_old_and_new_layout_give_the_view_rows(self):
        import tempfile
        from pathlib import Path

        from radar.branch_source import date_window_from, has_date_cover
        from tools import convert_branch_raw_without_rowid as conv
        from tools import make_synthetic_branch_db as synth
        import contextlib, io

        with tempfile.TemporaryDirectory() as tmp:
            old, new = Path(tmp) / "old.db", Path(tmp) / "new.db"
            synth.build(old, stocks=6, days=25, branches=12, warrants_per_stock=1)
            with contextlib.redirect_stdout(io.StringIO()):
                conv.convert(old, new, analyze=True)
            cols = "r.stock_id, r.date, d.branch_key, d.branch_name, r.buy_lots, r.sell_lots, r.net_lots, r.pct"
            where = "WHERE r.date >= '2026-09-15' AND LENGTH(r.stock_id) = 4"
            view = ("SELECT stock_id, date, branch_key, branch_name, buy_lots, sell_lots, net_lots, pct "
                    "FROM branch_trades WHERE date >= '2026-09-15' AND LENGTH(stock_id) = 4")
            results = []
            for db in (old, new):
                from sqlalchemy import create_engine
                eng = create_engine("sqlite:///" + db.as_posix())
                with eng.connect() as conn:
                    results.append(has_date_cover(conn))
                eng.dispose()
                got = self._rows(db, lambda conn: f"SELECT {cols} FROM {date_window_from(conn)} {where}")
                self.assertEqual(got, self._rows(db, lambda conn: view))
                self.assertTrue(got)
                results.append(got)
            self.assertEqual(results[0], False)       # old layout: plain join
            self.assertEqual(results[2], True)        # new layout: INDEXED BY the cover
            self.assertEqual(results[1], results[3])  # identical rows on both layouts


class SameDayMergeTests(unittest.TestCase):
    def test_single_row_is_passed_through_unchanged(self):
        merged = merge_by_date([{"date": "d1", "net": 5, "pct": 1.25}], ("net", "pct"))
        self.assertEqual(merged, {"d1": {"net": 5, "pct": 1.25}})
        self.assertIsInstance(merged["d1"]["net"], int)

    def test_duplicates_are_summed_in_any_order(self):
        rows = [{"date": "d1", "net": 777, "pct": 9.9}, {"date": "d1", "net": -45, "pct": 0.1},
                {"date": "d1", "net": 3, "pct": 1e-17}, {"date": "d0", "net": 1, "pct": None}]
        outs = {repr(merge_by_date(list(p), ("net", "pct"))) for p in itertools.permutations(rows)}
        self.assertEqual(len(outs), 1, outs)
        merged = merge_by_date(rows, ("net", "pct"))
        self.assertEqual(list(merged), ["d0", "d1"])
        self.assertEqual(merged["d1"]["net"], 735)
        self.assertEqual(merged["d1"]["pct"], math.fsum([9.9, 0.1, 1e-17]))
        self.assertIsNone(merged["d0"]["pct"])

    def test_none_only_when_every_row_is_none(self):
        self.assertIsNone(combine([None, None]))
        self.assertEqual(combine([None, 2.5]), 2.5)


if __name__ == "__main__":
    unittest.main()
