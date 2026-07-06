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

    exp = sub.add_parser("export-json", help="write web/public/data/*.json for the frontend")
    exp.add_argument("--out", default=None, help="output dir (default web/public/data)")
    exp.set_defaults(fn=cmd_export_json)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
