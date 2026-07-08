import argparse
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from . import config
from .db import get_engine, init_db


def _today() -> str:
    return datetime.now(ZoneInfo(config.TZ)).strftime("%Y%m%d")


def cmd_init_db(_args):
    init_db()
    print(f"db ready: {config.DB_URL}")


def cmd_import_daily(args):
    from .importer import import_daily
    datasets = args.datasets.split(",") if args.datasets else None
    results = import_daily(args.date, datasets)
    bad = False
    for r in results:
        line = f"{r['source']:>4} {r['dataset']:<7} {r['status']:<6} rows={r['rows']}"
        if r["status"] == "error":
            bad = True
            line += f"  {r.get('error', '')[:120]}"
        print(line)
    sys.exit(1 if bad else 0)


def cmd_backfill(args):
    from .importer import backfill
    info = backfill(args.days, args.datasets.split(","))
    print(f"backfill done: {info['trading_days']} trading days present "
          f"({info['imported']} newly imported, {info['probes']} probes)")


def cmd_deep_backfill(args):
    from .importer import deep_backfill
    ids = args.ids.split(",") if args.ids else None
    info = deep_backfill(ids=ids, top=args.top, all_stocks=args.all, sleep_s=args.sleep)
    print(f"deep-backfill: {info['done']} fetched, {info['skipped']} already deep, "
          f"{info['failed']} failed")


def cmd_import_warrant_master(_args):
    from .importer import import_warrant_master
    info = import_warrant_master()
    print(f"warrant master: {info['total']} rows "
          f"(twse matched {info['twse_matched']}, unmatched {info['twse_unmatched']})")


def cmd_aggregate_warrants(args):
    from .importer import aggregate_warrants
    n = aggregate_warrants(args.date)
    print(f"warrant_stock_daily rows written: {n}")


def cmd_compute_adjustments(args):
    from .adjustments import compute_adjustments
    ids = args.ids.split(",") if args.ids else None
    info = compute_adjustments(ids=ids, top=args.top, all_stocks=args.all,
                               start_date=args.start_date, sleep_s=args.sleep)
    print(f"adjustments: {info['done']} stocks, {info['events']} events, "
          f"{info['rows']} rows updated, {info['failed']} failed")


def cmd_compute_indicators(args):
    from .compute.indicators import compute_indicators
    ids = args.ids.split(",") if args.ids else None
    compute_indicators(ids=ids, top=args.top, all_stocks=args.all, days=args.days)


def cmd_import_themes(args):
    from .importer import import_themes
    import_themes(args.limit)


def cmd_seed_branches(_args):
    from .seed_branches import run
    run()


def cmd_import_branch_trades(args):
    from .importer import import_branch_trades
    ids = args.ids.split(",") if args.ids else None
    import_branch_trades(args.date, args.top, ids)


def cmd_compute_scores(args):
    from .compute.scores import compute_scores
    info = compute_scores(args.date)
    print(f"scores {info['date']}: {info['scored']} scored, "
          f"{info['watchlist']} reach watchlist threshold (>=65)")


def cmd_compute_performance(args):
    from .compute.performance import compute_performance
    info = compute_performance(args.date, args.all)
    print(f"performance {info['date']}: {info['updated']}/{info['candidates']} rows updated, "
          f"{info['complete_20d']} have 20d returns")


def cmd_compute_branch_stats(args):
    from .compute.compute_branch_stats import compute_all
    compute_all()


def cmd_import_stock_info(_args):
    from .importer import import_stock_info
    print(f"industry filled for {import_stock_info()} stocks")


def cmd_export_json(args):
    from .export.json_export import export_json
    info = export_json(args.out)
    print(f"exported {info['stocks']} stocks for {info['date']} -> {info['out']}")


def cmd_status(_args):
    init_db()
    with get_engine().connect() as conn:
        rows = conn.execute(text(
            "SELECT run_at, source, dataset, date, rows, status, COALESCE(error,'') "
            "FROM import_logs ORDER BY id DESC LIMIT 20")).fetchall()
        if not rows:
            print("no imports yet")
            return
        for r in rows:
            print(f"{r[0]}  {r[1]:>4} {r[2]:<7} {r[3]}  rows={r[4]:<6} {r[5]:<6} {r[6][:60]}")
        counts = conn.execute(text(
            "SELECT 'stocks', COUNT(*) FROM stocks "
            "UNION ALL SELECT 'warrants', COUNT(*) FROM warrants "
            "UNION ALL SELECT 'daily_prices', COUNT(*) FROM daily_prices "
            "UNION ALL SELECT 'warrant_daily', COUNT(*) FROM warrant_daily "
            "UNION ALL SELECT 'daily_institutional', COUNT(*) FROM daily_institutional "
            "UNION ALL SELECT 'daily_margins', COUNT(*) FROM daily_margins")).fetchall()
        print("-" * 40)
        for name, n in counts:
            print(f"{name:<22} {n}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="radar", description="Trever Radar data pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="create tables").set_defaults(fn=cmd_init_db)

    imp = sub.add_parser("import-daily", help="import one trading day (quotes/insti/margin)")
    imp.add_argument("--date", default=_today(), help="YYYYMMDD, default today (Asia/Taipei)")
    imp.add_argument("--datasets", default=None, help="comma list: quotes,insti,margin")
    imp.set_defaults(fn=cmd_import_daily)

    sub.add_parser("status", help="recent import logs + table counts").set_defaults(fn=cmd_status)

    bf = sub.add_parser("backfill", help="import last N trading days of history")
    bf.add_argument("--days", type=int, default=240)
    bf.add_argument("--datasets", default="quotes", help="comma list, default quotes")
    bf.set_defaults(fn=cmd_backfill)

    dp = sub.add_parser("deep-backfill", help="since-IPO history via FinMind (1 request/stock)")
    dp.add_argument("--ids", default=None, help="comma list, e.g. 2330,2317")
    dp.add_argument("--top", type=int, default=None, help="top N by latest-day turnover")
    dp.add_argument("--all", action="store_true", help="all stocks/ETFs (needs free token for quota)")
    dp.add_argument("--sleep", type=float, default=7.0, help="seconds between requests")
    dp.set_defaults(fn=cmd_deep_backfill)

    sub.add_parser("import-warrant-master",
                   help="warrant master: underlying/strike/maturity (TWSE+TPEx OpenAPI)"
                   ).set_defaults(fn=cmd_import_warrant_master)

    ag = sub.add_parser("aggregate-warrants", help="rebuild warrant_stock_daily")
    ag.add_argument("--date", default=None, help="YYYYMMDD; omit = rebuild all dates")
    ag.set_defaults(fn=cmd_aggregate_warrants)

    adj = sub.add_parser("compute-adjustments",
                         help="compute daily_prices.adj_factor from dividend results")
    adj.add_argument("--ids", default=None, help="comma list, e.g. 2330,2317")
    adj.add_argument("--top", type=int, default=None, help="top N by latest-day turnover")
    adj.add_argument("--all", action="store_true", help="all stocks/ETFs with daily_prices")
    adj.add_argument("--start-date", default="1990-01-01", help="YYYY-MM-DD")
    adj.add_argument("--sleep", type=float, default=1.0, help="seconds between FinMind requests")
    adj.set_defaults(fn=cmd_compute_adjustments)

    ind = sub.add_parser("compute-indicators",
                         help="compute indicators_daily from adjusted daily_prices")
    ind.add_argument("--ids", default=None, help="comma list, e.g. 2330,2317")
    ind.add_argument("--top", type=int, default=None, help="top N by latest-day turnover")
    ind.add_argument("--all", action="store_true", help="all stocks/ETFs with daily_prices")
    ind.add_argument("--days", type=int, default=None,
                     help="incremental: only recompute/write the last N dates (nightly use 5)")
    ind.set_defaults(fn=cmd_compute_indicators)

    sub.add_parser("import-stock-info",
                   help="fill stocks.industry via FinMind (one request)"
                   ).set_defaults(fn=cmd_import_stock_info)

    th = sub.add_parser("import-themes", help="concept-stock groups (fubon public page)")
    th.add_argument("--limit", type=int, default=None, help="only first N groups (testing)")
    th.set_defaults(fn=cmd_import_themes)

    sub.add_parser("seed-branches",
                   help="seed manual tracked-branch list (docs/13)"
                   ).set_defaults(fn=cmd_seed_branches)

    bt = sub.add_parser("import-branch-trades",
                        help="scrape top-15 branch buys/sells (fubon public page)")
    bt.add_argument("--date", default=None, help="YYYYMMDD; default latest trading day")
    bt.add_argument("--top", type=int, default=80, help="pool size by composite score")
    bt.add_argument("--ids", default=None, help="comma list overrides pool")
    bt.set_defaults(fn=cmd_import_branch_trades)

    sc = sub.add_parser("compute-scores", help="V1 composite daily scores (docs/04)")
    sc.add_argument("--date", default=None, help="YYYYMMDD; default latest trading day")
    sc.set_defaults(fn=cmd_compute_scores)

    perf = sub.add_parser("compute-performance",
                          help="backfill daily_scores forward returns")
    perf.add_argument("--date", default=None, help="YYYYMMDD; refresh one signal date")
    perf.add_argument("--all", action="store_true", help="refresh every score row")
    perf.set_defaults(fn=cmd_compute_performance)

    bs = sub.add_parser("compute-branch-stats",
                        help="compute stats for tracked branches")
    bs.set_defaults(fn=cmd_compute_branch_stats)

    exp = sub.add_parser("export-json", help="write web/public/data/*.json for the frontend")
    exp.add_argument("--out", default=None, help="output dir (default web/public/data)")
    exp.set_defaults(fn=cmd_export_json)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
