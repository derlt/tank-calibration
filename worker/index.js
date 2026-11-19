/* Cloud store for the on-site page: a small JSON API on D1.
 *
 * The page works without it.  The page keeps every session in the browser
 * first; this API is an optional copy that a team shares.
 *
 *   workspace   a team space: a name plus a secret keyword (the password)
 *   token       a login: random, 30 days, sent as "Authorization: Bearer"
 *   campaign    one session JSON of the page, with a version number
 *
 * Security
 *   - The keyword is stored only as PBKDF2-SHA256 (100 000 rounds, random salt).
 *   - A token is stored only as SHA-256.  Logout deletes it.
 *   - A new workspace needs the signup code (secret SIGNUP_CODE).  Without
 *     that secret, nobody can make a workspace.
 *   - Every campaign query is scoped by the workspace of the token.
 *   - A save names the version it started from.  An older version is a
 *     conflict (409): nothing is overwritten.
 *   - No cookies: the token is not sent by the browser on its own, so
 *     other sites cannot act for a user (no CSRF).
 *
 * Abuse and flood limits
 *   - Rate limit bindings per IP address: API_LIMIT for every request,
 *     AUTH_LIMIT for login and signup.  Over the limit: 429.
 *   - Failed logins in D1: 10 per IP address and 50 per workspace in
 *     15 minutes, then 429 until the window ends.
 *   - Body size, campaign count and field lengths have hard limits.
 *   - API_HOSTS (a plain variable, comma-separated host names): the API
 *     answers only on these hosts, so every API call passes the zone
 *     firewall.  The workers.dev and preview addresses get 403.  Empty:
 *     every host (local tests).
 *   - Only /api/* runs this code.  The page itself is a static asset, so a
 *     flood of API requests cannot take the page down, and the page keeps
 *     working offline.
 */

export const LIMITS = {
  body: 1_000_000,          // bytes of one request body
  campaigns: 2000,          // live campaigns per workspace
  tokenDays: 30,
  iterations: 100_000,      // PBKDF2 rounds (the Workers maximum)
  failWindow: 15 * 60 * 1000,
  failIp: 10,
  failWorkspace: 50,
  keywordMin: 12,
  keywordMax: 200,
};

const enc = new TextEncoder();

class HttpError extends Error {
  constructor(status, message, extra) { super(message); this.status = status; this.extra = extra || {}; }
}

// ------------------------------------------------------------------ helpers
function hex(buf) { return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join(""); }
function b64url(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function randomBytes(n) { const a = new Uint8Array(n); crypto.getRandomValues(a); return a; }
async function sha256(text) { return hex(await crypto.subtle.digest("SHA-256", enc.encode(text))); }

/** Equal strings in a time that does not depend on where they differ. */
function sameText(a, b) {
  const x = enc.encode(String(a)), y = enc.encode(String(b));
  let d = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) d |= (x[i] || 0) ^ (y[i] || 0);
  return d === 0;
}

async function pbkdf2(keyword, saltHex, iterations) {
  const salt = new Uint8Array(saltHex.match(/../g).map((h) => parseInt(h, 16)));
  const key = await crypto.subtle.importKey("raw", enc.encode(keyword.normalize("NFC")), "PBKDF2", false, ["deriveBits"]);
  return hex(await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations }, key, 256));
}

const HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  // Bearer tokens, no cookies: any origin may call, including the page
  // opened as a local file (origin "null").
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
  "Access-Control-Max-Age": "86400",
};
function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), { status, headers: Object.assign({}, HEADERS, extra) });
}

/** The API answers only on the hosts in API_HOSTS (all hosts when it is empty). */
export function hostAllowed(env, url) {
  const list = String(env.API_HOSTS || "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  return !list.length || list.includes(url.hostname.toLowerCase());
}

function clientIp(request) { return request.headers.get("cf-connecting-ip") || "local"; }

async function rateLimit(env, name, key) {
  const b = env[name];
  if (!b || typeof b.limit !== "function") return;
  const { success } = await b.limit({ key });
  if (!success) throw new HttpError(429, "Too many requests. Wait one minute.", { "Retry-After": "60" });
}

/**
 * A request body as text.  The page sends a large body gzipped (a campaign
 * is mostly repeated JSON keys: about a fifth of the size), so an upload
 * over a weak site network finishes in time.  A gzip body is known by its
 * first two bytes (1f 8b; JSON text never starts so), not by a header, so
 * it works whatever the network does with the headers.  The limit holds
 * for the unpacked text too: a small body that unpacks to much more stops
 * at LIMITS.body.
 */
async function readBody(request) {
  const n = Number(request.headers.get("content-length") || 0);
  if (n > LIMITS.body) throw new HttpError(413, "The request is too large.");
  const raw = new Uint8Array(await request.arrayBuffer());
  if (raw.length > LIMITS.body) throw new HttpError(413, "The request is too large.");
  const text = raw.length >= 2 && raw[0] === 0x1f && raw[1] === 0x8b
    ? await gunzip(raw, LIMITS.body)
    : new TextDecoder().decode(raw);
  try {
    const v = JSON.parse(text || "{}");
    if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error();
    return v;
  } catch (e) { throw new HttpError(400, "The request body is not a JSON object."); }
}

/** Unpack a gzip body to text, at most max bytes; more is 413, a bad stream 400. */
async function gunzip(bytes, max) {
  const reader = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip")).getReader();
  const parts = [];
  let total = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.length;
      if (total > max) { await reader.cancel().catch(() => {}); throw new HttpError(413, "The request is too large."); }
      parts.push(value);
    }
  } catch (e) {
    if (e instanceof HttpError) throw e;
    throw new HttpError(400, "The request body is not valid gzip.");
  }
  const out = new Uint8Array(total);
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return new TextDecoder().decode(out);
}

// ------------------------------------------------------------------ validation
function workspaceName(v) {
  const s = String(v == null ? "" : v).trim().toLowerCase();
  if (!/^[a-z0-9][a-z0-9_-]{2,39}$/.test(s)) {
    throw new HttpError(400, "Workspace: 3 to 40 characters, letters, digits, - or _.");
  }
  return s;
}
function keyword(v) {
  const s = typeof v === "string" ? v : "";
  if (s.length < LIMITS.keywordMin) throw new HttpError(400, `The secret keyword needs ${LIMITS.keywordMin} characters or more.`);
  if (s.length > LIMITS.keywordMax) throw new HttpError(400, "The secret keyword is too long.");
  return s;
}
function userName(v) {
  // Printable text only: no control characters.
  const s = String(v == null ? "" : v).replace(/[\u0000-\u001f\u007f]/g, "").trim().slice(0, 40);
  if (!s) throw new HttpError(400, "Enter your name.");
  return s;
}
function campaignId(v) {
  if (!/^[A-Za-z0-9-]{8,64}$/.test(v || "")) throw new HttpError(400, "Bad campaign id.");
  return v;
}
/** The page's session JSON: one tank (config + levels) or a transfer (out + in). */
function sessionSummary(data) {
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new HttpError(400, "The campaign is not a session.");
  const one = (s) => s && typeof s === "object" && s.config && typeof s.config === "object" && Array.isArray(s.levels);
  const name = (s) => String(s.config.tank == null ? "tank" : s.config.tank);
  if (data.kind === "transfer") {
    if (!one(data.out) || !one(data.in)) throw new HttpError(400, "The campaign is not a session.");
    return { tank: `${name(data.out)} → ${name(data.in)}`.slice(0, 80), levels: data.out.levels.length };
  }
  if (!one(data)) throw new HttpError(400, "The campaign is not a session.");
  return { tank: name(data).slice(0, 80), levels: data.levels.length };
}

// ------------------------------------------------------------------ failed logins
async function failsOver(env, keys, now) {
  const rows = (await env.DB.prepare("SELECT key, count, since FROM fails WHERE key IN (?1, ?2)")
    .bind(keys.ip, keys.ws || "-").all()).results || [];
  for (const r of rows) {
    const max = r.key === keys.ip ? LIMITS.failIp : LIMITS.failWorkspace;
    if (now - r.since < LIMITS.failWindow && r.count >= max) return Math.ceil((r.since + LIMITS.failWindow - now) / 1000);
  }
  return 0;
}
async function recordFail(env, keys, now) {
  const sql = "INSERT INTO fails (key, count, since) VALUES (?1, 1, ?2) ON CONFLICT(key) DO UPDATE SET "
    + "count = CASE WHEN ?2 - since >= ?3 THEN 1 ELSE count + 1 END, "
    + "since = CASE WHEN ?2 - since >= ?3 THEN ?2 ELSE since END";
  const stmts = [env.DB.prepare(sql).bind(keys.ip, now, LIMITS.failWindow)];
  if (keys.ws) stmts.push(env.DB.prepare(sql).bind(keys.ws, now, LIMITS.failWindow));
  await env.DB.batch(stmts);
}
async function guardFails(env, keys, now) {
  const wait = await failsOver(env, keys, now);
  if (wait > 0) {
    throw new HttpError(429, `Too many failed attempts. Try again in ${Math.ceil(wait / 60)} min.`, { "Retry-After": String(wait) });
  }
}

// ------------------------------------------------------------------ tokens
async function issueToken(env, workspace, user, now) {
  const token = b64url(randomBytes(32));
  const expires = now + LIMITS.tokenDays * 86400 * 1000;
  await env.DB.batch([
    env.DB.prepare("DELETE FROM tokens WHERE expires_at < ?1").bind(now),
    env.DB.prepare("INSERT INTO tokens (hash, workspace_id, user, created_at, expires_at) VALUES (?1, ?2, ?3, ?4, ?5)")
      .bind(await sha256(token), workspace.id, user, now, expires),
  ]);
  return { token, workspace: workspace.name, user, expires };
}

async function auth(request, env, now) {
  const m = /^Bearer ([A-Za-z0-9_-]{43})$/.exec(request.headers.get("authorization") || "");
  if (!m) throw new HttpError(401, "Log in first.");
  const hash = await sha256(m[1]);
  const row = await env.DB.prepare(
    "SELECT t.hash, t.workspace_id, t.user, t.expires_at, w.name FROM tokens t JOIN workspaces w ON w.id = t.workspace_id WHERE t.hash = ?1",
  ).bind(hash).first();
  if (!row || row.expires_at < now) throw new HttpError(401, "The login has expired. Log in again.");
  return { hash, ws: row.workspace_id, workspace: row.name, user: row.user, expires: row.expires_at };
}

// ------------------------------------------------------------------ routes
async function signup(request, env, now) {
  const ip = clientIp(request);
  await rateLimit(env, "AUTH_LIMIT", ip);
  const keys = { ip: "ip:" + ip };
  await guardFails(env, keys, now);
  const body = await readBody(request);
  if (!env.SIGNUP_CODE) throw new HttpError(403, "New workspaces are switched off on this server.");
  if (!sameText(await sha256(String(body.signup_code || "")), await sha256(env.SIGNUP_CODE))) {
    await recordFail(env, keys, now);
    throw new HttpError(403, "Wrong signup code.");
  }
  const name = workspaceName(body.workspace), kw = keyword(body.keyword), user = userName(body.user);
  const salt = hex(randomBytes(16));
  const ws = { id: hex(randomBytes(16)), name };
  const r = await env.DB.prepare(
    "INSERT INTO workspaces (id, name, salt, hash, iterations, created_at, created_by) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7) ON CONFLICT(name) DO NOTHING",
  ).bind(ws.id, name, salt, await pbkdf2(kw, salt, LIMITS.iterations), LIMITS.iterations, now, user).run();
  if (!r.meta || !r.meta.changes) throw new HttpError(409, "That workspace name is taken. Choose another, or log in.");
  return json(await issueToken(env, ws, user, now), 201);
}

const DUMMY_SALT = "00".repeat(16);
async function login(request, env, now) {
  const ip = clientIp(request);
  await rateLimit(env, "AUTH_LIMIT", ip);
  const body = await readBody(request);
  const name = workspaceName(body.workspace), user = userName(body.user);
  const kw = typeof body.keyword === "string" ? body.keyword.slice(0, LIMITS.keywordMax) : "";
  const keys = { ip: "ip:" + ip, ws: "ws:" + name };
  await guardFails(env, keys, now);
  const ws = await env.DB.prepare("SELECT id, name, salt, hash, iterations FROM workspaces WHERE name = ?1").bind(name).first();
  // Hash even when the workspace does not exist: the answer time does not
  // tell which workspace names exist.
  const got = await pbkdf2(kw, ws ? ws.salt : DUMMY_SALT, ws ? ws.iterations : LIMITS.iterations);
  if (!ws || !sameText(got, ws.hash)) {
    await recordFail(env, keys, now);
    throw new HttpError(401, "Wrong workspace or secret keyword.");
  }
  return json(await issueToken(env, ws, user, now));
}

async function logout(request, env, now) {
  const a = await auth(request, env, now);
  await env.DB.prepare("DELETE FROM tokens WHERE hash = ?1").bind(a.hash).run();
  return json({ ok: true });
}

async function listCampaigns(env, a) {
  const rows = (await env.DB.prepare(
    "SELECT id, tank, levels, version, created_at, created_by, updated_at, updated_by FROM campaigns "
    + "WHERE workspace_id = ?1 AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 500",
  ).bind(a.ws).all()).results || [];
  return json({ workspace: a.workspace, user: a.user, campaigns: rows });
}

async function getCampaign(env, a, id, url) {
  const have = url.searchParams.get("have");
  const known = have != null && /^\d+$/.test(have) ? Number(have) : -1;
  // One read: the version and the data are of the same save.  A caller that
  // already has this version gets no data (a cheap poll).
  const row = await env.DB.prepare(
    "SELECT id, tank, levels, version, updated_at, updated_by, deleted_at, "
    + "CASE WHEN version = ?3 THEN NULL ELSE data END AS data FROM campaigns WHERE workspace_id = ?1 AND id = ?2",
  ).bind(a.ws, id, known).first();
  if (!row || row.deleted_at != null) throw new HttpError(404, "No such campaign in this workspace.");
  const { data, deleted_at: _, ...meta } = row;
  if (row.version === known) return json(Object.assign({ same: true }, meta));
  return json(Object.assign({ data: JSON.parse(data) }, meta));
}

async function conflict(env, a, id) {
  const cur = await env.DB.prepare(
    "SELECT version, updated_at, updated_by, deleted_at FROM campaigns WHERE workspace_id = ?1 AND id = ?2",
  ).bind(a.ws, id).first();
  return json({ error: "Someone else saved this campaign first.", conflict: true, current: cur || null }, 409);
}

async function putCampaign(request, env, a, id, now) {
  const body = await readBody(request);
  const base = Number(body.base_version);
  if (!Number.isInteger(base) || base < 0) throw new HttpError(400, "base_version must be a whole number.");
  const sum = sessionSummary(body.data);
  const data = JSON.stringify(body.data);
  if (base === 0) {
    const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM campaigns WHERE workspace_id = ?1 AND deleted_at IS NULL").bind(a.ws).first();
    if (n && n.n >= LIMITS.campaigns) throw new HttpError(403, "This workspace is full. Delete old campaigns first.");
    const r = await env.DB.prepare(
      "INSERT INTO campaigns (workspace_id, id, tank, levels, version, data, created_at, created_by, updated_at, updated_by) "
      + "VALUES (?1, ?2, ?3, ?4, 1, ?5, ?6, ?7, ?6, ?7) ON CONFLICT(workspace_id, id) DO NOTHING",
    ).bind(a.ws, id, sum.tank, sum.levels, data, now, a.user).run();
    if (!r.meta || !r.meta.changes) return conflict(env, a, id);
    return json({ id, version: 1, updated_at: now, updated_by: a.user }, 201);
  }
  // One statement: the version check and the write cannot be split by
  // another save.  A deleted campaign stays deleted: the save gets 409 with
  // deleted_at, and the page offers to upload it as a new campaign (so the
  // campaign limit holds).
  const r = await env.DB.prepare(
    "UPDATE campaigns SET tank = ?3, levels = ?4, data = ?5, version = version + 1, updated_at = ?6, updated_by = ?7 "
    + "WHERE workspace_id = ?1 AND id = ?2 AND version = ?8 AND deleted_at IS NULL",
  ).bind(a.ws, id, sum.tank, sum.levels, data, now, a.user, base).run();
  if (!r.meta || !r.meta.changes) return conflict(env, a, id);
  return json({ id, version: base + 1, updated_at: now, updated_by: a.user });
}

async function deleteCampaign(env, a, id, url, now) {
  const base = Number(url.searchParams.get("base_version"));
  if (!Number.isInteger(base) || base < 1) throw new HttpError(400, "base_version must be a whole number.");
  // Soft delete: the row stays, so an operator can restore it in D1.
  const r = await env.DB.prepare(
    "UPDATE campaigns SET deleted_at = ?3, updated_at = ?3, updated_by = ?4, version = version + 1 "
    + "WHERE workspace_id = ?1 AND id = ?2 AND version = ?5 AND deleted_at IS NULL",
  ).bind(a.ws, id, now, a.user, base).run();
  if (!r.meta || !r.meta.changes) return conflict(env, a, id);
  return json({ ok: true });
}

async function route(request, env, url, now) {
  const path = url.pathname, method = request.method;
  if (path === "/api/health" && method === "GET") return json({ ok: true });
  if (!env.DB) throw new HttpError(503, "The cloud store is not set up on this server.");
  if (path === "/api/workspaces" && method === "POST") return signup(request, env, now);
  if (path === "/api/login" && method === "POST") return login(request, env, now);
  if (path === "/api/logout" && method === "POST") return logout(request, env, now);
  const a = await auth(request, env, now);
  if (path === "/api/me" && method === "GET") return json({ workspace: a.workspace, user: a.user, expires: a.expires });
  if (path === "/api/campaigns" && method === "GET") return listCampaigns(env, a);
  const m = /^\/api\/campaigns\/([^/]+)$/.exec(path);
  if (m) {
    let raw;
    try { raw = decodeURIComponent(m[1]); } catch (e) { throw new HttpError(400, "Bad campaign id."); }
    const id = campaignId(raw);
    if (method === "GET") return getCampaign(env, a, id, url);
    if (method === "PUT") return putCampaign(request, env, a, id, now);
    if (method === "DELETE") return deleteCampaign(env, a, id, url, now);
  }
  throw new HttpError(404, "No such API route.");
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/")) {
      return env.ASSETS ? env.ASSETS.fetch(request) : new Response("Not found", { status: 404 });
    }
    if (!hostAllowed(env, url)) return json({ error: "The cloud works only at the main address of the page." }, 403);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: HEADERS });
    try {
      await rateLimit(env, "API_LIMIT", clientIp(request));
      return await route(request, env, url, Date.now());
    } catch (e) {
      if (e instanceof HttpError) return json({ error: e.message }, e.status, e.extra);
      console.error(e);
      return json({ error: "Server error." }, 500);
    }
  },
};
