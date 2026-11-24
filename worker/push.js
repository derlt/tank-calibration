/* Web Push for the lock-screen alarms: the sender, and the store of one device.
 *
 * iOS stops a page's scripts and sound when the phone locks.  A device that
 * has the page as a Home Screen app can get a push at the alarm time: the
 * page sends the alarms as "in N seconds"; PushTimer, a Durable Object per
 * device, keeps them and wakes at the earliest one (alarm()) to send.
 *
 *   - No login: a device holds a random secret (the page makes it); the
 *     store of the device is named by the SHA-256 of the secret.  Whoever
 *     knows the secret manages that device's alarms, nobody else.
 *   - Times are relative (seconds from the request), counted on the
 *     server's clock: a wrong phone clock does not matter.
 *   - Only known push services get a request (pushHostAllowed): the Worker
 *     never sends to an address a user chose.
 *   - The payload is encrypted (RFC 8291, aes128gcm), so the service worker
 *     shows the text with no call back to the API.
 *   - An alarm more than LATE_MS late is dropped: a late "close the valve"
 *     is worse than none.
 */

const enc = new TextEncoder();

export const LIMITS = {
  alarms: 10,
  inMin: 1,
  inMax: 6 * 3600,
  title: 120,
  body: 300,
  endpoint: 600,
  lateMs: 120_000,
};
export const KINDS = ["pre", "full", "settle"];

// ------------------------------------------------------------------ bytes
export function b64urlEncode(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
export function b64urlDecode(text) {
  const t = String(text).replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(t + "=".repeat((4 - (t.length % 4)) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}
function concat(...parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
}

// ------------------------------------------------------------------ hosts
/** Only the push services of the browsers.  Not an address a user typed. */
export function pushHostAllowed(endpoint) {
  let u;
  try { u = new URL(endpoint); } catch (e) { return false; }
  if (u.protocol !== "https:" || u.port || u.username || u.password) return false;
  const h = u.hostname.toLowerCase();
  return h === "web.push.apple.com" || h.endsWith(".push.apple.com")
    || h === "fcm.googleapis.com"
    || h === "updates.push.services.mozilla.com"
    || h.endsWith(".notify.windows.com");
}

/** A browser subscription, checked: {endpoint, p256dh, auth} or null. */
export function cleanSubscription(v) {
  if (!v || typeof v !== "object" || !v.keys || typeof v.endpoint !== "string") return null;
  if (v.endpoint.length > LIMITS.endpoint || !pushHostAllowed(v.endpoint)) return null;
  try {
    const p = b64urlDecode(v.keys.p256dh), a = b64urlDecode(v.keys.auth);
    if (p.length !== 65 || p[0] !== 4 || a.length !== 16) return null;
  } catch (e) { return null; }
  return { endpoint: v.endpoint, p256dh: v.keys.p256dh, auth: v.keys.auth };
}

/** The alarms of a request, checked: [{in, kind, title, body}] or null. */
export function cleanAlarms(v) {
  if (!Array.isArray(v) || v.length > LIMITS.alarms) return null;
  const out = [];
  for (const x of v) {
    if (!x || typeof x !== "object") return null;
    const sec = Number(x.in);
    if (!Number.isFinite(sec) || sec < LIMITS.inMin || sec > LIMITS.inMax) return null;
    if (!KINDS.includes(x.kind)) return null;
    const title = typeof x.title === "string" ? x.title.slice(0, LIMITS.title) : "";
    const body = typeof x.body === "string" ? x.body.slice(0, LIMITS.body) : "";
    if (!title) return null;
    out.push({ in: Math.round(sec), kind: x.kind, title, body });
  }
  return out;
}

// ------------------------------------------------------------------ VAPID
function ecJwk(pub, priv) {
  const p = b64urlDecode(pub);
  const jwk = { kty: "EC", crv: "P-256", x: b64urlEncode(p.slice(1, 33)), y: b64urlEncode(p.slice(33, 65)), ext: true };
  if (priv) jwk.d = priv;
  return jwk;
}

/** The VAPID Authorization header for a push service (RFC 8292), valid 12 h. */
export async function vapidHeader(endpoint, env, nowMs) {
  const key = await crypto.subtle.importKey("jwk", ecJwk(env.VAPID_PUBLIC_KEY, env.VAPID_PRIVATE_KEY),
    { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
  const head = b64urlEncode(enc.encode(JSON.stringify({ typ: "JWT", alg: "ES256" })));
  const claims = b64urlEncode(enc.encode(JSON.stringify({
    aud: new URL(endpoint).origin,
    exp: Math.floor(nowMs / 1000) + 12 * 3600,
    sub: env.VAPID_SUBJECT,
  })));
  const sig = new Uint8Array(await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, enc.encode(`${head}.${claims}`)));
  return `vapid t=${head}.${claims}.${b64urlEncode(sig)}, k=${env.VAPID_PUBLIC_KEY}`;
}

// ------------------------------------------------------------- encryption
async function hkdf(salt, ikm, info, bytes) {
  const k = await crypto.subtle.importKey("raw", ikm, "HKDF", false, ["deriveBits"]);
  return new Uint8Array(await crypto.subtle.deriveBits({ name: "HKDF", hash: "SHA-256", salt, info }, k, bytes * 8));
}

/** The body of a push (RFC 8291, aes128gcm, one record) for a subscription's p256dh and auth. */
export async function encryptPayload(sub, plain) {
  const ua = b64urlDecode(sub.p256dh), auth = b64urlDecode(sub.auth);
  const mine = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  const mineRaw = new Uint8Array(await crypto.subtle.exportKey("raw", mine.publicKey));
  const theirs = await crypto.subtle.importKey("raw", ua, { name: "ECDH", namedCurve: "P-256" }, false, []);
  const shared = new Uint8Array(await crypto.subtle.deriveBits({ name: "ECDH", public: theirs }, mine.privateKey, 256));
  const ikm = await hkdf(auth, shared, concat(enc.encode("WebPush: info\0"), ua, mineRaw), 32);
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const cek = await hkdf(salt, ikm, enc.encode("Content-Encoding: aes128gcm\0"), 16);
  const nonce = await hkdf(salt, ikm, enc.encode("Content-Encoding: nonce\0"), 12);
  const aes = await crypto.subtle.importKey("raw", cek, "AES-GCM", false, ["encrypt"]);
  const data = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce }, aes, concat(plain, Uint8Array.of(2))));
  const head = new Uint8Array(21);
  head.set(salt, 0);
  new DataView(head.buffer).setUint32(16, 4096);
  head[20] = mineRaw.length;
  return concat(head, mineRaw, data);
}

/**
 * Send one push.  -> the push service's status (201 sent, 404 or 410: the
 * subscription is gone), or 0 when the service did not answer.
 */
export async function sendPush(env, sub, message, nowMs) {
  if (!pushHostAllowed(sub.endpoint)) return 400;
  const body = await encryptPayload(sub, enc.encode(JSON.stringify(message)));
  try {
    const r = await fetch(sub.endpoint, {
      method: "POST",
      headers: {
        Authorization: await vapidHeader(sub.endpoint, env, nowMs),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        TTL: "60",
        Urgency: "high",
        Topic: String(message.kind || "calib").slice(0, 32),
      },
      body,
    });
    return r.status;
  } catch (e) {
    console.error("push send failed", e && e.message);
    return 0;
  }
}

// ---------------------------------------------------------------- the store
/**
 * One device: its subscription and its alarms.  A classic Durable Object
 * (a fetch handler), called by the Worker with JSON:
 *   POST /subscribe {subscription}   PUT /alarms {alarms, now}
 *   DELETE /alarms                   DELETE /subscribe        GET /state
 */
export class PushTimer {
  constructor(state, env) { this.state = state; this.env = env; this.now = () => Date.now(); }

  async fetch(request) {
    const path = new URL(request.url).pathname, method = request.method;
    const st = this.state.storage;
    if (path === "/subscribe" && method === "POST") {
      const { subscription } = await request.json();
      await st.put("sub", subscription);
      return Response.json({ ok: true });
    }
    if (path === "/subscribe" && method === "DELETE") {
      await st.deleteAlarm();
      await st.deleteAll();
      return Response.json({ ok: true });
    }
    if (path === "/alarms" && method === "PUT") {
      if (!(await st.get("sub"))) return Response.json({ error: "No subscription for this device." }, { status: 409 });
      const { alarms } = await request.json();
      const at = this.now();
      await this.keep(alarms.map((a) => ({ at: at + a.in * 1000, kind: a.kind, title: a.title, body: a.body })));
      return Response.json({ ok: true, count: alarms.length });
    }
    if (path === "/alarms" && method === "DELETE") {
      await this.keep([]);
      return Response.json({ ok: true });
    }
    if (path === "/state" && method === "GET") {
      return Response.json({ subscribed: !!(await st.get("sub")), alarms: (await st.get("alarms")) || [] });
    }
    return Response.json({ error: "No such route." }, { status: 404 });
  }

  /** Store the list and wake at the earliest alarm (or at none). */
  async keep(list) {
    const st = this.state.storage;
    list.sort((a, b) => a.at - b.at);
    await st.put("alarms", list);
    if (list.length) await st.setAlarm(list[0].at);
    else await st.deleteAlarm();
  }

  /** Send what is due, drop what is too late, wake again for the next. */
  async alarm() {
    const st = this.state.storage;
    const sub = await st.get("sub");
    const list = (await st.get("alarms")) || [];
    const now = this.now();
    const due = list.filter((a) => a.at <= now);
    const rest = list.filter((a) => a.at > now);
    // Store the rest first: an error below must not send the same alarm again.
    await this.keep(rest);
    if (!sub) return;
    for (const a of due) {
      if (now - a.at > LIMITS.lateMs) continue;
      const status = await sendPush(this.env, sub, { title: a.title, body: a.body, kind: a.kind }, now);
      if (status === 404 || status === 410) {   // the device removed the subscription
        await st.deleteAlarm();
        await st.deleteAll();
        return;
      }
    }
  }
}
