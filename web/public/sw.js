/* Trever Radar app-shell service worker.
 *
 * Cache: HTML navigations (network-first) + same-origin static assets.
 * NEVER cache /data/* — market signals must not be shown stale as "latest".
 * NEVER cache Supabase / auth — login JWT architecture stays untouched.
 */
const VERSION = "trever-radar-shell-v1";

function shouldBypass(url) {
  if (url.pathname.startsWith("/data/") || url.pathname === "/data") return true;
  if (url.hostname.includes("supabase.co")) return true;
  if (url.pathname.startsWith("/auth")) return true;
  return false;
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(VERSION).then((cache) =>
      cache.addAll(["/", "/icons/trever-radar-mark.svg", "/icons/icon-192.png", "/icons/icon-512.png"]),
    ),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  let url;
  try {
    url = new URL(req.url);
  } catch {
    return;
  }

  if (url.origin !== self.location.origin || shouldBypass(url)) return;

  if (req.mode === "navigate") {
    event.respondWith(networkFirst(req));
    return;
  }

  event.respondWith(cacheFirst(req));
});

async function networkFirst(req) {
  try {
    const res = await fetch(req);
    if (res && res.ok) {
      const copy = res.clone();
      const cache = await caches.open(VERSION);
      await cache.put(req, copy);
    }
    return res;
  } catch {
    const cached = await caches.match(req);
    if (cached) return cached;
    const home = await caches.match("/");
    if (home) return home;
    return new Response("離線且尚未快取此頁。請連上網路後再開啟。", {
      status: 503,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
}

async function cacheFirst(req) {
  const cached = await caches.match(req);
  if (cached) return cached;
  try {
    const res = await fetch(req);
    if (res && res.ok) {
      const copy = res.clone();
      const cache = await caches.open(VERSION);
      await cache.put(req, copy);
    }
    return res;
  } catch {
    return cached || Response.error();
  }
}
