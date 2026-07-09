// Reliable external cron for GitHub Actions.
//
// GitHub's native `schedule:` trigger can be delayed by hours when Actions
// is under load (observed: daily-market delayed ~3h44m, daily-insti ~3h06m,
// daily-branches ~2h40m on 2026-07-09). Cloudflare Workers Cron Triggers
// fire on time, so this worker calls `workflow_dispatch` at the same wall
// clock times the yaml `schedule:` blocks used to target.
//
// Cloudflare Workers Free plan caps Cron Triggers at 3/Worker and 5/account
// (https://developers.cloudflare.com/workers/configuration/cron-triggers/)
// — not enough for our 6 fire times. So wrangler.toml declares exactly ONE
// trigger ("*/10 * * * *", every 10 minutes) and this file matches the
// current UTC time against SCHEDULE below to decide which workflow (if any)
// to dispatch. All target times are on :00/:10/:40 marks, so a 10-minute
// tick never skips one.

const REPO_OWNER = "bbdevin";
const REPO_NAME = "trever-radar";

const WEEKDAY_UTC = [1, 2, 3, 4, 5]; // Mon-Fri, Date.getUTCDay() convention

// hm is UTC "HH:MM". Comment shows the Taipei (UTC+8) wall clock time these
// used to run at natively; see .github/workflows/*.yml for what each does.
const SCHEDULE = [
  { hm: "06:10", days: WEEKDAY_UTC, workflow: "daily-market.yml" },   // 14:10 Taipei
  { hm: "08:10", days: WEEKDAY_UTC, workflow: "daily-insti.yml" },    // 16:10 Taipei
  { hm: "09:40", days: WEEKDAY_UTC, workflow: "daily-branches.yml" }, // 17:40 Taipei
  { hm: "13:00", days: WEEKDAY_UTC, workflow: "daily-branches.yml" }, // 21:00 Taipei
  { hm: "14:10", days: WEEKDAY_UTC, workflow: "daily-margin.yml" },   // 22:10 Taipei
  { hm: "17:10", days: null, workflow: "data-backfill.yml" },         // 01:10 Taipei (next day), every day
];

function matchesNow(entry, now) {
  const hh = String(now.getUTCHours()).padStart(2, "0");
  const mm = String(now.getUTCMinutes()).padStart(2, "0");
  if (`${hh}:${mm}` !== entry.hm) return false;
  if (entry.days && !entry.days.includes(now.getUTCDay())) return false;
  return true;
}

export default {
  async scheduled(event, env, ctx) {
    const now = new Date(event.scheduledTime);
    const matches = SCHEDULE.filter((e) => matchesNow(e, now));
    if (matches.length === 0) {
      return; // most ticks are a no-op; only ~6/day actually dispatch
    }
    for (const m of matches) {
      ctx.waitUntil(dispatchWorkflow(m.workflow, env));
    }
  },

  // Manual smoke test: GET /?workflow=<workflow file name>&token=<SMOKE_TEST_TOKEN>
  // Auth required — this endpoint is public internet, unlike `scheduled()`
  // which Cloudflare invokes internally and is never network-reachable.
  async fetch(request, env) {
    const url = new URL(request.url);
    const token = url.searchParams.get("token");
    if (!env.SMOKE_TEST_TOKEN || token !== env.SMOKE_TEST_TOKEN) {
      return new Response("unauthorized", { status: 401 });
    }
    const workflow = url.searchParams.get("workflow");
    const known = [...new Set(SCHEDULE.map((e) => e.workflow))];
    if (!workflow || !known.includes(workflow)) {
      return new Response(`Usage: /?workflow=<workflow>&token=...\nKnown: ${known.join(", ")}`, {
        status: 400,
      });
    }
    const res = await dispatchWorkflow(workflow, env);
    return new Response(`dispatched ${workflow}: ${res.status}`, {
      status: res.ok ? 200 : 502,
    });
  },
};

async function dispatchWorkflow(workflowFile, env) {
  const res = await fetch(
    `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${workflowFile}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "trever-radar-scheduler-worker",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main" }),
    }
  );
  if (!res.ok) {
    console.error(`dispatch failed for ${workflowFile}: ${res.status} ${await res.text()}`);
  } else {
    console.log(`dispatched ${workflowFile} OK`);
  }
  return res;
}
