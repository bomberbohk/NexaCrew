/* NexaCrew Station PWA service worker.
   Strategy: NETWORK-FIRST for everything (so app updates apply instantly),
   falling back to the cache when offline. Static assets and the app shell
   are cached opportunistically after each successful fetch. */
const CACHE = "nexacrew-station-v1";

self.addEventListener("install", (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c =>
    c.addAll(["/", "/static/style.css", "/static/i18n.js", "/static/app.js",
              "/static/nexacrew_logo.png", "/static/manifest.webmanifest"]).catch(() => { })));
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/")) return;   // API is always live
  e.respondWith((async () => {
    try {
      const res = await fetch(e.request);
      if (res && res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy)).catch(() => { });
      }
      return res;
    } catch {
      const hit = await caches.match(e.request, { ignoreSearch: url.pathname === "/" });
      if (hit) return hit;
      throw new Error("offline");
    }
  })());
});
