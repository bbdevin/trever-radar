import argparse
import sys
from datetime import datetime, timedelta
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
    errors = [r for r in results if r["status"] == "error"]
    tpex_520_only = (
        datasets == ["quotes"]
        and len(results) == 2
        and len(errors) == 1
        and sum(
            r["source"] == "twse" and r["dataset"] == "quotes" and r["status"] == "ok"
            for r in results
        ) == 1
        and sum(
            r["source"] == "tpex" and r["dataset"] == "quotes"
            and r["status"] == "error" and r.get("error_kind") == "http"
            and r.get("status_code") == 520
            for r in results
        ) == 1
    )
    sys.exit(75 if tpex_520_only else (1 if bad else 0))


def cmd_backfill(args):
    from .importer import backfill
    info = backfill(args.days, args.datasets.split(","))
    print(f"backfill done: {info['trading_days']} trading days present "
          f"({info['imported']} newly imported, {info['probes']} probes)")


def cmd_backfill_margin(args):
    from .importer import backfill_margin
    info = backfill_margin(args.days, args.sleep, args.dry_run, args.min_rows)
    print(
        f"backfill-margin: target={info['days_target']} imported={info['imported']} "
        f"skipped={info['skipped']} errors={info['errors']}"
        + (" (dry-run)" if info["dry_run"] else "")
    )


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


def cmd_import_buybacks(args):
    from .importer import import_buybacks

    as_of = args.as_of
    date_from = (datetime.fromisoformat(as_of).date() - timedelta(days=args.days - 1)).isoformat()
    info = import_buybacks(date_from, as_of)
    print(f"buybacks: {info['rows']} plans ({info['date_from']} to {info['as_of']})")


def cmd_seed_branches(_args):
    from .seed_branches import run
    run()


def cmd_import_branch_trades(args):
    from .importer import import_branch_trades
    ids = args.ids.split(",") if args.ids else None
    import_branch_trades(
        args.date, args.top, ids,
        warrants=args.warrants,
        sleep_s=args.sleep,
        warrant_turnover_min=args.warrant_turnover_min,
    )


def cmd_import_warrant_branch_trades(args):
    from .importer import import_warrant_branch_trades

    info = import_warrant_branch_trades(
        date=args.date,
        market=args.market,
        top=args.top,
        sleep_s=args.sleep,
        max_minutes=args.max_minutes,
        state_file=args.state_file,
        dry_run=args.dry_run,
    )
    if not args.dry_run and not info["complete"]:
        raise SystemExit("warrant branch collection incomplete; state retained for retry")


def cmd_backfill_branches(args):
    from .importer import backfill_branches
    backfill_branches(args.top, args.days, args.sleep, args.max_minutes)


def cmd_backfill_warrant_branches(args):
    from .importer import backfill_warrant_branches
    info = backfill_warrant_branches(
        args.top, args.days, args.sleep, args.max_minutes, args.market,
        state_file=args.state_file,
    )
    if info["stopped"]:
        raise SystemExit(f"warrant branch backfill incomplete: {info['stopped']}")


def cmd_import_tdcc(args):
    from .importer import import_tdcc_shareholding

    info = import_tdcc_shareholding()
    print(
        f"tdcc holders: as_of={info['as_of']} stocks={info['stocks']} rows={info['rows']}"
    )


def cmd_import_directors(args):
    from .importer import import_directors

    info = import_directors(args.ym)
    print(
        f"directors: months={info['months']} stocks={info['stocks']} rows={info['rows']}"
    )


def cmd_backfill_tdcc(args):
    from .importer import backfill_tdcc_from_archive

    info = backfill_tdcc_from_archive(
        date_from=args.date_from,
        date_to=args.date_to,
        sleep_s=args.sleep,
        dry_run=args.dry_run,
        skip_existing=not args.force,
    )
    print(
        f"backfill-tdcc: listed={info['listed']} planned={info['planned']} "
        f"imported={info['imported']} skipped={info['skipped']} "
        f"errors={len(info['errors'])}"
    )
    if info["errors"]:
        for e in info["errors"][:10]:
            print(f"  err: {e}")
        raise SystemExit(1)


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


def cmd_phase2_diff_report(args):
    from .compute.phase2_diff_report import build_phase2_diff_report
    info = build_phase2_diff_report(args.date, args.out)
    print(
        f"phase2-diff {info['date']}: {info['rows']} rows compared, "
        f"tech affected {info['tech_affected']}, final affected {info['final_affected']}, "
        f"watchline crossed {info['crossed_watch']} -> {info['out']}"
    )


def cmd_phase3_strategy_performance_report(args):
    from .compute.strategy_performance import build_phase3_strategy_performance_report

    info = build_phase3_strategy_performance_report(
        date_from=args.date_from,
        lookback_dates=args.lookback_dates,
        recent_events=args.recent_events,
        out=args.out,
    )
    print(
        "phase3-strategy-perf "
        f"out={info['out']} codes={info['codes']} events={info['events']} "
        f"lookback_dates={info['lookback_dates']} recent_events={info['recent_events']}"
    )


def cmd_compute_branch_stats(args):
    from .compute.compute_branch_stats import compute_all
    compute_all()


def cmd_branch_point_in_time_report(args):
    from .compute.branch_point_in_time_report import write_branch_point_in_time_report

    report = write_branch_point_in_time_report(
        as_of=args.as_of,
        date_from=args.date_from,
        date_to=args.date_to,
        out=args.out,
    )
    print(
        "branch-point-in-time-report "
        f"rows={len(report['branch_stock_rows'])} "
        f"episodes={len(report['episode_samples'])} -> {args.out}"
    )


def cmd_branch_point_in_time_series(args):
    from .compute.branch_point_in_time_series import write_branch_point_in_time_series

    report = write_branch_point_in_time_series(
        as_of_from=args.as_of_from,
        as_of_to=args.as_of_to,
        step=args.step,
        window_days=args.window_days,
        out=args.out,
    )
    coverage = report["coverage"]
    print(
        "branch-point-in-time-series "
        f"as_of_dates={coverage['as_of_dates_evaluated']} "
        f"branches={coverage['branch_entity_count']} "
        f"branch_stocks={coverage['branch_stock_entity_count']} "
        f"empty_as_of_dates={len(coverage['as_of_dates_with_no_branch_stock_rows'])} "
        f"-> {args.out}"
    )


def cmd_branch_point_in_time_persist(args):
    from .compute.branch_point_in_time_persist import compute_branch_pit_stats

    info = compute_branch_pit_stats(as_of=args.as_of, window_days=args.window_days)
    print(
        "branch-point-in-time-persist "
        f"as_of={info['as_of']} "
        f"window={info['window_market_days']}d(from={info['window_from']}"
        f"{',truncated' if info['window_truncated'] else ''}) "
        f"branches={info['branches_written']} "
        f"elapsed={info['elapsed_sec']}s"
    )


def cmd_branch_ranking_v2_shadow(args):
    from .compute.branch_ranking_v2_shadow import write_branch_ranking_v2_shadow_report

    report = write_branch_ranking_v2_shadow_report(as_of=args.as_of, out=args.out)
    summary = report["summary"]
    tiers = summary["maturity_tiers"]
    print(
        "branch-ranking-v2-shadow "
        f"branches={summary['branches_evaluated']} v1_ranked={summary['v1_ranked_count']} "
        f"tiers(insufficient/provisional/sufficient)="
        f"{tiers['insufficient']}/{tiers['provisional']}/{tiers['sufficient']} -> {args.out}"
    )
    for key, info in summary["interpretations"].items():
        drift = info["rank_drift"]
        print(
            f"  {key}: listed={info['listed_count']} scored={info['scored_count']} "
            f"left={info['left_count']} entered={info['entered_count']} "
            f"drift(mean_abs)={drift['mean_abs']} survivors={drift['survivors']}"
        )


def cmd_import_geo(_args):
    from .import_geo import import_geo
    import_geo()


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


def cmd_import_descriptions(args):
    from .importer import import_descriptions
    info = import_descriptions(args.limit)
    print(f"descriptions updated: {info['done']}, failed: {info['failed']}")


def cmd_prune(args):
    from .prune import prune_db
    info = prune_db(args.indicators, args.warrants, args.logs, args.vacuum)
    print(f"pruned: {info['indicators']} indicators, {info['warrants']} warrants, {info['logs']} logs")
    if info['vacuum']:
        print("vacuum completed")


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

    bfm = sub.add_parser(
        "backfill-margin",
        help="backfill margin gaps for last N trading days (TWSE+TPEx, docs/34 A4)",
    )
    bfm.add_argument("--days", type=int, default=240)
    bfm.add_argument("--sleep", type=float, default=0.4, help="seconds between days")
    bfm.add_argument("--min-rows", type=int, default=500, help="min rows/day to skip re-import")
    bfm.add_argument("--dry-run", action="store_true", help="list gap days only")
    bfm.set_defaults(fn=cmd_backfill_margin)

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

    sub.add_parser(
        "import-geo",
        help="company + broker-branch addresses for pocket-list geo (docs/27 G1)",
    ).set_defaults(fn=cmd_import_geo)

    th = sub.add_parser("import-themes", help="concept-stock groups (fubon public page)")
    th.add_argument("--limit", type=int, default=None, help="only first N groups (testing)")
    th.set_defaults(fn=cmd_import_themes)

    buybacks = sub.add_parser(
        "import-buybacks",
        help="official MOPS t35sc09 buyback plans (manual only; no scheduler)",
    )
    buybacks.add_argument("--as-of", default=datetime.now(ZoneInfo(config.TZ)).date().isoformat(), help="YYYY-MM-DD")
    buybacks.add_argument("--days", type=int, default=365, help="inclusive lookback, 1..366")
    buybacks.set_defaults(fn=cmd_import_buybacks)

    desc = sub.add_parser("import-descriptions", help="Pull company profiles from Fubon")
    desc.add_argument("--limit", type=int, default=None)
    desc.set_defaults(fn=cmd_import_descriptions)

    sub.add_parser("seed-branches",
                   help="seed manual tracked-branch list (docs/13)"
                   ).set_defaults(fn=cmd_seed_branches)

    bt = sub.add_parser("import-branch-trades",
                        help="scrape top-15 branch buys/sells (MoneyDJ mirrors)")
    bt.add_argument("--date", default=None, help="YYYYMMDD; default latest trading day")
    bt.add_argument("--top", type=int, default=80,
                    help="score-pool size; 0 = all type=stock with quotes that day (no ETF)")
    bt.add_argument("--ids", default=None, help="comma list overrides pool")
    bt.add_argument("--warrants", type=int, default=200,
                    help="legacy bundled warrant pool; 0 disables it (use import-warrant-branch-trades for full market)")
    bt.add_argument("--warrant-turnover-min", type=int, default=None,
                    help="active-stock TWSE call/put pool: same-day turnover >= N (N >= 0); overrides --warrants")
    bt.add_argument("--sleep", type=float, default=1.2, help="overall request interval")
    bt.set_defaults(fn=cmd_import_branch_trades)

    wbt = sub.add_parser(
        "import-warrant-branch-trades",
        help="fetch one day's full eligible TWSE/TPEx warrant branch pool (resumable)",
    )
    wbt.add_argument("--date", default=None, help="YYYYMMDD; default latest warrant_daily date")
    wbt.add_argument("--market", choices=("twse", "tpex", "all"), default="all")
    wbt.add_argument("--top", type=int, default=25_000,
                     help="hard safety cap; excess targets fail closed, never truncate")
    wbt.add_argument("--sleep", type=float, default=1.0, help="overall request interval")
    wbt.add_argument("--max-minutes", type=int, default=None,
                     help="stop incomplete with nonzero exit; state file makes next run resume")
    wbt.add_argument("--state-file", default=None,
                     help="atomic JSON resume file (default data/warrant-branch-state-YYYY-MM-DD.json)")
    wbt.add_argument("--dry-run", action="store_true",
                     help="report exact target counts only; do not fetch or write")
    wbt.set_defaults(fn=cmd_import_warrant_branch_trades)

    bb = sub.add_parser("backfill-branches",
                        help="march-back branch history (resumable, mirror-rotated)")
    bb.add_argument("--top", type=int, default=300, help="stocks by latest turnover")
    bb.add_argument("--days", type=int, default=60, help="trading days depth")
    bb.add_argument("--sleep", type=float, default=1.2)
    bb.add_argument("--max-minutes", type=int, default=None, help="stop cleanly after N minutes")
    bb.set_defaults(fn=cmd_backfill_branches)

    bwb = sub.add_parser("backfill-warrant-branches",
                         help="march-back warrant branch history (resumable)")
    bwb.add_argument("--market", choices=("twse", "tpex", "all"), default="twse")
    bwb.add_argument("--top", type=int, default=200,
                     help="single-market top-N; with --market all, a fail-closed per-day safety cap")
    bwb.add_argument("--days", type=int, default=120, help="trading days depth (half year)")
    bwb.add_argument("--sleep", type=float, default=1.2)
    bwb.add_argument("--max-minutes", type=int, default=None, help="stop cleanly after N minutes")
    bwb.add_argument("--state-file", default=None,
                     help="optional base path; writes one atomic state per date+market beside it")
    bwb.set_defaults(fn=cmd_backfill_warrant_branches)

    tdcc = sub.add_parser(
        "import-tdcc",
        help="TDCC weekly shareholding dispersion (docs/34 B1)",
    )
    tdcc.set_defaults(fn=cmd_import_tdcc)

    idir = sub.add_parser(
        "import-directors",
        help="TWSE/TPEx monthly director holdings (docs/34 §4.6 D1)",
    )
    idir.add_argument(
        "--ym",
        default=None,
        help="YYYY-MM; default = whatever OpenAPI latest month returns",
    )
    idir.set_defaults(fn=cmd_import_directors)

    btdcc = sub.add_parser(
        "backfill-tdcc",
        help="backfill TDCC weeks from wirelessr archive (docs/34; official has no history)",
    )
    btdcc.add_argument(
        "--from",
        dest="date_from",
        default="2026-04-01",
        help="YYYY-MM-DD inclusive (default 2026-04-01; archive ~from 2026-04-30)",
    )
    btdcc.add_argument(
        "--to",
        dest="date_to",
        default=None,
        help="YYYY-MM-DD inclusive (default today)",
    )
    btdcc.add_argument("--sleep", type=float, default=0.4)
    btdcc.add_argument("--dry-run", action="store_true", help="list weeks only")
    btdcc.add_argument(
        "--force",
        action="store_true",
        help="re-import weeks already in DB",
    )
    btdcc.set_defaults(fn=cmd_backfill_tdcc)

    sc = sub.add_parser("compute-scores", help="V1 composite daily scores (docs/04)")
    sc.add_argument("--date", default=None, help="YYYYMMDD; default latest trading day")
    sc.set_defaults(fn=cmd_compute_scores)

    perf = sub.add_parser("compute-performance",
                          help="backfill daily_scores forward returns")
    perf.add_argument("--date", default=None, help="YYYYMMDD; refresh one signal date")
    perf.add_argument("--all", action="store_true", help="refresh every score row")
    perf.set_defaults(fn=cmd_compute_performance)

    p2r = sub.add_parser("phase2-diff-report",
                         help="phase2: compare decoupled scores vs legacy S1-S10 bonus")
    p2r.add_argument("--date", default=None, help="YYYYMMDD; default latest daily_scores date")
    p2r.add_argument("--out", default=None, help="output markdown path")
    p2r.set_defaults(fn=cmd_phase2_diff_report)

    p3 = sub.add_parser(
        "phase3-strategy-performance-report",
        help="phase3: strategy performance report (win_rate/avg/median over 5/10/20d)",
    )
    p3.add_argument(
        "--date-from",
        default=None,
        help="YYYYMMDD or YYYY-MM-DD; default = latest-lookback window",
    )
    p3.add_argument("--lookback-dates", type=int, default=180, help="recent distinct score dates")
    p3.add_argument("--recent-events", type=int, default=50, help="recent matured events for recent20 stats")
    p3.add_argument("--out", default=None, help="output markdown path")
    p3.set_defaults(fn=cmd_phase3_strategy_performance_report)

    bs = sub.add_parser("compute-branch-stats",
                        help="compute stats for tracked branches")
    bs.set_defaults(fn=cmd_compute_branch_stats)

    bpit = sub.add_parser(
        "branch-point-in-time-report",
        help="read-only E2 branch × stock point-in-time shadow JSON report",
    )
    bpit.add_argument("--as-of", required=True, help="YYYY-MM-DD inclusive knowledge cutoff")
    bpit.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD inclusive event start")
    bpit.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD inclusive event end; must be <= as-of")
    bpit.add_argument("--out", required=True, help="JSON output path")
    bpit.set_defaults(fn=cmd_branch_point_in_time_report)

    bpits = sub.add_parser(
        "branch-point-in-time-series",
        help="read-only E2 shadow stability series across many as-of trading days",
    )
    bpits.add_argument("--as-of-from", dest="as_of_from", required=True,
                       help="YYYY-MM-DD first as-of (walk lands on market trading days only)")
    bpits.add_argument("--as-of-to", dest="as_of_to", required=True,
                       help="YYYY-MM-DD last as-of; must be on or after --as-of-from")
    bpits.add_argument("--step", type=int, default=1,
                       help="walk every Nth market trading day in the as-of range (default 1)")
    bpits.add_argument("--window-days", dest="window_days", type=int, default=60,
                       help="trailing window in market trading days ending at each as-of (default 60)")
    bpits.add_argument("--out", required=True, help="JSON output path")
    bpits.set_defaults(fn=cmd_branch_point_in_time_series)

    bpitp = sub.add_parser(
        "branch-point-in-time-persist",
        help="persist one as-of of E2 branch-level point-in-time counts into "
             "branch_pit_stats (counts only, never rates; re-running one as-of "
             "replaces its rows, so a backfill is this command in a loop)",
    )
    bpitp.add_argument("--as-of", required=True,
                       help="YYYY-MM-DD; must be a market trading day")
    bpitp.add_argument("--window-days", dest="window_days", type=int, default=60,
                       help="trailing window in market trading days ending at --as-of "
                            "(default 60); too little history truncates the window and "
                            "is recorded in window_from, never padded")
    bpitp.set_defaults(fn=cmd_branch_point_in_time_persist)

    v2s = sub.add_parser(
        "branch-ranking-v2-shadow",
        help="read-only docs/13 §8 ranking-V2 shadow JSON: V1 vs three readings of "
             "'matured < 10 不評分' (no schema change, no DB write)",
    )
    v2s.add_argument("--as-of", required=True, help="YYYY-MM-DD inclusive knowledge cutoff")
    v2s.add_argument("--out", required=True, help="JSON output path")
    v2s.set_defaults(fn=cmd_branch_ranking_v2_shadow)

    exp = sub.add_parser("export-json", help="write web/public/data/*.json for the frontend")
    exp.add_argument("--out", default=None, help="output dir (default web/public/data)")
    exp.set_defaults(fn=cmd_export_json)

    pr = sub.add_parser("prune", help="delete old history to keep DB slim")
    pr.add_argument("--indicators", type=int, default=400, help="days to keep in indicators_daily")
    pr.add_argument("--warrants", type=int, default=150, help="days to keep in warrant_daily")
    pr.add_argument("--logs", type=int, default=180, help="days to keep in import_logs")
    pr.add_argument("--vacuum", action="store_true", help="run VACUUM after pruning")
    pr.set_defaults(fn=cmd_prune)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
