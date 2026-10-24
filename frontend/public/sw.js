/* Офлайн для «За столом»: страница /play и её скрипты кэшируются, чтобы счётчики работали без интернета.
   API не кэшируется (кроме картинок карт «Берсерка» для набора отряда). */
const CACHE = "dragon-play-v1";
const PAGES = ["/play"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(PAGES)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

const cacheFirst = async (req) => {
  const hit = await caches.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) (await caches.open(CACHE)).put(req, res.clone());
  return res;
};

const networkFirst = async (req, key) => {
  try {
    const res = await fetch(req);
    if (res.ok) (await caches.open(CACHE)).put(key, res.clone());
    return res;
  } catch (err) {
    const hit = await caches.match(key);
    if (hit) return hit;
    throw err;
  }
};

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/api/img/bk/")) {
    e.respondWith(cacheFirst(req));
  } else if (req.mode === "navigate" && url.pathname === "/play") {
    e.respondWith(networkFirst(req, "/play"));
  } else if (req.mode === "navigate") {
    // без интернета любая страница приложения открывает «За столом»
    e.respondWith(fetch(req).catch(() => caches.match("/play").then((hit) => hit || Response.error())));
  }
});
