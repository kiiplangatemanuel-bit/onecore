const CACHE = "onecore-pos-shell-v1";
self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(["/pos"])));
  self.skipWaiting();
});
self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(key => key.startsWith("onecore-pos-") && key !== CACHE).map(key => caches.delete(key)));
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname === "/pos") {
    event.respondWith((async () => {
      try {
        const response = await fetch(event.request);
        if (response.ok) (await caches.open(CACHE)).put("/pos", response.clone());
        return response;
      } catch {
        return (await caches.match("/pos")) || new Response("POS shell unavailable offline. Reconnect and open POS once.", {status: 503, headers: {"Content-Type": "text/plain"}});
      }
    })());
  }
});
