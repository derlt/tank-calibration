/* calib site cloud — the optional shared copy of a campaign.
 *
 * One source for the browser page and the Node tests.  No DOM.
 *
 * The browser stays the first store: the page saves every entry there, with
 * or without a network.  This client keeps a second copy on the cloud store
 * (worker/index.js) when the user is logged in to a workspace:
 *
 *   login     workspace name + secret keyword -> a token for 30 days
 *   link      the open session <-> one cloud campaign {id, version}
 *   dirty     the browser copy has changes that the cloud does not have
 *   sync      upload the changes; offline -> they wait, and upload later,
 *             also after the session is closed (the outbox)
 *   conflict  someone else saved first; nothing is overwritten, the user
 *             chooses: take the cloud copy, or keep theirs as a new campaign
 *   poll      a clean link asks for a newer version, so a team can follow
 *             one campaign live
 *
 * Storage keys (localStorage):
 *   calib-site:cloud   {base, token, workspace, user, expires, auto}
 *   calib-site:link    the link of the open session (see "the link" below)
 *   calib-site:outbox  [{link, data}]: closed sessions whose changes wait for upload
 */
(function (root) {
  "use strict";

  const AUTH = "calib-site:cloud", LINK = "calib-site:link", OUTBOX = "calib-site:outbox";
  const TIMEOUT = 15000;
  // An upload gets one more second per 4 KB of body: 4 KB/s is 32 kbit/s, a
  // weak site network.  Without it a large campaign could never finish.
  const PER_4KB = 1000;
  // A body this large or more goes gzipped (CompressionStream), when the
  // browser can: a campaign packs to about a fifth.
  const GZIP_FROM = 1024;
  // keepalive (the upload may finish after the page is hidden) allows at
  // most 64 KB of body in flight.
  const KEEPALIVE_MAX = 60000;

  /** text -> gzip bytes, or null when the browser cannot pack. */
  async function gzip(text) {
    if (typeof CompressionStream === "undefined" || typeof Blob === "undefined" || typeof Response === "undefined") return null;
    try {
      const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
      return new Uint8Array(await new Response(stream).arrayBuffer());
    } catch (e) { return null; }
  }

  /** An error with the HTTP status; status 0 = no network. */
  class CloudError extends Error {
    constructor(status, message, body) { super(message); this.status = status; this.body = body || {}; }
    get offline() { return this.status === 0; }
  }

  function newId() {
    const c = typeof crypto !== "undefined" ? crypto : null;
    if (c && c.randomUUID) return c.randomUUID();
    const a = new Uint8Array(16);
    if (c && c.getRandomValues) c.getRandomValues(a);
    else for (let i = 0; i < 16; i++) a[i] = Math.floor(Math.random() * 256);
    return [...a].map((b) => b.toString(16).padStart(2, "0")).join("").replace(/^(.{8})(.{4})(.{4})(.{4})/, "$1-$2-$3-$4-");
  }

  /** "" (this site) or an https address without a trailing slash. */
  function normBase(v) {
    const s = String(v == null ? "" : v).trim().replace(/\/+$/, "");
    if (!s) return "";
    if (!/^https:\/\/[^\s/]+$/i.test(s) && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(s)) {
      throw new CloudError(-1, "The server address must start with https:// and hold no path.");
    }
    return s;
  }

  /**
   * opts.storage  localStorage or a stub with getItem/setItem/removeItem
   * opts.fetch    the fetch function; none -> every call is offline
   * opts.origin   the page's own origin when it is served over http(s)
   * opts.now      a clock, for the tests
   */
  function Client(opts) {
    this.store = opts.storage;
    this.fetchFn = opts.fetch || null;
    this.origin = opts.origin || "";
    this.now = opts.now || (() => Date.now());
    this.onClosed = opts.onClosed || null;
    this.busy = null;
  }

  Client.prototype._get = function (k) { try { return JSON.parse(this.store.getItem(k) || "null"); } catch (e) { return null; } };
  Client.prototype._set = function (k, v) { if (v == null) this.store.removeItem(k); else this.store.setItem(k, JSON.stringify(v)); };

  Client.prototype.auth = function () { return this._get(AUTH) || {}; };
  Client.prototype.loggedIn = function () { const a = this.auth(); return !!(a.token && a.expires > this.now()); };
  Client.prototype.auto = function () { return this.auth().auto !== false; };
  Client.prototype.setAuto = function (on) { this._set(AUTH, Object.assign(this.auth(), { auto: !!on })); };
  /** The server: the saved address, else the page's own site. */
  Client.prototype.base = function () { return this.auth().base || this.origin; };

  /**
   * base != null: a login or signup call, sent without the token.
   * opts.gzip: pack a large body; opts.keepalive: the request may outlive
   * the page (a small body only).
   */
  Client.prototype.request = async function (method, path, body, base, opts) {
    opts = opts || {};
    const b = base != null ? base : this.base();
    if (!b) throw new CloudError(-1, "Enter the server address: this page is a local file.");
    if (!this.fetchFn) throw new CloudError(0, "No network.");
    const headers = { "Content-Type": "application/json" };
    const tok = base == null ? this.auth().token : null;
    if (tok) headers.Authorization = "Bearer " + tok;
    let payload = body == null ? undefined : JSON.stringify(body);
    if (payload && opts.gzip && payload.length >= GZIP_FROM) payload = (await gzip(payload)) || payload;
    const size = payload == null ? 0 : payload.length;
    const ctl = typeof AbortController !== "undefined" ? new AbortController() : null;
    const wait = TIMEOUT + Math.ceil(size / 4096) * PER_4KB;
    const timer = ctl && typeof setTimeout !== "undefined" ? setTimeout(() => ctl.abort(), wait) : null;
    let res;
    try {
      const init = {
        method, headers, body: payload,
        signal: ctl ? ctl.signal : undefined, cache: "no-store", credentials: "omit",
      };
      if (opts.keepalive && size <= KEEPALIVE_MAX) init.keepalive = true;
      res = await this.fetchFn(b + path, init);
    } catch (e) {
      throw new CloudError(0, "No network: the change waits in this browser.");
    } finally { if (timer != null) clearTimeout(timer); }
    let out = {};
    try { out = await res.json(); } catch (e) { out = {}; }
    if (res.status === 401 && tok) {
      // The token is gone or expired: keep the server address and the name.
      const a = this.auth();
      this._set(AUTH, { base: a.base, workspace: a.workspace, user: a.user, auto: a.auto });
    }
    if (!res.ok) throw new CloudError(res.status, out.error || `Server answer ${res.status}.`, out);
    return out;
  };

  Client.prototype._keep = function (base, r) {
    const a = this.auth();
    this._set(AUTH, { base, token: r.token, workspace: r.workspace, user: r.user, expires: r.expires, auto: a.auto });
    return r;
  };
  Client.prototype.login = async function (base, workspace, keyword, user) {
    const b = normBase(base);
    const r = await this.request("POST", "/api/login", { workspace, keyword, user }, b || this.origin);
    return this._keep(b, r);
  };
  Client.prototype.signup = async function (base, workspace, keyword, user, code) {
    const b = normBase(base);
    const r = await this.request("POST", "/api/workspaces", { workspace, keyword, user, signup_code: code }, b || this.origin);
    return this._keep(b, r);
  };
  Client.prototype.logout = async function () {
    const a = this.auth();
    try { if (a.token) await this.request("POST", "/api/logout", {}); } catch (e) { /* offline: forget it here anyway */ }
    this._set(AUTH, { base: a.base, workspace: a.workspace, user: a.user, auto: a.auto });
  };
  Client.prototype.list = function () { return this.request("GET", "/api/campaigns"); };
  Client.prototype.fetchCampaign = function (id, have) {
    return this.request("GET", `/api/campaigns/${encodeURIComponent(id)}${have != null ? "?have=" + have : ""}`);
  };
  Client.prototype.remove = function (id, version) {
    return this.request("DELETE", `/api/campaigns/${encodeURIComponent(id)}?base_version=${version}`);
  };

  // ---------------------------------------------------------------- the link
  //
  // A link joins one copy of a session in this browser to one cloud campaign:
  //   id        the cloud campaign
  //   copy      a tag of this browser copy; a closed copy keeps its tag in
  //             the archive and in the outbox, so the two stay in step
  //   ws, base  the workspace and the server of the campaign
  //   version   the cloud version this copy builds on
  //   rev       local changes so far; synced: the changes the cloud has
  //   sent      uploads whose answer did not come back (lost on the way);
  //             a 409 checks them before it calls a conflict
  //   conflict  someone else saved first: the user chooses
  //   gone      the campaign was deleted in the cloud
  //
  // The open session has one link (LINK).  A closed session with changes
  // that the cloud does not have waits in the outbox (OUTBOX) with its data,
  // and uploads at the next sync.

  const GONE = "This campaign was deleted from the cloud. It stays in this browser.";
  const STOP = { offline: 1, login: 1 };

  /** A short signature of a text: an upload is recognised by it after a lost answer. */
  function sig(text) {
    let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
    for (let i = 0; i < text.length; i++) {
      const c = text.charCodeAt(i);
      h1 = Math.imul(h1 ^ c, 2654435761); h2 = Math.imul(h2 ^ c, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return text.length.toString(36) + ":" + (h2 >>> 0).toString(36) + (h1 >>> 0).toString(36);
  }

  Client.prototype.link = function () { return this._get(LINK); };
  Client.prototype.setLink = function (l) { this._set(LINK, l); };
  Client.prototype.unlink = function () { this._set(LINK, null); };
  Client.prototype.outbox = function () { const o = this._get(OUTBOX); return Array.isArray(o) ? o : []; };

  /** The workspace and server of the login (kept after a logout). */
  Client.prototype.where = function () { return { ws: this.auth().workspace || "", base: this.base() }; };
  /** The link belongs to the workspace of this login. */
  Client.prototype.here = function (l) {
    if (!l) return false;
    if (l.ws == null) return true;
    const w = this.where();
    return l.ws === w.ws && (l.base || "") === w.base;
  };
  /** "none" | "elsewhere" | "gone" | "conflict" | "dirty" | "clean" */
  Client.prototype.state = function (l) {
    if (l === undefined) l = this.link();
    if (!l) return "none";
    if (!this.here(l)) return "elsewhere";
    if (l.gone) return "gone";
    if (l.conflict) return "conflict";
    return l.rev > l.synced ? "dirty" : "clean";
  };
  Client.prototype.dirty = function () { const l = this.link(); return !!l && l.rev > l.synced; };
  /** Closed copies that wait for upload to this workspace. */
  Client.prototype.waiting = function () { return this.outbox().filter((e) => this.here(e.link)); };

  Client.prototype._make = function (o) {
    const w = this.where();
    const l = Object.assign({ copy: newId(), ws: w.ws, base: w.base, rev: 0, synced: 0 }, o);
    this._set(LINK, l);
    return l;
  };
  /** Link the open session to a new cloud campaign; the next sync uploads it. */
  Client.prototype.linkNew = function () { return this._make({ id: newId(), version: 0, rev: 1 }); };
  /** Link to a campaign just read from the cloud: clean. */
  Client.prototype.linkTo = function (c) { return this._make({ id: c.id, version: c.version, by: c.updated_by, at: c.updated_at }); };
  /** The page saved the session: the cloud copy is behind by one more change. */
  Client.prototype.markDirty = function () {
    const l = this.link();
    if (!l) return;
    l.rev += 1;
    this._set(LINK, l);
  };

  /**
   * The open session closes (archive, new campaign, another one opens).
   * Its changes that the cloud does not have go to the outbox with data,
   * the session JSON at this moment.  -> the link, for the archive entry.
   */
  Client.prototype.detach = function (data) {
    const l = this.link();
    if (!l) return null;
    this._set(LINK, null);
    if (l.rev > l.synced && !l.conflict && !l.gone && data) {
      const box = this.outbox().filter((e) => e.link.copy !== l.copy);
      box.push({ link: l, data });
      this._set(OUTBOX, box);
    }
    return l;
  };
  /**
   * A closed copy opens again, with the link of its archive entry.  When its
   * changes still wait in the outbox, they leave the outbox: the open link
   * uploads them.  The reopened copy gets a new tag, so older archive
   * entries of the same campaign never take its state.
   */
  Client.prototype.attach = function (l) {
    const box = this.outbox(), e = l.copy ? box.find((x) => x.link.copy === l.copy) : null;
    if (e) this._set(OUTBOX, box.filter((x) => x !== e));
    return this._make(Object.assign({}, e ? e.link : l, { copy: newId() }));
  };

  /** Change the link with this tag, open or in the outbox.  -> the link, or null when it is gone. */
  Client.prototype._update = function (copy, fn) {
    const l = this.link();
    if (l && l.copy === copy) { fn(l); this._set(LINK, l); return l; }
    const box = this.outbox(), e = box.find((x) => x.link.copy === copy);
    if (!e) return null;
    fn(e.link);
    this._set(OUTBOX, box);
    return e.link;
  };
  Client.prototype._find = function (copy) {
    const l = this.link();
    if (l && l.copy === copy) return l;
    const e = this.outbox().find((x) => x.link.copy === copy);
    return e ? e.link : null;
  };

  /** One PUT.  -> {state: "saved" | "recovered" | "conflict" | "gone" | "offline" | "login" | "error", message} */
  Client.prototype._upload = async function (l, data, keepalive) {
    const try1 = { rev: l.rev, sig: sig(JSON.stringify(data)) };
    const base = l.version;
    // Keep the try before the request: when the answer is lost, the next
    // 409 finds it.
    this._update(l.copy, (x) => { x.sent = (x.sent || []).concat([try1]).slice(-5); });
    try {
      const r = await this.request("PUT", `/api/campaigns/${encodeURIComponent(l.id)}`, { data, base_version: base }, null,
        { gzip: true, keepalive });
      this._update(l.copy, (x) => {
        x.version = r.version; x.synced = Math.max(x.synced, try1.rev); x.by = r.updated_by; x.at = r.updated_at;
        delete x.sent;
      });
      return { state: "saved" };
    } catch (e) {
      if (e.status === 409) return this._conflict(l.copy, l.id, base, e);
      if (e.status === 0) return { state: "offline", message: e.message };
      if (e.status === 401) return { state: "login", message: e.message };
      return { state: "error", status: e.status, message: e.message };
    }
  };
  /** A 409: our own save whose answer was lost, a deleted campaign, or a real conflict. */
  Client.prototype._conflict = async function (copy, id, base, e) {
    const cur = e.body.current || null;
    const l = this._find(copy);
    if (cur && cur.deleted_at == null && cur.version === base + 1 && l && l.sent && l.sent.length) {
      let c = null;
      try { c = await this.fetchCampaign(id); } catch (x) { c = null; }
      const s = c && c.version === base + 1 ? sig(JSON.stringify(c.data)) : null;
      const hit = s && l.sent.find((t) => t.sig === s);
      if (hit) {
        this._update(copy, (x) => {
          x.version = c.version; x.synced = Math.max(x.synced, hit.rev); x.by = c.updated_by; x.at = c.updated_at;
          delete x.sent;
        });
        return { state: "recovered" };
      }
    }
    if (!cur || cur.deleted_at != null) {
      this._update(copy, (x) => { x.gone = true; delete x.sent; });
      return { state: "gone", message: GONE };
    }
    this._update(copy, (x) => { x.conflict = cur; delete x.sent; });
    return { state: "conflict", message: e.message };
  };
  /** Upload one copy until the cloud has it: after a lost answer, once more with the right version. */
  Client.prototype._push = async function (copy, getData, keepalive) {
    for (let i = 0; i < 3; i++) {
      const l = this._find(copy);
      if (!l) return { state: "moved" };   // the copy was closed or opened again meanwhile
      if (l.rev <= l.synced) return { state: "saved" };
      const data = getData();
      if (data == null) return { state: "idle" };
      const r = await this._upload(l, data, keepalive);
      if (r.state !== "recovered") return r;
    }
    return { state: "error", message: "The upload did not settle. Try again." };
  };

  /**
   * Upload what waits: first the closed copies in the outbox, then the open
   * session.  getData() returns the open session JSON at the moment of the
   * upload.  One sync at a time; a change made while one runs is sent by the
   * next.  opts.onClosed({state, link, data, message}) hears the end of each
   * closed copy: saved, conflict, gone or error.
   *
   * -> {state: "idle" | "saved" | "pending" | "offline" | "conflict" | "gone"
   *            | "elsewhere" | "login" | "error", message}
   */
  Client.prototype.sync = function (getData, opts) {
    if (this.busy) return this.busy.then(() => this.sync(getData, opts));
    this.busy = this._sync(getData, (opts && opts.keepalive) || false).finally(() => { this.busy = null; });
    return this.busy;
  };
  Client.prototype._sync = async function (getData, keepalive) {
    const box = this.waiting();
    const open = this.state();
    if (!box.length && open !== "dirty") {
      if (open === "conflict") return { state: "conflict", message: "Someone else saved this campaign first." };
      if (open === "gone") return { state: "gone", message: GONE };
      if (open === "elsewhere") return { state: "elsewhere" };
      return { state: "idle" };
    }
    if (!this.loggedIn()) return { state: "login", message: "Log in to upload the changes." };
    for (const e of box) {
      const r = await this._push(e.link.copy, () => e.data);
      if (STOP[r.state] || (r.state === "error" && r.status === 429)) return r;
      if (r.state === "idle" || r.state === "moved") continue;
      const link = this._find(e.link.copy) || e.link;
      this._set(OUTBOX, this.outbox().filter((x) => x.link.copy !== e.link.copy));
      if (this.onClosed) this.onClosed({ state: r.state, link, data: e.data, message: r.message });
    }
    const l = this.link();
    if (!l || this.state(l) !== "dirty") {
      const st = this.state(l);
      return { state: st === "conflict" || st === "gone" ? st : "saved", message: st === "gone" ? GONE : undefined };
    }
    const r = await this._push(l.copy, getData, keepalive);
    if (r.state === "moved") return { state: "idle" };
    if (r.state !== "saved") return r;
    const cur = this.link();
    return { state: cur && cur.copy === l.copy && cur.rev > cur.synced ? "pending" : "saved" };
  };

  /**
   * Ask for a newer cloud version of a clean link.  apply(campaign) puts it
   * in the page; when apply throws, the link stays as it was.
   * -> null (nothing new, offline, or local changes wait) | {gone: true} | the campaign {id, version, data, …}
   */
  Client.prototype.poll = async function (apply) {
    const l = this.link();
    if (!l || this.state(l) !== "clean" || l.version < 1 || !this.loggedIn() || this.busy) return null;
    let r;
    try { r = await this.fetchCampaign(l.id, l.version); } catch (e) {
      if (e.status === 404 && this._update(l.copy, (x) => { x.gone = true; })) return { gone: true };
      return null;
    }
    if (r.same || !r.data || r.version <= l.version) return null;
    const cur = this.link();
    if (!cur || cur.copy !== l.copy || this.state(cur) !== "clean") return null;   // the user typed meanwhile
    if (apply) apply(r);
    this._update(l.copy, (x) => { x.version = r.version; x.by = r.updated_by; x.at = r.updated_at; });
    return r;
  };

  /**
   * Conflict, choice 1: the cloud copy replaces the browser copy.
   * apply(campaign) puts it in the page (and archives the browser copy,
   * with its conflicted link); then the session links to the cloud copy.
   */
  Client.prototype.takeCloud = async function (apply) {
    const l = this.link();
    if (!l) throw new CloudError(-1, "No campaign is open.");
    let r;
    try { r = await this.fetchCampaign(l.id); } catch (e) {
      if (e.status === 404) { this._update(l.copy, (x) => { x.gone = true; delete x.conflict; }); throw new CloudError(404, GONE); }
      throw e;
    }
    const cur = this.link();
    if (!cur || cur.copy !== l.copy) throw new CloudError(-1, "The open campaign changed. Try again.");
    if (apply) apply(r, cur);
    this.linkTo(r);
    return r;
  };
  /** Conflict, choice 2 (also for a deleted campaign or another workspace): the browser copy becomes a new cloud campaign. */
  Client.prototype.fork = function () { return this.linkNew(); };

  const api = { Client, CloudError, newId, normBase, sig, gzip, AUTH, LINK, OUTBOX };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CalibCloud = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
