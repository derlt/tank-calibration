// Run the cloud Worker (worker/index.js) under Node, with no network.
//
// D1 is SQLite: a stub on node:sqlite runs the real schema and the real
// queries.  The rate limit bindings are counters.  fetchFor() gives a fetch
// function that sends the request to the Worker in-process, so the page's
// client (site/cloud.js) talks to the real server code.
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import path from "node:path";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
export const worker = (await import(path.join(ROOT, "worker", "index.js"))).default;
export const { LIMITS } = await import(path.join(ROOT, "worker", "index.js"));

export function makeD1() {
  const db = new DatabaseSync(":memory:");
  db.exec("PRAGMA foreign_keys = ON");
  db.exec(readFileSync(path.join(ROOT, "worker", "schema.sql"), "utf8"));
  const runOne = (s) => {
    const st = db.prepare(s.sql);
    if (/^\s*(SELECT|WITH)/i.test(s.sql)) return { results: st.all(...s.args) };
    const r = st.run(...s.args);
    return { meta: { changes: Number(r.changes) } };
  };
  class Stmt {
    constructor(sql, args) { this.sql = sql; this.args = args || []; }
    bind(...a) { return new Stmt(this.sql, a); }
    async first() { const r = db.prepare(this.sql).get(...this.args); return r ? Object.assign({}, r) : null; }
    async all() { return { results: db.prepare(this.sql).all(...this.args).map((r) => Object.assign({}, r)) }; }
    async run() { return runOne(this); }
  }
  return {
    raw: db,
    prepare: (sql) => new Stmt(sql),
    async batch(stmts) {
      db.exec("BEGIN");
      try { const out = stmts.map(runOne); db.exec("COMMIT"); return out; } catch (e) { db.exec("ROLLBACK"); throw e; }
    },
  };
}

/** A rate limit binding: `limit` calls per key, then { success: false }. */
export function makeLimiter(limit) {
  const n = new Map();
  return {
    calls: n,
    async limit({ key }) { const c = (n.get(key) || 0) + 1; n.set(key, c); return { success: c <= limit }; },
  };
}

export function makeEnv(over = {}) {
  return Object.assign({
    DB: makeD1(),
    SIGNUP_CODE: "test-signup-code",
    API_LIMIT: makeLimiter(1e9),
    AUTH_LIMIT: makeLimiter(1e9),
  }, over);
}

/** fetch() that answers from the Worker.  ip sets cf-connecting-ip. */
export function fetchFor(env, ip = "198.51.100.7") {
  return async (url, init = {}) => {
    const headers = new Headers(init.headers || {});
    headers.set("cf-connecting-ip", ip);
    const req = new Request(url, { method: init.method || "GET", headers, body: init.body });
    return worker.fetch(req, env);
  };
}

export const BASE = "https://cloud.test";

/** One call: method, path, body, token -> { status, body, headers }. */
export async function call(env, method, p, body, token, ip) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = "Bearer " + token;
  const res = await fetchFor(env, ip)(BASE + p, { method, headers, body: body == null ? undefined : JSON.stringify(body) });
  let out = null;
  try { out = await res.json(); } catch (e) { out = null; }
  return { status: res.status, body: out, headers: Object.fromEntries(res.headers) };
}

/** A small session JSON, as the page saves it. */
export function session(tank = "t1", levels = 2) {
  return { version: 1, config: { tank, D: 2400, Lest: 5000 }, levels: Array.from({ length: levels }, (_, i) => ({ row: i + 1, H: 100 + 30 * i, dips: [100 + 30 * i] })), batch: null };
}
