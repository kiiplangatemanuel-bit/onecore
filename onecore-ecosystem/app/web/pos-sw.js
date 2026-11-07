const CACHE = "onecore-pos-shell-v2";
const DB = "onecore-pos-v1";
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
function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB, 1);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
function getRecord(db, store, id) {
  return new Promise((resolve, reject) => {
    const request = db.transaction(store, "readonly").objectStore(store).get(id);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
function getAll(db, store) {
  return new Promise((resolve, reject) => {
    const request = db.transaction(store, "readonly").objectStore(store).getAll();
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error);
  });
}
function removeQueueItem(db, id) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction("queue", "readwrite");
    tx.objectStore("queue").delete(id);
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
}
async function decrypt(record, key) {
  const plain = await crypto.subtle.decrypt({name: "AES-GCM", iv: new Uint8Array(record.iv)}, key, new Uint8Array(record.cipher));
  return JSON.parse(new TextDecoder().decode(plain));
}
async function notifyClients(message) {
  const clients = await self.clients.matchAll({type: "window", includeUncontrolled: true});
  for (const client of clients) client.postMessage(message);
}
async function syncOfflineQueue() {
  const db = await openDb();
  try {
    const keyRecord = await getRecord(db, "keys", "aes");
    const sessionRecord = await getRecord(db, "cache", "session");
    if (!keyRecord || !keyRecord.value || !sessionRecord) return;
    const session = await decrypt(sessionRecord, keyRecord.value);
    if (!session.token || !session.org || !session.branch || !session.expires_at || session.expires_at <= Date.now()) return;
    const items = await getAll(db, "queue");
    for (const item of items) {
      const sale = await decrypt(item, keyRecord.value);
      const headers = {"Authorization": "Bearer " + session.token, "X-Organization-ID": String(session.org), "Content-Type": "application/json"};
      if (session.deviceToken) headers["X-POS-Device-Token"] = session.deviceToken;
      let response;
      try {
        response = await fetch("/api/v1/pos/sync", {method: "POST", headers, body: JSON.stringify(sale)});
      } catch (error) {
        throw error;
      }
      if (response.status === 401 || response.status === 403) {
        await notifyClients({type: "pos-sync-auth-required", transaction_id: item.id});
        return;
      }
      if (response.status === 409 || response.status === 404 || response.status === 422) {
        await notifyClients({type: "pos-sync-conflict", transaction_id: item.id, status: response.status});
        continue; // Keep the encrypted item for supervisor review; never auto-discard or replay it.
      }
      if (!response.ok) throw new Error("POS background sync failed: " + response.status);
      const result = await response.json();
      await removeQueueItem(db, item.id);
      await notifyClients({type: "pos-sync-complete", transaction_id: item.id, sale_id: result.id,
        payment_follow_up: (sale.payments || []).some(payment => payment.method === "mpesa")});
    }
  } finally {
    db.close();
  }
}
self.addEventListener("sync", event => {
  if (event.tag === "onecore-pos-sync") event.waitUntil(syncOfflineQueue());
});
