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
 *   timer     the fill timer that runs now, shared by the team's devices
 *             apart from the campaign data (last change wins, no merge)
 *
 * Storage keys (localStorage):
 *   calib-site:cloud   {base, token, workspace, user, expires, auto}
 *   calib-site:link    the link of the open session (see "the link" below)
 *   calib-site:outbox  [{link, data}]: closed sessions whose changes wait for upload
 */
(function (root) {
  "use strict";

  const AUTH = "calib-site:cloud", LINK = "calib-site:link", OUTBOX = "calib-site:outbox", MERGES = "calib-site:merges";
  const MERGES_KEEP = 20;
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
   * opts.rebase   the page's merge (page.html, rebase()): replays this
   *               device's actions on the cloud copy at a 409.  Without it,
   *               every 409 is a conflict (an older page, the tests).
   * opts.mergeOn  false: no merge, today's conflict choice (the page's
   *               kill switch in Files → Cloud)
   */
  function Client(opts) {
    this.store = opts.storage;
    this.fetchFn = opts.fetch || null;
    this.origin = opts.origin || "";
    this.now = opts.now || (() => Date.now());
    this.onClosed = opts.onClosed || null;
    this.rebase = opts.rebase || null;
    this.mergeOn = opts.mergeOn || null;
    this.busy = null;
  }

  Client.prototype._get = function (k) { try { return JSON.parse(this.store.getItem(k) || "null"); } catch (e) { return null; } };
  Client.prototype._set = function (k, v) { if (v == null) this.store.removeItem(k); else this.store.setItem(k, JSON.stringify(v)); };

  Client.prototype.auth = function () { return this._get(AUTH) || {}; };
  Client.prototype.loggedIn = function () { const a = this.auth(); return !!(a.token && a.expires > this.now()); };
  Client.prototype.auto = function () { return this.auth().auto !== false; };
  Client.prototype.setAuto = function (on) { this._set(AUTH, Object.assign(this.auth(), { auto: !!on })); };
  /** Merge two writers of one campaign (Files → Cloud, on by default); off: today's conflict choice. */
  Client.prototype.merge = function () { return this.auth().merge !== false; };
  Client.prototype.setMerge = function (on) { this._set(AUTH, Object.assign(this.auth(), { merge: !!on })); };
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
  //   ops, noReplay, baseSig
  //             this device's actions since `version`, for the merge (see
  //             "the action list" above)
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

  // ------------------------------------------------------- the action list
  //
  // Two people can write into one campaign: one counts the cans, the other
  // dips.  When the second save gets a conflict (409), the page replays this
  // device's own actions on the cloud copy (page.html, rebase()), instead of
  // asking the user to choose.  For that the link keeps:
  //   ops       this device's actions since `version`: [{k, a, t, at, after, rev}]
  //             k the Session method, a its arguments, t the time, at what
  //             the action stood on, after the session's signature just
  //             after it, rev the local change it made
  //   noReplay  {rev, why}: a change that is not in ops (a settings form, an
  //             undo); the list cannot explain the copy until the cloud has it
  //   baseSig   the fingerprint of the cloud copy at `version` (see
  //             fingerprint()): the replay finds what the other person changed
  // No base copy is kept: a fingerprint is about 20 bytes per row.

  /** At most this many actions; more, and the list is not replayable until the next upload. */
  const OPS_MAX = 500;

  /** JSON text with sorted keys: two copies of one session compare equal. */
  function canon(v) {
    if (v === null || typeof v !== "object") { const s = JSON.stringify(v); return s === undefined ? "null" : s; }
    if (Array.isArray(v)) return "[" + v.map((x) => (x === undefined || typeof x === "function" ? "null" : canon(x))).join(",") + "]";
    return "{" + Object.keys(v).filter((k) => v[k] !== undefined && typeof v[k] !== "function").sort()
      .map((k) => JSON.stringify(k) + ":" + canon(v[k])).join(",") + "}";
  }
  /**
   * A session without the per-device fields of a transfer: `active` is the
   * tank view of this device, `lastDip` the tank it dipped last (undo order).
   */
  function shared(data) {
    if (!data || data.kind !== "transfer" || (!("active" in data) && !("lastDip" in data))) return data;
    const o = Object.assign({}, data);
    delete o.active;
    delete o.lastDip;
    return o;
  }
  /** The signature of a whole session, without the per-device fields. */
  function sessionSig(data) { return sig(canon(shared(data))); }
  /** The parts of one tank's session: one signature per row, the tally, the settings, the finish, the rest. */
  function tankPrint(d) {
    const rest = Object.assign({}, d);
    for (const k of ["levels", "batch", "config", "finished"]) delete rest[k];
    return {
      rows: (d.levels || []).map((l) => sig(canon(l))),
      batch: sig(canon(d.batch == null ? null : d.batch)),
      config: sig(canon(d.config == null ? null : d.config)),
      finished: sig(canon(d.finished == null ? null : d.finished)),
      rest: sig(canon(rest)),
    };
  }
  /**
   * The fingerprint of a cloud copy: per part, a signature.  A transfer has
   * one per tank.  all: the whole session (sessionSig).
   */
  function fingerprint(data) {
    if (!data || typeof data !== "object") return null;
    const all = sessionSig(data);
    if (data.kind === "transfer") {
      const rest = shared(data), r = Object.assign({}, rest);
      delete r.out; delete r.in;
      return { kind: "transfer", out: tankPrint(data.out || {}), in: tankPrint(data.in || {}), rest: sig(canon(r)), all };
    }
    return Object.assign(tankPrint(data), { all });
  }
  /** The link takes a new cloud version: its fingerprint, and the actions the cloud now has leave the list. */
  function moveBase(x, data, rev) {
    x.baseSig = fingerprint(data);
    if (rev == null) { delete x.ops; delete x.noReplay; return; }
    if (x.ops) x.ops = x.ops.filter((o) => o.rev > rev);
    if (x.ops && !x.ops.length) delete x.ops;
    if (x.noReplay && x.noReplay.rev <= rev) delete x.noReplay;
  }

  /**
   * The last merges and refusals on this device, newest first:
   * {when, version, by, n (actions), ok, why}.  A refusal keeps its reason
   * ("same", "target", "lost"...): the log shows which rule refuses most on
   * site, so a rule can be relaxed later, with a test.
   */
  Client.prototype.merges = function () { const m = this._get(MERGES); return Array.isArray(m) ? m : []; };
  Client.prototype._mergelog = function (e) {
    this._set(MERGES, [Object.assign({ when: this.now() }, e)].concat(this.merges()).slice(0, MERGES_KEEP));
  };

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
  Client.prototype.linkTo = function (c) {
    return this._make({ id: c.id, version: c.version, by: c.updated_by, at: c.updated_at, baseSig: fingerprint(c.data) });
  };
  /**
   * The page saved the session: the cloud copy is behind by one more change.
   *   op          the action that made the change ({k, a, t, at, after}):
   *               it joins the action list
   *   {cancel: k} the change takes back the last action, of kind k, when it
   *               was the last change (an untap right after its tap): both
   *               leave the list; else as a reason
   *   a text      the reason why the change has no action (a settings form,
   *               an undo): the list is not replayable until the cloud has it
   *   nothing     the same, with the reason "edit"
   * One write: the change and its action never part.
   */
  Client.prototype.markDirty = function (op) {
    const l = this.link();
    if (!l) return;
    const ops = l.ops || [];
    l.rev += 1;
    const last = ops[ops.length - 1];
    if (op && typeof op === "object" && op.cancel) {
      if (last && last.k === op.cancel && last.rev === l.rev - 1) {
        // The copy is again what the list explained before the action.  (When
        // the upload of the action itself lands later, the next replay finds
        // the copy unexplained, and refuses.)
        ops.pop();
        if (ops.length) l.ops = ops; else delete l.ops;
      } else l.noReplay = { rev: l.rev, why: "un" + op.cancel };
    } else if (op && typeof op === "object") {
      l.ops = ops.concat([Object.assign({}, op, { rev: l.rev })]);
      if (l.ops.length > OPS_MAX) l.noReplay = { rev: l.rev, why: "long" };
    } else l.noReplay = { rev: l.rev, why: typeof op === "string" && op ? op : "edit" };
    // A change that is not replayable makes the earlier actions useless: they
    // leave the list at the next upload anyway.
    if (l.noReplay && l.noReplay.rev === l.rev) delete l.ops;
    this._set(LINK, l);
  };
  /** The link's action list as the replay needs it, or {why} when it cannot explain the copy. */
  Client.prototype.actions = function (l) {
    if (l === undefined) l = this.link();
    if (!l) return { why: "none" };
    if (l.noReplay) return { why: l.noReplay.why };
    if (!l.baseSig) return { why: "base" };
    return { ops: l.ops || [], baseSig: l.baseSig };
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
        moveBase(x, data, try1.rev);
      });
      return { state: "saved" };
    } catch (e) {
      if (e.status === 409) return this._conflict(l.copy, l.id, base, e, data, try1.rev);
      if (e.status === 0) {
        // The answer was lost, so the server may have taken it: the try is
        // marked, and a later 409 does not replay our actions over it.
        this._update(l.copy, (x) => {
          const t = (x.sent || []).find((y) => y.rev === try1.rev && y.sig === try1.sig);
          if (t) t.lost = true;
        });
        return { state: "offline", message: e.message };
      }
      if (e.status === 401) return { state: "login", message: e.message };
      return { state: "error", status: e.status, message: e.message };
    }
  };
  /**
   * A 409 on the open session: the page replays this device's actions on the
   * cloud copy (opts.rebase) and the result uploads.  -> {merged} to upload
   * the merged copy, {wait: why} to try again at the next tick, or
   * {why} when the merge is refused (the user then gets the conflict).
   */
  Client.prototype._merge = async function (copy, l, base, cur, data, rev) {
    if (!this.rebase || (this.mergeOn && !this.mergeOn())) return { why: "off" };
    const no = (why) => { this._mergelog({ version: cur.version, by: cur.updated_by, n: (this.actions(l).ops || []).length, ok: false, why }); return { why }; };
    // Only the open session: a closed copy keeps the conflict choice.
    const open = this.link();
    if (!open || open.copy !== copy) return no("closed");
    const a = this.actions(l);
    if (a.why) return no(a.why);
    const c = await this.fetchCampaign(l.id);
    if (!c || !c.data) return no("none");
    const refuse = (why) => {
      this._mergelog({ version: c.version, by: c.updated_by, n: a.ops.length, ok: false, why });
      return { why };
    };
    // An upload whose answer was lost may have landed, and the cloud may
    // already hold its actions: a replay would add them twice.  With the
    // cloud exactly one version on and that version not ours, the lost
    // try's base version is taken, so it cannot land any more: then safe.
    if (l.sent && l.sent.some((t) => t.lost)) {
      if (c.version > base + 1 || l.sent.some((t) => t.sig === sig(JSON.stringify(c.data)))) return refuse("lost");
    }
    let r;
    try { r = this.rebase({ data: c.data, local: data, version: c.version, by: c.updated_by, at: c.updated_at },
      { ops: a.ops, baseSig: a.baseSig, copy, rev }); } catch (e) { return refuse("threw"); }
    if (r && r.wait) return { wait: r.wait };
    if (!r || r.refused) return refuse((r && r.refused) || "none");
    this._mergelog({ version: c.version, by: c.updated_by, n: a.ops.length, ok: true });
    // The cloud copy is the new base; the actions stay, the cloud does not
    // have them until this upload is saved.  sent goes: its tries are behind.
    // The last action's signature is the merged copy's: the list explains it.
    this._update(copy, (x) => {
      x.version = c.version; x.baseSig = fingerprint(c.data); x.by = c.updated_by; x.at = c.updated_at;
      delete x.sent;
      if (r.after && x.ops && x.ops.length) x.ops[x.ops.length - 1].after = r.after;
    });
    return { merged: { by: c.updated_by, at: c.updated_at, n: a.ops.length } };
  };
  /** A 409: our own save whose answer was lost, a deleted campaign, a merge, or a real conflict. */
  Client.prototype._conflict = async function (copy, id, base, e, data, rev) {
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
          moveBase(x, c.data, hit.rev);
        });
        return { state: "recovered" };
      }
    }
    if (!cur || cur.deleted_at != null) {
      this._update(copy, (x) => { x.gone = true; delete x.sent; });
      return { state: "gone", message: GONE };
    }
    let m = null;
    try { m = await this._merge(copy, l, base, cur, data, rev); } catch (x) { m = null; }
    if (m && m.merged) return { state: "merged", merged: m.merged, current: cur };
    if (m && m.wait) return { state: "wait", why: m.wait };
    this._update(copy, (x) => {
      x.conflict = m && m.why ? Object.assign({}, cur, { why: m.why }) : cur;
      delete x.sent;
    });
    return { state: "conflict", message: e.message, why: m ? m.why : undefined };
  };
  /**
   * Upload one copy until the cloud has it: after a lost answer or a merge,
   * once more with the right version.
   * -> {state: "saved", merged?} | {state: "wait", why} | another state
   */
  Client.prototype._push = async function (copy, getData, keepalive) {
    let merged = null, last = null;
    for (let i = 0; i < 3; i++) {
      const l = this._find(copy);
      if (!l) return { state: "moved" };   // the copy was closed or opened again meanwhile
      if (l.rev <= l.synced) return merged ? { state: "saved", merged } : { state: "saved" };
      const data = getData();
      if (data == null) return { state: "idle" };
      const r = await this._upload(l, data, keepalive);
      if (r.state === "merged") { merged = r.merged; last = r.current || last; continue; }
      if (r.state === "wait") return r;
      if (r.state === "saved") return merged ? { state: "saved", merged } : r;
      if (r.state !== "recovered") return r;
    }
    // Another writer at every try: the user chooses, as before.
    if (merged && last) {
      this._update(copy, (x) => { x.conflict = Object.assign({}, last, { why: "loop" }); delete x.sent; });
      return { state: "conflict", message: "Someone else saved this campaign first.", why: "loop" };
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
    const out = { state: cur && cur.copy === l.copy && cur.rev > cur.synced ? "pending" : "saved" };
    if (r.merged) out.merged = r.merged;
    return out;
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
    this._update(l.copy, (x) => { x.version = r.version; x.by = r.updated_by; x.at = r.updated_at; moveBase(x, r.data); });
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

  // ------------------------------------------------------- the fill timer
  //
  // The fill timer that runs now in the open campaign, shared by the team's
  // devices (worker: /api/campaigns/:id/timer).  It is not campaign data:
  // no version, no merge, no outbox.  The change made last wins, so a
  // device that starts, stops or moves the timer (+20 s) sets it for all.
  //
  //   timer   {run, start, dur, size, lead, early} or null (no timer runs);
  //           run: a random id of one timer run, start: ms
  //   tm      {id, rev}: the cloud's timer rev this device has, per campaign
  //   tmOut   {id, timer, at}: this device's last change, not uploaded yet
  //   skew    the server's clock minus this device's clock, ms
  //
  // On the wire, start and at are on the server's clock; the page gets them
  // on its own clock.  So two phones whose clocks differ by some seconds
  // still ring at the same moment.  Memory only: a reload starts again
  // from the cloud's timer.

  function shift(timer, by) { return timer ? Object.assign({}, timer, { start: Math.round(timer.start + by) }) : null; }

  /** A server answer with `now`: a better estimate of the clock skew replaces the old one. */
  Client.prototype._clock = function (t0, r) {
    const t1 = this.now();
    if (!r || typeof r.now !== "number" || !isFinite(r.now)) return;
    const rtt = Math.max(0, t1 - t0);
    // The error is at most half the round trip: a short trip wins, and an
    // estimate older than 5 minutes yields to any answer.
    if (this.skewRtt == null || rtt <= this.skewRtt + 250 || t1 - this.skewAt > 300000) {
      this.skew = r.now - (t0 + t1) / 2; this.skewRtt = rtt; this.skewAt = t1;
    }
  };
  /** The page started, stopped or changed the fill timer: upload it at the next timerSync. */
  Client.prototype.timerChanged = function (timer) {
    const l = this.link();
    if (!l) return;
    this.tmOut = { id: l.id, timer: timer ? Object.assign({}, timer) : null, at: this.now() };
  };
  /** A timer change of the open campaign waits for upload. */
  Client.prototype.timerWaits = function () { const l = this.link(); return !!(this.tmOut && l && this.tmOut.id === l.id); };

  /**
   * Upload this device's timer change, else ask for a newer one.
   * -> null (nothing new, offline, the campaign is not in the cloud yet) |
   *    {timer, by, at, none}: the cloud's timer, on this device's clock, for
   *    the page; none: the cloud never had one for this campaign
   */
  Client.prototype.timerSync = function (opts) {
    if (this.tmBusy) { this.tmAgain = true; return this.tmBusy; }
    const run = async () => {
      let got = null;
      do {
        this.tmAgain = false;
        const r = await this._timerSync(opts);
        // An upload settles the question; a poll that finds nothing keeps
        // what an earlier round found.
        got = r.pushed ? r.got : r.got || got;
      } while (this.tmAgain);
      return got;
    };
    this.tmBusy = run().finally(() => { this.tmBusy = null; });
    return this.tmBusy;
  };
  Client.prototype._timerSync = async function (opts) {
    const l = this.link();
    if (this.tmOut && (!l || this.tmOut.id !== l.id)) this.tmOut = null;   // another campaign is open now
    if (!l || !(l.version >= 1) || l.gone || !this.here(l) || !this.loggedIn()) return { got: null };
    const path = `/api/campaigns/${encodeURIComponent(l.id)}/timer`;
    // none: the cloud never had a timer for this campaign.
    const back = (x) => ({ timer: shift(x.timer, -(this.skew || 0)), by: x.updated_by || "", at: x.changed_at, none: !x.rev });
    const keep = (x) => { this.tm = { id: l.id, rev: x.rev }; };
    const out = this.tmOut;
    const t0 = this.now();
    if (out) {
      let r;
      try {
        const skew = this.skew || 0;
        r = await this.request("PUT", path, { timer: shift(out.timer, skew), at: Math.round(out.at + skew) }, null,
          { keepalive: !!(opts && opts.keepalive) });
      } catch (e) {
        this._clock(t0, e.body && e.body.current);
        if (e.status === 409 && e.body && e.body.current) {
          // Another device changed the timer later than this one: its change stays.
          if (this.tmOut === out) this.tmOut = null;
          keep(e.body.current);
          return { pushed: true, got: this.tmOut ? null : back(e.body.current) };
        }
        // Offline, busy or an older server: the change waits for the next try.
        if (e.status === 0 || e.status === 429 || e.status >= 500 || e.status === 401) return { pushed: true, got: null };
        if (this.tmOut === out) this.tmOut = null;   // refused (400, 404): it never uploads
        return { pushed: true, got: null };
      }
      this._clock(t0, r);
      if (this.tmOut === out) this.tmOut = null;
      keep(r);
      return { pushed: true, got: null };
    }
    const have = this.tm && this.tm.id === l.id ? this.tm.rev : null;
    let r;
    try { r = await this.request("GET", path + (have != null ? "?have=" + have : "")); } catch (e) { return { got: null }; }
    this._clock(t0, r);
    const cur = this.link();
    if (!cur || cur.id !== l.id) return { got: null };   // another campaign opened meanwhile
    if (this.tmOut) { this.tmAgain = true; return { got: null }; }   // a change here meanwhile: it goes first
    keep(r);
    if (r.same) return { got: null };
    return { got: back(r) };
  };

  const api = { Client, CloudError, newId, normBase, sig, gzip, canon, sessionSig, fingerprint, AUTH, LINK, OUTBOX, MERGES, OPS_MAX };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CalibCloud = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
