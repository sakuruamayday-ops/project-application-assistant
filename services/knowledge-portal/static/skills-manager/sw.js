const RETIRED_CACHE_PREFIX = "jiaotang-skills-manager";
self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key.startsWith(RETIRED_CACHE_PREFIX))
          .map((key) => caches.delete(key)),
      ))
      .then(() => self.registration.unregister())
      .then(() => self.clients.claim()),
  );
});
self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request));
});
