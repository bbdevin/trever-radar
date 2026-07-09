# trever-radar-scheduler

External cron for the 6 data workflows, using a Cloudflare Worker instead of
GitHub's native `schedule:` (observed delayed 2.5–3.5h under Actions load on
2026-07-09: `daily-market` ~3h44m late, `daily-insti` ~3h06m, `daily-branches`
~2h40m — confirmed via `gh run list`).

## Status: deployed and confirmed working (2026-07-09)

- Live at `https://trever-radar-scheduler.a7033140327k.workers.dev`.
- Uses **one** Cloudflare Cron Trigger (`*/10 * * * *`, fires every 10
  minutes) — not one trigger per workflow. Cloudflare Workers Free plan caps
  Cron Triggers at 3/Worker and 5/account
  ([docs](https://developers.cloudflare.com/workers/configuration/cron-triggers/)),
  which isn't enough for our 6 fire times. `worker.js`'s `SCHEDULE` table
  matches the current UTC time on each tick and dispatches the matching
  GitHub workflow (if any) via `workflow_dispatch`. Add/change fire times by
  editing `SCHEDULE` and redeploying — no Cloudflare trigger-count limit to
  worry about.
- `GH_TOKEN` secret (fine-grained GitHub PAT, `Actions: Read and write` on
  this repo only) is set and verified working — confirmed a real
  `workflow_dispatch` run landed via `gh run list`.
- `SMOKE_TEST_TOKEN` secret is set. **fetch() requires it** (`?token=...`);
  unauthenticated requests get `401`. This was a real gap: the Worker's
  public URL had no auth at first, so anyone who found the URL could have
  triggered any of the 6 workflows and burned through the private repo's
  2,000 min/month Actions budget. Fixed same day, before anything else
  changed.
- `.github/workflows/daily-margin.yml`: new, lightweight, margin-only
  catch-up round at 22:10 Taipei (70 min after the existing 21:00
  `daily-branches` round). `daily-branches.yml`'s own margin fetches at
  17:40/21:00 are untouched — this is a pure addition, not a replacement,
  in case TWSE `MI_MARGN` publishes later than 21:00.
- `.github/workflows/{daily-market,daily-insti,daily-branches,data-backfill}.yml`:
  `schedule:` blocks removed. Only `workflow_dispatch:` remains as a
  trigger. `data-backfill.yml`'s Saturday-only full-recompute step and both
  weekly-backup steps were updated to key off `inputs.task` / day-of-week
  instead of `github.event_name == 'schedule'` (that event no longer exists
  once `schedule:` is gone). Backup steps also had their old
  `|| event_name == 'workflow_dispatch'` clause removed, so backups stay
  Friday-only (`daily-branches`) / Saturday-only (`data-backfill`) exactly
  like before — a manual test dispatch no longer forces an extra backup
  upload, which was overwriting the weekly known-good snapshot.

**⚠️ These yaml changes are local, not yet committed/pushed to `main`.**
Right now the 4 modified workflows + `daily-margin.yml` have no trigger at
all until this is pushed — the Worker is proven working, so this is the
last step. Ask to proceed when ready (push triggers `deploy.yml`, normal).

## If you want to run a manual smoke test yourself later

I generated `SMOKE_TEST_TOKEN` randomly during setup and never printed it
(set directly via a piped command, not visible in any transcript). If you
want to smoke-test manually in the future, set your own value first:

```
cd cloudflare-trigger
wrangler secret put SMOKE_TEST_TOKEN
```

Then:

```
curl "https://trever-radar-scheduler.a7033140327k.workers.dev/?workflow=daily-market.yml&token=<your token>"
```

Known `workflow` values: `daily-market.yml`, `daily-insti.yml`,
`daily-branches.yml`, `daily-margin.yml`, `data-backfill.yml`. Check
`gh run list --workflow <name> --limit 2` afterward to confirm it landed as
a fresh `workflow_dispatch` run.

## Ongoing / known risks

- **No fallback trigger.** If the Worker or `GH_TOKEN` ever breaks silently
  (e.g. PAT expires), the site simply stops auto-updating with no alert —
  check `radar.json`'s `freshness` field on the live site, or `gh run list`,
  if the site looks stale. Worth an occasional glance for the first few
  weeks.
- **`GH_TOKEN` rotation**: this PAT is a live, actively-used credential
  (called ~6x/day going forward) — don't just revoke it. Rotate by creating
  a new PAT, `wrangler secret put GH_TOKEN` with the new value, confirm a
  smoke test still works, *then* revoke the old one.
- Cloudflare Workers Cron Triggers + the 144 no-op ticks/day this design
  adds are free-tier, no cost.
