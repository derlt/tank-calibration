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

// ---------------------------------------------------------------- lock-screen alarms
// A Durable Object namespace: one PushTimer (worker/push.js) per name, on a
// Map as storage.  `objects` keeps them, so a test moves their clock
// (obj.now) and runs alarm() as the runtime would.
const { PushTimer } = await import(path.join(ROOT, "worker", "push.js"));
export function makePushNamespace(env) {
  const objects = new Map();
  return {
    objects,
    idFromName: (name) => name,
    get(id) {
      if (!objects.has(id)) {
        const data = new Map();
        const storage = {
          data, wake: null,
          async get(k) { return data.get(k); },
          async put(k, v) { data.set(k, structuredClone(v)); },
          async setAlarm(t) { storage.wake = t; },
          async deleteAlarm() { storage.wake = null; },
          async deleteAll() { data.clear(); },
        };
        const obj = new PushTimer({ storage }, env);
        obj.storage = storage;
        objects.set(id, obj);
      }
      const obj = objects.get(id);
      return { fetch: (req) => obj.fetch(req) };
    },
  };
}

/** An environment with the push keys (a fresh P-256 pair) and a Durable Object namespace. */
export async function makePushEnv(over = {}) {
  const { generateKeyPairSync } = await import("node:crypto");
  const { publicKey, privateKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
  const pub = publicKey.export({ format: "jwk" });
  const raw = Buffer.concat([Buffer.from([4]), Buffer.from(pub.x, "base64url"), Buffer.from(pub.y, "base64url")]);
  const env = makeEnv(Object.assign({
    VAPID_PUBLIC_KEY: raw.toString("base64url"),
    VAPID_PRIVATE_KEY: privateKey.export({ format: "jwk" }).d,
    VAPID_SUBJECT: "mailto:ops@example.test",
    PUSH_LIMIT: makeLimiter(1e9),
  }, over));
  env.PUSH_TIMER = makePushNamespace(env);
  return env;
}

/** A browser's push subscription for a test: its key pair, to decrypt what the Worker sends. */
export async function makeSubscription(endpoint = "https://web.push.apple.com/abc123") {
  const { generateKeyPairSync, randomBytes } = await import("node:crypto");
  const { publicKey, privateKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
  const j = publicKey.export({ format: "jwk" });
  const p256dh = Buffer.concat([Buffer.from([4]), Buffer.from(j.x, "base64url"), Buffer.from(j.y, "base64url")]);
  const auth = randomBytes(16);
  return { subscription: { endpoint, keys: { p256dh: p256dh.toString("base64url"), auth: auth.toString("base64url") } }, privateKey, p256dh, auth };
}

/** Decrypt a push body (RFC 8291, aes128gcm) with the subscription's private key. */
export async function decryptPush(sub, body) {
  const { createECDH, createDecipheriv, hkdfSync } = await import("node:crypto");
  const b = Buffer.from(body);
  const salt = b.subarray(0, 16), idlen = b[20], asPub = b.subarray(21, 21 + idlen), data = b.subarray(21 + idlen);
  const jwk = sub.privateKey.export({ format: "jwk" });
  const ecdh = createECDH("prime256v1");
  ecdh.setPrivateKey(Buffer.from(jwk.d, "base64url"));
  const shared = ecdh.computeSecret(asPub);
  const ikm = Buffer.from(hkdfSync("sha256", shared, sub.auth, Buffer.concat([Buffer.from("WebPush: info\0"), sub.p256dh, asPub]), 32));
  const cek = Buffer.from(hkdfSync("sha256", ikm, salt, "Content-Encoding: aes128gcm\0", 16));
  const nonce = Buffer.from(hkdfSync("sha256", ikm, salt, "Content-Encoding: nonce\0", 12));
  const d = createDecipheriv("aes-128-gcm", cek, nonce);
  d.setAuthTag(data.subarray(data.length - 16));
  const plain = Buffer.concat([d.update(data.subarray(0, data.length - 16)), d.final()]);
  return { text: plain.subarray(0, plain.length - 1).toString("utf8"), delimiter: plain[plain.length - 1], rs: b.readUInt32BE(16) };
}
