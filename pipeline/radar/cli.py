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


def _warn_unverified_markets(info, cmd: str) -> None:
    """A market the gap check could not evaluate must not read as a clean bill.

    The reference needs `_MIN_MARKET_SAMPLES` dates carrying rows, and the
    sample count is starved by exactly the thing being looked for: the longer
    and more total an outage, the fewer dates have rows. Below the floor the
    market is exempted, so the worst outages produce the least output. Saying
    so on the last line keeps an operator from reading silence as health.
    """
    for market in info.get("unverified_markets", []):
        n = info.get("samples", {}).get(market, 0)
        print(f"{cmd}: WARNING {market} was NOT checked for gaps — only {n} "
              f"date(s) in the window carry any rows, too few to establish "
              f"what normal looks like. Re-run with a larger --days if this "
              f"market should have data.")


def cmd_backfill(args):
    from .importer import backfill
    info = backfill(args.days, args.datasets.split(","))
    still = info.get("still_incomplete") or []
    print(f"backfill done: {info['trading_days']} trading days present "
          f"({info['imported']} newly imported, {info['probes']} probes, "
          f"{len(info.get('attempted') or [])} market-gaps attempted, "
          f"{len(still)} still incomplete)")
    _warn_unverified_markets(info, "backfill")
    if still:
        # 非零,因為「試過了」不等於「補好了」。importer._run 的 docstring 明講
        # "never raise":每一次抓取失敗都變成 import_logs 裡的一列然後正常返回,
        # 所以在本次改動之前,25 個日期全部失敗也會 exit 0 並印出「repaired」。
        # 任何把後續步驟鏈在這個離開碼上的流程(repair-window.sh 就是)會鏈在一個
        # 不存在的閘門上。現在退出碼講的是結果,不是「跑完了」。
        print(f"backfill: {len(still)} (date, market) still below the completeness "
              f"floor after re-importing — the gap was NOT closed", file=sys.stderr)
        raise SystemExit(1)


def cmd_backfill_margin(args):
    from .importer import backfill_margin
    info = backfill_margin(args.days, args.sleep, args.dry_run, args.min_rows)
    print(
        f"backfill-margin: target={info['days_target']} imported={info['imported']} "
        f"skipped={info['skipped']} errors={info['errors']} "
        f"market-gaps={len(info['repaired'])}"
        + (" (dry-run)" if info["dry_run"] else "")
    )
    _warn_unverified_markets(info, "backfill-margin")


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


# 分點當日匯入的離開碼。沿用本檔的紀律:離開碼講的是**結果**。
#
#   0  日期合格、沒有標的失敗、而且這一輪真的抓到東西了。
#   75 日期合格,但有個別標的兩次都失敗(import_logs status='incomplete')。
#      資料可以上線,只是這一天少了幾檔。
#   76 這一輪一檔都沒抓到(done == 0 而目標清單非空)——來源在這一輪是死的。
#      但**日期仍然可能合格**:同一天 17:40 跑過一輪了。所以這個碼的意思是
#      「叫醒人,但不要扣住資料」,它蓋過 0 與 75,永遠不蓋過 1。
#   1  日期不合格(status='error'):覆蓋率掉出帶狀範圍,這一天不可以上線。
#
# 注意 `incomplete` 這個字在本檔出現兩次而來源不同:這裡指「單輪內的個別標的
# 失敗但仍在帶內」,`_WARRANT_RESUMABLE_STOPS` 指的是權證爬蟲可續跑的分塊停點。
# 共用詞彙、各自推導,不要把分點匯入接到那個 tuple 上。
BRANCH_IMPORT_INCOMPLETE_EXIT = 75
BRANCH_FEED_DEAD_EXIT = 76


def cmd_import_branch_trades(args):
    from .importer import import_branch_trades
    ids = args.ids.split(",") if args.ids else None
    info = import_branch_trades(
        args.date, args.top, ids,
        warrants=args.warrants,
        sleep_s=args.sleep,
        warrant_turnover_min=args.warrant_turnover_min,
    )
    if not info["fit"]:
        print(f"import-branch-trades: {info['status']}", file=sys.stderr)
        raise SystemExit(1)
    if info["dead_feed"]:
        print("import-branch-trades: this round fetched nothing from the feed; "
              "the date itself is still fit to publish", file=sys.stderr)
        raise SystemExit(BRANCH_FEED_DEAD_EXIT)
    if info["failed"]:
        print(f"import-branch-trades: {info['failed']} stock(s) failed twice; "
              "the date is still fit to publish", file=sys.stderr)
        raise SystemExit(BRANCH_IMPORT_INCOMPLETE_EXIT)


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


# 「還沒跑完,下次接著跑」與「真的壞了」必須用不同離開碼分開。
#
# 這兩件事先前共用 exit 1,於是任何驅動腳本只能去比對 `stopped` 的字面訊息——
# 把 shell 綁在一個 Python f-string 上,改一個字就靜默壞掉,而且壞的方向是把
# 失敗當成正常。75 沿用本檔 `cmd_import_daily` 已經在用的慣例(TPEx 520 那種
# 預期內的不完整),`daily-insti.sh` 也是靠它判斷。
#
# 對既有呼叫者無影響:`bf-supervisor.sh` 以 `|| true` 忽略離開碼,
# `manual-catchup.sh` 與 `vps_mega_finalize.sh` 都只看「非零就停」。
WARRANT_BACKFILL_INCOMPLETE_EXIT = 75

# 可續跑的停止理由(對照 `_backfill_warrant_branches_with_state` 寫進 `stopped`
# 的三種字串)。剩下那個 "too many failures at ..." 是真失敗,不列在這裡。
_WARRANT_RESUMABLE_STOPS = ("time budget reached", "resume required")


def cmd_backfill_warrant_branches(args):
    from .importer import backfill_warrant_branches
    info = backfill_warrant_branches(
        args.top, args.days, args.sleep, args.max_minutes, args.market,
        state_file=args.state_file, min_age_days=args.min_age_days,
    )
    stopped = info["stopped"]
    if not stopped:
        return
    print(f"warrant branch backfill incomplete: {stopped}", file=sys.stderr)
    resumable = stopped.startswith(_WARRANT_RESUMABLE_STOPS)
    raise SystemExit(WARRANT_BACKFILL_INCOMPLETE_EXIT if resumable else 1)


# 個股期貨當日匯入的離開碼。沿用本檔既有的紀律:離開碼講的是**結果**,
# 不是「指令跑完了」(`cmd_import_daily` 的 75 是預期內的不完整,`cmd_backfill`
# 的 1 是「補過了但沒補好」)。
#
#   0  對照表refresh 成功,而且當天的一般與盤後兩個時段都寫進去了 = 這一天完整。
#   75 抓到也寫進去了,但 payload 只有一般時段。盤後掛在**同一個日期**上、
#      約次日清晨才公布,所以下午跑的排程看到的一天本來就只有一半。這是預期內的
#      不完整,不是失敗:重跑一次就補齊。與 `cmd_import_daily` 的 TPEx 520 同義,
#      `daily-insti.sh` 之類的驅動腳本也是靠 75 判斷「等一下再來」。
#   1  其他一切:抓取或解析失敗,或 '+F' join 對不到任何契約(importer 會丟例外)。
#      join 壞掉時安靜寫 0 列比失敗更糟,所以那條路也走 1。
#
# 刻意**沒有**「今天這個日期我已經有了 → 特別的碼」這一格:這個端點只供應最新一天,
# 假日重跑本來就會拿到同一天,而重寫同一天是冪等的,那不是一個需要通報的結果。
FUTURES_AFTER_HOURS_PENDING_EXIT = 75


def cmd_import_futures(_args):
    from .importer import import_futures

    info = import_futures()
    print(
        f"futures {info['date']}: contracts={info['contracts']} "
        f"rows={info['stock_futures_rows']} (of {info['feed_rows']} feed rows; "
        f"{info['leftover_codes']} non-stock contract codes ignored) "
        f"sessions={'一般' if info['has_regular'] else '-'}"
        f"/{'盤後' if info['has_after_hours'] else '-'}"
    )
    if not info["has_after_hours"]:
        print(
            "import-futures: the after-hours session for this date has not been "
            "published yet — re-run after it closes to complete the date",
            file=sys.stderr,
        )
        raise SystemExit(FUTURES_AFTER_HOURS_PENDING_EXIT)


def cmd_backfill_futures(args):
    from .importer import backfill_futures

    info = backfill_futures(args.days, args.sleep, args.dry_run)
    print(
        f"backfill-futures: range={info['date_from']}..{info['date_to']} "
        f"market_days={info['market_days']} chunks={info['chunks_planned']} "
        f"dates_covered={info['dates_written']} rows={info['rows_written']} "
        f"still_missing={len(info['still_missing'])} errors={len(info['errors'])}"
        + (" (dry-run)" if info["dry_run"] else "")
    )
    for e in info["errors"][:10]:
        print(f"  err: {e}", file=sys.stderr)
    if info["dry_run"]:
        return
    if info["still_missing"]:
        # 同 `cmd_backfill`:「試過了」不等於「補好了」。每個失敗的月份都只是
        # 一行 stderr 然後繼續,所以沒有這一關的話 12 個月全掛也會 exit 0。
        print(
            f"backfill-futures: {len(info['still_missing'])} market day(s) in the "
            f"window still have no futures_daily rows (first: "
            f"{info['still_missing'][0]}) — the gap was NOT closed",
            file=sys.stderr,
        )
        raise SystemExit(1)


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
    from .compute.branch_point_in_time_persist import (
        compute_branch_pit_stats,
        resolve_default_as_of,
    )

    as_of = args.as_of or resolve_default_as_of()
    info = compute_branch_pit_stats(as_of=as_of, window_days=args.window_days)
    print(
        "branch-point-in-time-persist "
        f"as_of={info['as_of']} "
        f"window={info['window_market_days']}d(from={info['window_from']}"
        f"{',truncated' if info['window_truncated'] else ''}) "
        f"branches={info['branches_written']} "
        f"elapsed={info['elapsed_sec']}s"
    )


def cmd_branch_stock_pctile_counts(args):
    from .compute.branch_stock_pctile_counts import (
        compute_branch_stock_pctile_counts,
        resolve_default_as_of,
    )

    as_of = args.as_of or resolve_default_as_of()
    info = compute_branch_stock_pctile_counts(as_of=as_of, window_days=args.window_days)
    print(
        "branch-stock-pctile-counts "
        f"as_of={info['as_of']} "
        f"window={info['window_market_days']}d(from={info['window_from']}"
        f"{',truncated' if info['window_truncated'] else ''}) "
        f"pairs={info['pairs_written']} stocks={info['stocks_written']} "
        f"elapsed={info['elapsed_sec']}s"
    )


def cmd_branch_window_direction_battery(args):
    from .compute.branch_window_direction_battery import (
        write_branch_window_direction_battery,
    )

    report = write_branch_window_direction_battery(
        as_of=args.as_of, window_days=args.window_days, seed=args.seed,
        flag_min_known=args.flag_min_known, out=args.out,
    )
    split = report["split"]
    print(
        "branch-window-direction-battery "
        f"as_of={report['metadata']['as_of']} "
        f"window={split['window_market_days']}d"
        f"{'(truncated)' if split['window_truncated'] else ''} "
        f"formation={split['formation_from']}..{split['formation_to']}"
        f"({split['formation_market_days']}d) "
        f"evaluation={split['evaluation_from']}..{split['evaluation_to']}"
        f"({split['evaluation_market_days']}d) -> {args.out}"
    )
    for direction, info in report["directions"].items():
        survivorship = info["survivorship"]
        unlagged, lag = info["evaluation"]["unlagged"], info["evaluation"]["lag"]
        placebo = info["placebo"]["unlagged"]
        print(
            f"  {direction}: flagged_pairs={info['formation']['flagged_pairs']} "
            f"stocks={info['formation']['flagged_stocks']} "
            f"activity={survivorship['with_evaluation_activity']} "
            f"survivors={survivorship['survivors']} "
            f"exceeds_both={unlagged['exceeds_own_stock_both']}/{unlagged['compared_pairs']} "
            f"obs_exp={unlagged['obs_exp']} lag_obs_exp={lag['obs_exp']} "
            f"placebo_obs_exp={placebo['obs_exp']} "
            f"re_flag={info['re_flag']['re_flagged_on_evaluation_half']}"
            f"/{info['re_flag']['formation_flagged_pairs']} (not a criterion)"
        )
    for verdict in report["verdicts"]:
        print(f"  {verdict['line']}")
    # 覆核觸發與判決分開印，前綴也不同：它們不能下架任何東西。
    for trigger in report["review_triggers"]:
        print(f"  {trigger['line']}")


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
    # 不是保守,是正確性:富邦頁解析出零列一律是 NoDataError,分不出「當天真的沒有
    # 分點成交」與「鏡像還沒發布這一天」,而後者會被記成永不重試的 empty。
    # 預設值與 `importer.WARRANT_BRANCH_MIN_AGE_DAYS` 相同(此處寫字面量是為了
    # 維持本檔「importer 一律延後到指令函式裡才 import」的慣例);
    # test_warrant_branch_import.py 會斷言兩者一致,不會漂移。
    bwb.add_argument("--min-age-days", type=int, default=1,
                     help="skip dates newer than N calendar days "
                          "(the mirror may not have published them yet)")
    bwb.set_defaults(fn=cmd_backfill_warrant_branches)

    sub.add_parser(
        "import-futures",
        help="TAIFEX single-stock futures: latest day's market report + the "
             "contract→stock mapping, refreshed in the same run (the feed has no "
             "usable date parameter, so 'latest' is all it can be asked for)",
    ).set_defaults(fn=cmd_import_futures)

    bff = sub.add_parser(
        "backfill-futures",
        help="backfill single-stock futures history via the Big5 CSV endpoint, "
             "chunked by calendar month (one request covers ~a month); resumable "
             "and polite",
    )
    bff.add_argument("--days", type=int, default=250,
                     help="market trading days of depth, taken from daily_prices")
    bff.add_argument("--sleep", type=float, default=1.2, help="seconds between requests")
    bff.add_argument("--dry-run", action="store_true", help="list the month chunks only")
    bff.set_defaults(fn=cmd_backfill_futures)

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
    bpitp.add_argument("--as-of", default=None,
                       help="YYYY-MM-DD; must be a market trading day. "
                            "Omitted: the latest trading day that has price data "
                            "(MAX(date) FROM daily_prices); fails loudly if there is none")
    bpitp.add_argument("--window-days", dest="window_days", type=int, default=60,
                       help="trailing window in market trading days ending at --as-of "
                            "(default 60); too little history truncates the window and "
                            "is recorded in window_from, never padded")
    bpitp.set_defaults(fn=cmd_branch_point_in_time_persist)

    bspc = sub.add_parser(
        "branch-stock-pctile-counts",
        # 2026-09-08:原文寫「the measured re-flag rate across years is only a few
        # percent」,把 re-flag 當成「這個性質不持久」的證據。那是誤讀,而且是
        # 本專案反覆引用過的那一個:re-flag 量的是**嚴格旗標**(每側 ≥10 次已知
        # 且兩側 ≥70%)重新達標的比率,分子分母都綁著活動量——評估半段交易少一
        # 點的分點,無論行為如何都再現不了。真正回答「紀錄有沒有帶到未來」的是
        # 存活 pair 的 exceeds-both 57.4%,對上約 22–24% 的機率值(2026-09-08 方
        # 向 battery,obs/exp 2.40 對安慰劑 0.91)。所以正確的因果是:群體傾向
        # 會延續 → 值得呈現計數;個別身分不會重現 → 不下旗標、不排名。
        help="replace the latest branch × stock snapshot of buy/sell price-percentile "
             "counts (counts and denominators only; no rates, no flags, no ranking — "
             "the tendency holds up out of sample at the group level, but a given "
             "branch re-earns the strict label about 2% of the time, so this table "
             "names no branch as anything)",
    )
    bspc.add_argument("--as-of", default=None,
                      help="YYYY-MM-DD; must be a market trading day. "
                           "Omitted: the latest trading day that has price data "
                           "(MAX(date) FROM daily_prices); fails loudly if there is none")
    bspc.add_argument("--window-days", dest="window_days", type=int, default=490,
                      help="trailing window in market trading days ending at --as-of "
                           "(default 490); too little history truncates the window and "
                           "is recorded in window_from, never padded")
    bspc.set_defaults(fn=cmd_branch_stock_pctile_counts)

    bwdb = sub.add_parser(
        "branch-window-direction-battery",
        help="read-only time-split out-of-sample battery deciding whether the shipped "
             "per-stock buy-low/sell-high panel stays up and whether the forward "
             "percentile may ever be added (flow-matched placebo + lag test + the "
             "pre-registered withdrawal verdicts; writes nothing to the database)",
    )
    bwdb.add_argument("--as-of", dest="as_of", required=True,
                      help="YYYY-MM-DD inclusive knowledge cutoff; the window is the "
                           "market trading days at or before it")
    bwdb.add_argument("--window-days", dest="window_days", type=int, default=490,
                      help="window in market trading days ending at --as-of (default 490); "
                           "it is halved by trading day into formation and evaluation. "
                           "Too little history truncates the window and is reported, "
                           "never padded")
    bwdb.add_argument("--seed", type=int, default=20260904,
                      help="seed for the flow-matched placebo draw (default 20260904); "
                           "the same seed and database reproduce the same placebo set")
    bwdb.add_argument("--flag-min-known", dest="flag_min_known", type=int, default=10,
                      help="known percentile episodes required per side in the formation "
                           "half to flag a pair (default 10, the protocol value the "
                           "battery was validated at). The shipped panel displays pairs "
                           "at >= 5 per side, a band with no out-of-sample reading; this "
                           "flag exists so 5, 8 and 10 can be read side by side. Any "
                           "value other than the default is instrumentation, not a "
                           "validated result")
    bwdb.add_argument("--out", required=True, help="JSON output path")
    bwdb.set_defaults(fn=cmd_branch_window_direction_battery)

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
