/* The offline copy of the hosted page (a service worker).
 *
 * The page is one file, and the browser loads it again more often than it
 * seems: a return from the Shortcuts timer, a reload, a phone that dropped
 * the tab.  At a tank the network can be weak or absent, and the load fails
 * there although the session waits in the browser.  This worker keeps the
 * last page it got and gives it when the network does not answer.
 *
 *   - Only the page itself: a GET that loads a page (a navigation) on this
 *     site.  /api/* and every other request go to the network as before.
 *   - Network first: a new deploy reaches the phone at the next load.  The
 *     network gets WAIT_MS; past that, or when it fails, the kept copy
 *     answers, and a late answer from the network still updates the copy
 *     for the next load.
 *   - One copy, under "/": a load with a query (the return from Shortcuts
 *     has none, a shared link may) gives the same page.
 *   - Only a good answer is kept: status 200, from this site, not a redirect.
 *
 * The page registers this file only on https (the hosted page); the one
 * file on a phone (calib_site.html) has no worker.
 */
"use strict";
const CACHE = "calib-page-v1";
const PAGE = "/";
const WAIT_MS = 3000;

self.addEventListener("install", (ev) => {
  ev.waitUntil(
    caches.open(CACHE)
      .then((c) => fetch(new Request(PAGE, { cache: "reload" })).then((r) => (good(r) ? c.put(PAGE, r) : null)))
      .catch(() => null)   // no network now: the first page load fills the copy
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (ev) => {
  ev.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("calib-page-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

/** A page answer worth keeping. */
function good(r) {
  return !!r && r.status === 200 && !r.redirected && (r.type === "basic" || r.type === "default");
}

/** The request this worker answers: a page load on this site, not the API. */
function isPage(req) {
  if (req.method !== "GET" || req.mode !== "navigate") return false;
  const url = new URL(req.url);
  return url.origin === self.location.origin && !url.pathname.startsWith("/api/");
}

self.addEventListener("fetch", (ev) => {
  const req = ev.request;
  if (!isPage(req)) return;
  const net = fetch(req).then((r) => {
    if (good(r)) {
      const copy = r.clone();
      ev.waitUntil(caches.open(CACHE).then((c) => c.put(PAGE, copy)).catch(() => null));
    }
    return r;
  });
  ev.waitUntil(net.catch(() => null));   // a late answer still updates the copy
  const kept = () => caches.open(CACHE).then((c) => c.match(PAGE));
  ev.respondWith(new Promise((resolve) => {
    let done = false;
    const give = (r) => { if (!done && r) { done = true; resolve(r); } };
    const fallback = () => kept().then((r) => {
      if (r) give(r);
      else net.then(give, () => give(Response.error()));   // nothing kept: wait for the network
    }, () => net.then(give, () => give(Response.error())));
    const timer = setTimeout(fallback, WAIT_MS);
    net.then((r) => { clearTimeout(timer); give(r); }, () => { clearTimeout(timer); fallback(); });
  }));
});
