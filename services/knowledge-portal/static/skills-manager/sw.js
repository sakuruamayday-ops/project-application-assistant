const CACHE = "jiaotang-skills-manager-pwa-v2";
const STATIC = [
  "/static/skills-manager/app.css",
  "/static/skills-manager/polish.css",
  "/static/skills-manager/app.js",
  "/static/skills-manager/zip-reader.js",
  "/static/skills-manager/platform-capabilities.json",
  "/static/favicon.svg",
];
self.addEventListener("install", (event) => event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(STATIC))));
self.addEventListener("activate", (event) => event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))));
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin) return;
  if (
    url.pathname === "/skills-manager"
    || url.pathname.startsWith("/v1/")
    || url.pathname.includes("/download")
  ) {
    event.respondWith(fetch(event.request));
    return;
  }
  event.respondWith(fetch(event.request).then((response) => {
    const copy = response.clone();
    caches.open(CACHE).then((cache) => cache.put(event.request, copy));
    return response;
  }).catch(() => caches.match(event.request)));
});
