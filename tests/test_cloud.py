# ruff: noqa: S608  -- the strings are JavaScript test scripts, not SQL built from input.
"""The cloud store: the Worker (worker/index.js) and the page's client (site/cloud.js).

The Worker runs under Node with D1 as an in-memory SQLite database
(tests/cloud_harness.mjs), so these tests run the real schema and the real
queries, with no network.  They need Node 22.5 or newer (node:sqlite).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NODE = shutil.which("node")
HARNESS = (HERE / "cloud_harness.mjs").as_uri()
CLOUD = (ROOT / "site" / "cloud.js").as_posix()


def _has_sqlite() -> bool:
    if not NODE:
        return False
    out = subprocess.run(  # noqa: S603
        [NODE, "-e", "require('node:sqlite')"], capture_output=True, text=True, check=False
    )
    return out.returncode == 0


SQLITE = _has_sqlite()


def _run(body: str):
    """Run an ES module with the harness as `h` and the client as `cloud`; it prints one JSON value."""
    script = (
        f"import * as h from {json.dumps(HARNESS)};\n"
        "import { createRequire } from 'node:module';\n"
        "const require = createRequire(import.meta.url);\n"
        f"const cloud = require({json.dumps(CLOUD)});\n"
        "const out = {};\n"
        f"{body}\n"
        "console.log(JSON.stringify(out));\n"
    )
    res = subprocess.run(  # noqa: S603
        [NODE, "--no-warnings", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if res.returncode != 0:
        raise AssertionError(res.stderr)
    return json.loads(res.stdout)


SIGNUP = (
    "const env = h.makeEnv();\n"
    "const s = await h.call(env, 'POST', '/api/workspaces', "
    "{ workspace: 'Team-1', keyword: 'correct horse battery', user: 'An', signup_code: 'test-signup-code' });\n"
    "const tok = s.body.token;\n"
)


@unittest.skipUnless(SQLITE, "node with node:sqlite is not installed")
class TestWorkspace(unittest.TestCase):
    def test_signup_needs_the_code_and_a_long_keyword(self):
        got = _run(
            "const env = h.makeEnv();\n"
            "const ok = { workspace: 'team-1', keyword: 'correct horse battery', user: 'An', signup_code: 'test-signup-code' };\n"
            "out.wrong = (await h.call(env, 'POST', '/api/workspaces', { ...ok, signup_code: 'guess' })).status;\n"
            "out.short = (await h.call(env, 'POST', '/api/workspaces', { ...ok, keyword: 'short' })).status;\n"
            "out.badName = (await h.call(env, 'POST', '/api/workspaces', { ...ok, workspace: 'a b' })).status;\n"
            "const r = await h.call(env, 'POST', '/api/workspaces', ok);\n"
            "out.ok = r.status; out.name = r.body.workspace; out.tokenLen = r.body.token.length;\n"
            "out.again = (await h.call(env, 'POST', '/api/workspaces', { ...ok, workspace: 'TEAM-1' })).status;\n"
            "const off = h.makeEnv({ SIGNUP_CODE: '' });\n"
            "out.off = (await h.call(off, 'POST', '/api/workspaces', ok)).status;\n"
            "const row = env.DB.raw.prepare('SELECT * FROM workspaces').get();\n"
            "out.stored = JSON.stringify(row);\n"
            "out.tokens = JSON.stringify(env.DB.raw.prepare('SELECT * FROM tokens').all());\n"
            "out.token = r.body.token;\n"
        )
        self.assertEqual(got["wrong"], 403)
        self.assertEqual(got["short"], 400)
        self.assertEqual(got["badName"], 400)
        self.assertEqual(got["ok"], 201)
        self.assertEqual(got["name"], "team-1", "names are lower case")
        self.assertEqual(got["tokenLen"], 43, "32 random bytes, base64url")
        self.assertEqual(got["again"], 409, "one name, one workspace")
        self.assertEqual(got["off"], 403, "no SIGNUP_CODE: no new workspaces")
        self.assertNotIn("correct horse battery", got["stored"], "the keyword is never stored")
        self.assertNotIn(got["token"], got["tokens"], "the token is never stored")

    def test_login_and_logout(self):
        got = _run(
            SIGNUP
            + "const cred = { workspace: 'team-1', keyword: 'correct horse battery', user: 'Binh' };\n"
            "out.wrong = (await h.call(env, 'POST', '/api/login', { ...cred, keyword: 'correct horse batterY' })).status;\n"
            "out.none = (await h.call(env, 'POST', '/api/login', { ...cred, workspace: 'nobody' })).status;\n"
            "const r = await h.call(env, 'POST', '/api/login', cred);\n"
            "out.ok = r.status; out.user = r.body.user;\n"
            "out.me = (await h.call(env, 'GET', '/api/me', null, r.body.token)).body;\n"
            "out.noAuth = (await h.call(env, 'GET', '/api/campaigns')).status;\n"
            "out.badAuth = (await h.call(env, 'GET', '/api/campaigns', null, 'x'.repeat(43))).status;\n"
            "out.logout = (await h.call(env, 'POST', '/api/logout', {}, r.body.token)).status;\n"
            "out.after = (await h.call(env, 'GET', '/api/me', null, r.body.token)).status;\n"
            "out.first = (await h.call(env, 'GET', '/api/me', null, tok)).status;\n"
            "env.DB.raw.prepare('UPDATE tokens SET expires_at = 1').run();\n"
            "out.expired = (await h.call(env, 'GET', '/api/me', null, tok)).status;\n"
        )
        self.assertEqual(got["wrong"], 401)
        self.assertEqual(got["none"], 401, "the same answer: no hint which names exist")
        self.assertEqual(got["ok"], 200)
        self.assertEqual(got["me"]["workspace"], "team-1")
        self.assertEqual(got["me"]["user"], "Binh")
        self.assertEqual(got["noAuth"], 401)
        self.assertEqual(got["badAuth"], 401)
        self.assertEqual(got["logout"], 200)
        self.assertEqual(got["after"], 401, "logout deletes the token")
        self.assertEqual(got["first"], 200, "other logins stay")
        self.assertEqual(got["expired"], 401)

    def test_failed_logins_lock_out(self):
        got = _run(
            SIGNUP
            + "const bad = { workspace: 'team-1', keyword: 'not the keyword!', user: 'X' };\n"
            "const good = { workspace: 'team-1', keyword: 'correct horse battery', user: 'An' };\n"
            "const st = [];\n"
            "for (let i = 0; i < h.LIMITS.failIp + 1; i++) st.push((await h.call(env, 'POST', '/api/login', bad, null, '203.0.113.1')).status);\n"
            "out.ip = st;\n"
            "out.goodSameIp = (await h.call(env, 'POST', '/api/login', good, null, '203.0.113.1')).status;\n"
            "out.goodOtherIp = (await h.call(env, 'POST', '/api/login', good, null, '203.0.113.2')).status;\n"
            "out.retry = (await h.call(env, 'POST', '/api/login', bad, null, '203.0.113.1')).headers['retry-after'];\n"
            "h.LIMITS.failWorkspace = 3;\n"
            "for (let i = 0; i < 4; i++) await h.call(env, 'POST', '/api/login', bad, null, '192.0.2.' + (10 + i));\n"
            "out.ws = (await h.call(env, 'POST', '/api/login', good, null, '192.0.2.99')).status;\n"
            "env.DB.raw.prepare('UPDATE fails SET since = since - ?').run(h.LIMITS.failWindow);\n"
            "out.later = (await h.call(env, 'POST', '/api/login', good, null, '192.0.2.99')).status;\n"
        )
        self.assertEqual(got["ip"][:-1], [401] * 10)
        self.assertEqual(got["ip"][-1], 429, "the 11th try from one address waits")
        self.assertEqual(got["goodSameIp"], 429, "the lock holds for the right keyword too")
        self.assertEqual(got["goodOtherIp"], 200)
        self.assertTrue(int(got["retry"]) > 0)
        self.assertEqual(got["ws"], 429, "a spread guess against one workspace locks it")
        self.assertEqual(got["later"], 200, "the lock ends with the window")

    def test_rate_limit_and_cors(self):
        got = _run(
            "const env = h.makeEnv({ API_LIMIT: h.makeLimiter(3) });\n"
            "const st = [];\n"
            "for (let i = 0; i < 4; i++) st.push((await h.call(env, 'GET', '/api/health')).status);\n"
            "out.st = st;\n"
            "out.other = (await h.call(env, 'GET', '/api/health', null, null, '198.51.100.99')).status;\n"
            "const pre = await h.worker.fetch(new Request(h.BASE + '/api/login', { method: 'OPTIONS' }), env);\n"
            "out.pre = pre.status; out.allow = pre.headers.get('access-control-allow-headers');\n"
            "const a = h.makeEnv({ ASSETS: { fetch: async (r) => new Response('page:' + new URL(r.url).pathname) } });\n"
            "out.page = await (await h.worker.fetch(new Request(h.BASE + '/'), a)).text();\n"
            "out.noDb = (await h.call(h.makeEnv({ DB: undefined }), 'GET', '/api/me')).status;\n"
        )
        self.assertEqual(got["st"], [200, 200, 200, 429])
        self.assertEqual(got["other"], 200, "the limit is per address")
        self.assertEqual(got["pre"], 204)
        self.assertIn("Authorization", got["allow"])
        self.assertEqual(got["page"], "page:/", "the page is a static asset")
        self.assertEqual(got["noDb"], 503)

    def test_api_answers_only_on_its_hosts(self):
        got = _run(
            "const env = h.makeEnv({ API_HOSTS: 'cloud.test, other.test' });\n"
            "const at = async (u) => (await h.worker.fetch(new Request(u), env)).status;\n"
            "out.main = await at('https://cloud.test/api/health');\n"
            "out.second = await at('https://OTHER.test/api/health');\n"
            "out.dev = await at('https://x.y.workers.dev/api/health');\n"
            "out.devPre = (await h.worker.fetch(new Request('https://x.y.workers.dev/api/login', { method: 'OPTIONS' }), env)).status;\n"
            "const a = h.makeEnv({ API_HOSTS: 'cloud.test', ASSETS: { fetch: async () => new Response('page') } });\n"
            "out.page = (await h.worker.fetch(new Request('https://x.y.workers.dev/'), a)).status;\n"
        )
        self.assertEqual(got["main"], 200)
        self.assertEqual(got["second"], 200, "a list, case-insensitive")
        self.assertEqual(got["dev"], 403, "the workers.dev address cannot skip the zone firewall")
        self.assertEqual(got["devPre"], 403)
        self.assertEqual(got["page"], 200, "the page itself stays on every address")


@unittest.skipUnless(SQLITE, "node with node:sqlite is not installed")
class TestCampaigns(unittest.TestCase):
    def test_versions_and_conflicts(self):
        got = _run(
            SIGNUP
            + "const id = 'c0ffee00-1111-2222-3333-444455556666';\n"
            "const put = (data, base, t = tok) => h.call(env, 'PUT', '/api/campaigns/' + id, { data, base_version: base }, t);\n"
            "const a = await put(h.session('alpha', 2), 0);\n"
            "out.create = [a.status, a.body.version];\n"
            "const b = await put(h.session('alpha', 3), 1);\n"
            "out.update = [b.status, b.body.version];\n"
            "const c = await put(h.session('alpha', 9), 1);\n"
            "out.stale = [c.status, c.body.conflict, c.body.current.version, c.body.current.updated_by];\n"
            "out.dup = (await put(h.session('alpha', 1), 0)).status;\n"
            "out.same = (await h.call(env, 'GET', '/api/campaigns/' + id + '?have=2', null, tok)).body;\n"
            "const g = (await h.call(env, 'GET', '/api/campaigns/' + id, null, tok)).body;\n"
            "out.levels = g.data.levels.length; out.version = g.version;\n"
            "const l = (await h.call(env, 'GET', '/api/campaigns', null, tok)).body;\n"
            "out.list = l.campaigns.map((x) => [x.tank, x.levels, x.version, x.updated_by]);\n"
            "out.hasData = 'data' in l.campaigns[0];\n"
            "out.delStale = (await h.call(env, 'DELETE', '/api/campaigns/' + id + '?base_version=1', null, tok)).status;\n"
            "out.del = (await h.call(env, 'DELETE', '/api/campaigns/' + id + '?base_version=2', null, tok)).status;\n"
            "out.gone = (await h.call(env, 'GET', '/api/campaigns/' + id, null, tok)).status;\n"
            "out.listAfter = (await h.call(env, 'GET', '/api/campaigns', null, tok)).body.campaigns.length;\n"
            "out.kept = env.DB.raw.prepare('SELECT COUNT(*) AS n FROM campaigns').get().n;\n"
        )
        self.assertEqual(got["create"], [201, 1])
        self.assertEqual(got["update"], [200, 2])
        self.assertEqual(got["stale"], [409, True, 2, "An"], "a stale save overwrites nothing")
        self.assertEqual(got["dup"], 409)
        self.assertTrue(got["same"]["same"], "a poll with the current version gets no data")
        self.assertNotIn("data", got["same"])
        self.assertEqual(got["levels"], 3)
        self.assertEqual(got["version"], 2)
        self.assertEqual(got["list"], [["alpha", 3, 2, "An"]])
        self.assertFalse(got["hasData"], "the list holds no session data")
        self.assertEqual(got["delStale"], 409)
        self.assertEqual(got["del"], 200)
        self.assertEqual(got["gone"], 404)
        self.assertEqual(got["listAfter"], 0)
        self.assertEqual(got["kept"], 1, "a delete is soft: the row stays")

    def test_deleted_stays_deleted_and_one_read(self):
        got = _run(
            SIGNUP
            + "const id = 'dddddddd-0000-0000-0000-000000000001';\n"
            "const put = (data, base) => h.call(env, 'PUT', '/api/campaigns/' + id, { data, base_version: base }, tok);\n"
            "await put(h.session('alpha', 2), 0);\n"
            "out.del = (await h.call(env, 'DELETE', '/api/campaigns/' + id + '?base_version=1', null, tok)).status;\n"
            "const r = await put(h.session('alpha', 3), 2);\n"
            "out.put = [r.status, r.body.current && r.body.current.deleted_at != null];\n"
            "out.get = (await h.call(env, 'GET', '/api/campaigns/' + id, null, tok)).status;\n"
            "out.badEscape = (await h.call(env, 'GET', '/api/campaigns/%E0%A4%A', null, tok)).status;\n"
            "const id2 = 'dddddddd-0000-0000-0000-000000000002';\n"
            "await h.call(env, 'PUT', '/api/campaigns/' + id2, { data: h.session('beta', 2), base_version: 0 }, tok);\n"
            "out.badHave = Object.keys((await h.call(env, 'GET', '/api/campaigns/' + id2 + '?have=x', null, tok)).body).includes('data');\n"
        )
        self.assertEqual(got["del"], 200)
        self.assertEqual(got["put"], [409, True], "a save never brings a deleted campaign back")
        self.assertEqual(got["get"], 404)
        self.assertEqual(got["badEscape"], 400, "a bad %-escape is a bad id, not a server error")
        self.assertTrue(got["badHave"], "a bad have= gets the data")

    def test_workspaces_are_separate(self):
        got = _run(
            SIGNUP
            + "const t2 = (await h.call(env, 'POST', '/api/workspaces', "
            "{ workspace: 'team-2', keyword: 'another long keyword', user: 'Chi', signup_code: 'test-signup-code' })).body.token;\n"
            "const id = 'aaaaaaaa-0000-0000-0000-000000000001';\n"
            "await h.call(env, 'PUT', '/api/campaigns/' + id, { data: h.session('mine'), base_version: 0 }, tok);\n"
            "out.read = (await h.call(env, 'GET', '/api/campaigns/' + id, null, t2)).status;\n"
            "out.write = (await h.call(env, 'PUT', '/api/campaigns/' + id, { data: h.session('theirs'), base_version: 1 }, t2)).status;\n"
            "out.own = (await h.call(env, 'PUT', '/api/campaigns/' + id, { data: h.session('theirs'), base_version: 0 }, t2)).status;\n"
            "out.list = (await h.call(env, 'GET', '/api/campaigns', null, t2)).body.campaigns.map((x) => x.tank);\n"
            "out.mine = (await h.call(env, 'GET', '/api/campaigns/' + id, null, tok)).body.data.config.tank;\n"
        )
        self.assertEqual(got["read"], 404)
        self.assertEqual(got["write"], 409, "an update never reaches another workspace's row")
        self.assertEqual(got["own"], 201, "the same id is a new campaign in the other workspace")
        self.assertEqual(got["list"], ["theirs"])
        self.assertEqual(got["mine"], "mine")

    def test_input_limits(self):
        got = _run(
            SIGNUP
            + "const id = 'bbbbbbbb-0000-0000-0000-000000000001';\n"
            "out.badId = (await h.call(env, 'PUT', '/api/campaigns/x', { data: h.session(), base_version: 0 }, tok)).status;\n"
            "out.notSession = (await h.call(env, 'PUT', '/api/campaigns/' + id, { data: { hello: 1 }, base_version: 0 }, tok)).status;\n"
            "out.badBase = (await h.call(env, 'PUT', '/api/campaigns/' + id, { data: h.session(), base_version: -1 }, tok)).status;\n"
            "const big = h.session(); big.pad = 'x'.repeat(h.LIMITS.body + 1);\n"
            "out.big = (await h.call(env, 'PUT', '/api/campaigns/' + id, { data: big, base_version: 0 }, tok)).status;\n"
            "const tr = { kind: 'transfer', out: h.session('a'), in: h.session('b', 4) };\n"
            "await h.call(env, 'PUT', '/api/campaigns/' + id, { data: tr, base_version: 0 }, tok);\n"
            "out.transfer = (await h.call(env, 'GET', '/api/campaigns', null, tok)).body.campaigns[0].tank;\n"
            "h.LIMITS.campaigns = 1;\n"
            "out.full = (await h.call(env, 'PUT', '/api/campaigns/cccccccc-0000-0000-0000-000000000001', { data: h.session(), base_version: 0 }, tok)).status;\n"
            "const ctl = await h.call(env, 'POST', '/api/login', { workspace: 'team-1', keyword: 'correct horse battery', user: 'a\\u0000b\\nc' });\n"
            "out.user = ctl.body.user;\n"
            "out.route = (await h.call(env, 'GET', '/api/nothing', null, tok)).status;\n"
        )
        self.assertEqual(got["badId"], 400)
        self.assertEqual(got["notSession"], 400)
        self.assertEqual(got["badBase"], 400)
        self.assertEqual(got["big"], 413)
        self.assertEqual(got["transfer"], "a → b")
        self.assertEqual(got["full"], 403)
        self.assertEqual(got["user"], "abc", "no control characters in a name")
        self.assertEqual(got["route"], 404)


@unittest.skipUnless(SQLITE, "node with node:sqlite is not installed")
class TestGzipBody(unittest.TestCase):
    def test_worker_reads_a_gzip_body_within_the_limit(self):
        got = _run(
            SIGNUP
            + "const zlib = require('node:zlib');\n"
            "const put = async (bytes) => { const r = await h.fetchFor(env)(h.BASE + '/api/campaigns/camp-0001', { method: 'PUT', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok }, body: bytes }); return [r.status, await r.json()]; };\n"
            "const body = JSON.stringify({ data: h.session('alpha', 3), base_version: 0 });\n"
            "out.gz = await put(zlib.gzipSync(body));\n"
            "out.stored = (await h.call(env, 'GET', '/api/campaigns/camp-0001', null, tok)).body.data.levels.length;\n"
            # a small body that unpacks past the limit
            "const bomb = zlib.gzipSync('{\"data\":\"' + ' '.repeat(h.LIMITS.body + 10) + '\"}');\n"
            "out.bombSize = bomb.length;\n"
            "out.bomb = (await put(bomb))[0];\n"
            "out.bad = (await put(new Uint8Array([0x1f, 0x8b, 8, 0, 1, 2, 3])))[0];\n"
            "out.plain = (await put(JSON.stringify({ data: h.session('alpha', 4), base_version: 1 })))[0];\n"
        )
        self.assertEqual(got["gz"][0], 201)
        self.assertEqual(got["stored"], 3, "the gzip body is the campaign")
        self.assertLess(got["bombSize"], 10_000)
        self.assertEqual(got["bomb"], 413, "the limit holds for the unpacked size")
        self.assertEqual(got["bad"], 400)
        self.assertEqual(got["plain"], 200, "a plain JSON body still works")


@unittest.skipUnless(SQLITE, "node with node:sqlite is not installed")
class TestClient(unittest.TestCase):
    PRELUDE = (
        "const env = h.makeEnv();\n"
        "const mem = () => { const m = new Map(); return { getItem: (k) => m.has(k) ? m.get(k) : null, setItem: (k, v) => m.set(k, v), removeItem: (k) => m.delete(k) }; };\n"
        "let online = true;\n"
        "const net = (ip) => { const f = h.fetchFor(env, ip); return (u, i) => online ? f(u, i) : Promise.reject(new TypeError('offline')); };\n"
        "const A = new cloud.Client({ storage: mem(), fetch: net('10.0.0.1'), origin: h.BASE });\n"
        "const B = new cloud.Client({ storage: mem(), fetch: net('10.0.0.2'), origin: h.BASE });\n"
        "await A.signup('', 'team-1', 'correct horse battery', 'An', 'test-signup-code');\n"
        "await B.login('', 'team-1', 'correct horse battery', 'Binh');\n"
    )

    def test_offline_first_sync(self):
        got = _run(
            self.PRELUDE
            + "let data = h.session('alpha', 1);\n"
            "A.linkNew();\n"
            "out.first = (await A.sync(() => data)).state;\n"
            "out.v1 = A.link().version;\n"
            "online = false;\n"
            "data = h.session('alpha', 2); A.markDirty();\n"
            "data = h.session('alpha', 3); A.markDirty();\n"
            "out.off = (await A.sync(() => data)).state;\n"
            "out.dirtyOff = A.dirty();\n"
            "online = true;\n"
            "out.back = (await A.sync(() => data)).state;\n"
            "out.dirtyOn = A.dirty(); out.v2 = A.link().version;\n"
            "out.idle = (await A.sync(() => data)).state;\n"
            "const l = await B.list();\n"
            "out.seen = l.campaigns.map((c) => [c.tank, c.levels, c.updated_by]);\n"
            "out.loginBad = await A.login('', 'team-1', 'wrong keyword!!', 'An').then(() => 'ok', (e) => e.status);\n"
            "out.stillIn = A.loggedIn();\n"
            "out.badBase = await A.login('ftp://x', 'team-1', 'k', 'An').then(() => 'ok', (e) => e.message);\n"
            "const file = new cloud.Client({ storage: mem(), fetch: net('10.0.0.3'), origin: '' });\n"
            "out.file = await file.list().then(() => 'ok', (e) => e.message);\n"
        )
        self.assertEqual(got["first"], "saved")
        self.assertEqual(got["v1"], 1)
        self.assertEqual(got["off"], "offline")
        self.assertTrue(got["dirtyOff"], "offline changes wait in the browser")
        self.assertEqual(got["back"], "saved")
        self.assertFalse(got["dirtyOn"])
        self.assertEqual(got["v2"], 2, "two offline edits upload as one save")
        self.assertEqual(got["idle"], "idle")
        self.assertEqual(got["seen"], [["alpha", 3, "An"]])
        self.assertEqual(got["loginBad"], 401)
        self.assertTrue(got["stillIn"], "a failed second login keeps the first one")
        self.assertIn("https://", got["badBase"])
        self.assertIn("server address", got["file"], "a local file needs an address")

    def test_upload_goes_gzipped_and_small_ones_keepalive(self):
        got = _run(
            self.PRELUDE
            + "const seen = [];\n"
            "const spy = (ip) => { const f = net(ip); return (u, i) => { if (i && i.method === 'PUT') seen.push({ gz: i.body instanceof Uint8Array && i.body[0] === 0x1f && i.body[1] === 0x8b, size: i.body.length, keep: !!i.keepalive }); return f(u, i); }; };\n"
            "const C = new cloud.Client({ storage: mem(), fetch: spy('10.0.0.5'), origin: h.BASE });\n"
            "await C.login('', 'team-1', 'correct horse battery', 'Cam');\n"
            "let data = h.session('alpha', 40); C.linkNew();\n"
            "out.first = (await C.sync(() => data)).state;\n"
            "data = h.session('alpha', 41); C.markDirty();\n"
            "out.hidden = (await C.sync(() => data, { keepalive: true })).state;\n"
            # a body past the keepalive limit even packed: random text does not pack
            "const big = h.session('alpha', 42); big.config.note = Array.from({ length: 150000 }, () => Math.random().toString(36)[2]).join('');\n"
            "C.markDirty(); out.big = (await C.sync(() => big, { keepalive: true })).state;\n"
            "out.plain = JSON.stringify(h.session('alpha', 40)).length;\n"
            "out.seen = seen;\n"
            "out.cloud = (await B.fetchCampaign(C.link().id)).data.levels.length;\n"
        )
        self.assertEqual([got["first"], got["hidden"], got["big"]], ["saved"] * 3)
        self.assertTrue(all(x["gz"] for x in got["seen"]), "every upload goes gzipped")
        self.assertLess(got["seen"][0]["size"], got["plain"] / 3, "packed to well under a third")
        self.assertEqual([x["keep"] for x in got["seen"]], [False, True, False],
                         "keepalive only when asked, and only for a body within its limit")
        self.assertEqual(got["cloud"], 42)

    def test_two_users_one_campaign(self):
        got = _run(
            self.PRELUDE
            + "A.linkNew();\n"
            "await A.sync(() => h.session('alpha', 1));\n"
            "const c = await B.fetchCampaign(A.link().id); B.linkTo(c);\n"
            "out.pollNone = await B.poll();\n"
            "A.markDirty(); await A.sync(() => h.session('alpha', 2));\n"
            "const p = await B.poll();\n"
            "out.follow = [p.data.levels.length, p.updated_by, B.link().version];\n"
            "A.markDirty(); await A.sync(() => h.session('alpha', 3));\n"
            "B.markDirty();\n"
            "out.pollDirty = await B.poll();\n"
            "const r = await B.sync(() => h.session('alpha-b', 3));\n"
            "out.conflict = [r.state, B.link().conflict.version, B.link().conflict.updated_by];\n"
            "out.retry = (await B.sync(() => h.session('alpha-b', 3))).state;\n"
            "const took = await B.takeCloud();\n"
            "out.took = [took.data.levels.length, B.dirty(), !!B.link().conflict];\n"
            "B.markDirty();\n"
            "const r2 = await B.sync(() => h.session('alpha-b', 4));\n"
            "A.markDirty();\n"
            "const r3 = await A.sync(() => h.session('alpha', 4));\n"
            "out.aConflict = r3.state;\n"
            "const old = A.link().id;\n"
            "A.fork();\n"
            "out.fork = [(await A.sync(() => h.session('alpha', 4))).state, A.link().id !== old];\n"
            "out.list = (await A.list()).campaigns.map((x) => x.tank).sort();\n"
        )
        self.assertIsNone(got["pollNone"], "nothing new: no data")
        self.assertEqual(got["follow"], [2, "An", 2], "a clean link follows the other user")
        self.assertIsNone(got["pollDirty"], "a poll never replaces local changes")
        self.assertEqual(got["conflict"], ["conflict", 3, "An"])
        self.assertEqual(got["retry"], "conflict", "a conflict waits for the user's choice")
        self.assertEqual(got["took"], [3, False, False])
        self.assertEqual(got["aConflict"], "conflict")
        self.assertEqual(got["fork"], ["saved", True], "keep mine: a new campaign")
        self.assertEqual(got["list"], ["alpha", "alpha-b"])

    def test_lost_answer_is_not_a_conflict(self):
        got = _run(
            self.PRELUDE
            + "let lose = false;\n"
            "const f = h.fetchFor(env, '10.0.0.1');\n"
            "const C = new cloud.Client({ storage: mem(), origin: h.BASE, fetch: async (u, i) => {\n"
            "  const r = await f(u, i);\n"
            "  if (lose && i.method === 'PUT') { lose = false; throw new TypeError('lost'); }\n"
            "  return r; } });\n"
            "await C.login('', 'team-1', 'correct horse battery', 'Chi');\n"
            "C.linkNew();\n"
            "lose = true;\n"
            "out.first = (await C.sync(() => h.session('lost', 1))).state;\n"
            "out.again = (await C.sync(() => h.session('lost', 1))).state;\n"
            "out.v1 = [C.link().version, C.dirty(), !!C.link().conflict];\n"
            "lose = true; C.markDirty();\n"
            "out.second = (await C.sync(() => h.session('lost', 2))).state;\n"
            "C.markDirty();\n"
            "out.third = (await C.sync(() => h.session('lost', 3))).state;\n"
            "out.v3 = [C.link().version, C.dirty(), !!C.link().conflict];\n"
            "out.server = (await C.fetchCampaign(C.link().id)).data.levels.length;\n"
            "out.count = (await C.list()).campaigns.length;\n"
        )
        self.assertEqual(got["first"], "offline", "the answer was lost: the page cannot know")
        self.assertEqual(got["again"], "saved", "the retry finds its own save")
        self.assertEqual(got["v1"], [1, False, False])
        self.assertEqual(got["second"], "offline")
        self.assertEqual(got["third"], "saved", "a lost save and a new edit: no conflict with yourself")
        self.assertEqual(got["v3"], [3, False, False])
        self.assertEqual(got["server"], 3)
        self.assertEqual(got["count"], 1, "no duplicate campaign")

    def test_closed_copy_uploads_later(self):
        got = _run(
            self.PRELUDE
            + "const done = []; A.onClosed = (e) => done.push([e.state, e.link.rev === e.link.synced]);\n"
            "A.linkNew(); await A.sync(() => h.session('alpha', 1));\n"
            "const id = A.link().id;\n"
            "online = false;\n"
            "A.markDirty();\n"
            "out.off = (await A.sync(() => h.session('alpha', 2))).state;\n"
            "const closed = A.detach(h.session('alpha', 2));\n"
            "out.closed = [A.link(), A.outbox().length, A.state()];\n"
            "online = true;\n"
            "out.drain = (await A.sync(() => null)).state;\n"
            "out.done = done; out.box = A.outbox().length;\n"
            "out.server = (await B.fetchCampaign(id)).data.levels.length;\n"
            # a closed copy opened again before its upload: the open link sends it
            "online = false; const l2 = A.attach(closed); A.markDirty();\n"
            "await A.sync(() => h.session('alpha', 3));\n"
            "const c3 = A.detach(h.session('alpha', 3));\n"
            "const back = A.attach(c3);\n"
            "out.reopen = [A.outbox().length, back.copy !== c3.copy, A.dirty()];\n"
            "online = true;\n"
            "out.after = (await A.sync(() => h.session('alpha', 3))).state;\n"
            "out.server2 = (await B.fetchCampaign(id)).data.levels.length;\n"
        )
        self.assertEqual(got["off"], "offline")
        self.assertEqual(got["closed"], [None, 1, "none"], "closed: the changes wait in the outbox")
        self.assertEqual(got["drain"], "saved")
        self.assertEqual(got["done"], [["saved", True]], "the archive hears the new link")
        self.assertEqual(got["box"], 0)
        self.assertEqual(got["server"], 2, "the change made before the close is in the cloud")
        self.assertEqual(got["reopen"], [0, True, True], "opened again: it leaves the outbox, with a new tag")
        self.assertEqual(got["after"], "saved")
        self.assertEqual(got["server2"], 3)

    def test_other_workspace_and_deleted(self):
        got = _run(
            self.PRELUDE
            + "A.linkNew(); await A.sync(() => h.session('alpha', 1));\n"
            "const id = A.link().id;\n"
            "const c = await B.fetchCampaign(id); B.linkTo(c);\n"
            "await A.remove(id, A.link().version);\n"
            "out.poll = await B.poll(() => { throw new Error('no apply for a deleted campaign'); });\n"
            "out.bState = B.state();\n"
            "B.markDirty();\n"
            "out.bSync = (await B.sync(() => h.session('alpha', 2))).state;\n"
            "B.fork();\n"
            "out.bFork = (await B.sync(() => h.session('alpha', 2))).state;\n"
            # A logs in to another workspace: the open link belongs to team-1
            "const C = new cloud.Client({ storage: mem(), fetch: net('10.0.0.3'), origin: h.BASE });\n"
            "await C.login('', 'team-1', 'correct horse battery', 'Chi');\n"
            "C.linkNew(); await C.sync(() => h.session('gamma', 1));\n"
            "await C.logout();\n"
            "await C.signup('', 'team-2', 'another long keyword', 'Chi', 'test-signup-code');\n"
            "out.cState = C.state(); C.markDirty();\n"
            "out.cSync = (await C.sync(() => h.session('gamma', 2))).state;\n"
            "out.team2 = (await C.list()).campaigns.length;\n"
            "out.cPoll = await C.poll();\n"
        )
        self.assertEqual(got["poll"], {"gone": True}, "a deleted campaign is noticed, nothing is applied")
        self.assertEqual(got["bState"], "gone")
        self.assertEqual(got["bSync"], "gone", "no conflict and no upload for a deleted campaign")
        self.assertEqual(got["bFork"], "saved", "it can go up as a new campaign")
        self.assertEqual(got["cState"], "elsewhere")
        self.assertEqual(got["cSync"], "elsewhere", "a campaign of team-1 never goes to team-2")
        self.assertEqual(got["team2"], 0)
        self.assertIsNone(got["cPoll"])

    def test_poll_apply_fails_keeps_the_link(self):
        got = _run(
            self.PRELUDE
            + "A.linkNew(); await A.sync(() => h.session('alpha', 1));\n"
            "B.linkTo(await B.fetchCampaign(A.link().id));\n"
            "A.markDirty(); await A.sync(() => h.session('alpha', 2));\n"
            "out.err = await B.poll(() => { throw new Error('bad data'); }).then(() => 'ok', (e) => e.message);\n"
            "out.v = B.link().version;\n"
            "out.again = (await B.poll((c) => {})).version;\n"
        )
        self.assertEqual(got["err"], "bad data")
        self.assertEqual(got["v"], 1, "a failed apply does not move the link")
        self.assertEqual(got["again"], 2)

    def test_expired_login_keeps_the_changes(self):
        got = _run(
            self.PRELUDE
            + "A.linkNew(); await A.sync(() => h.session('alpha', 1));\n"
            "env.DB.raw.prepare('DELETE FROM tokens').run();\n"
            "A.markDirty();\n"
            "const r = await A.sync(() => h.session('alpha', 2));\n"
            "out.state = r.state; out.loggedIn = A.loggedIn(); out.dirty = A.dirty();\n"
            "out.kept = [A.auth().workspace, A.auth().user];\n"
            "await A.login('', 'team-1', 'correct horse battery', 'An');\n"
            "out.after = (await A.sync(() => h.session('alpha', 2))).state;\n"
        )
        self.assertEqual(got["state"], "login")
        self.assertFalse(got["loggedIn"])
        self.assertTrue(got["dirty"])
        self.assertEqual(got["kept"], ["team-1", "An"], "the form keeps the workspace and the name")
        self.assertEqual(got["after"], "saved")


@unittest.skipUnless(SQLITE, "node with node:sqlite is not installed")
class TestPage(unittest.TestCase):
    def _devices(self):
        stub = (HERE / "page_stub.js").as_posix()
        page = (ROOT / "site" / "page.html").as_posix()
        core = (ROOT / "site" / "site_core.js").as_posix()
        return (
            f"const stub = require({json.dumps(stub)});\n"
            "const env = h.makeEnv();\n"
            "await h.call(env, 'POST', '/api/workspaces', { workspace: 'team-1', keyword: 'correct horse battery', user: 'An', signup_code: 'test-signup-code' });\n"
            "const net = { on: true };\n"
            # dlg.prompt: the answer of the next prompt() (Edit pour, override)
            "const dlg = { prompt: null };\n"
            "const dev = (ip) => { const f = h.fetchFor(env, ip); return { fetch: (u, i) => net.on ? f(u, i) : Promise.reject(new TypeError('offline')), location: { protocol: 'https:', origin: h.BASE }, prompt: () => dlg.prompt }; };\n"
            "const until = async (ok) => { for (let i = 0; i < 300 && !ok(); i++) await new Promise((r) => setTimeout(r, 10)); return ok(); };\n"
            "const link = (st) => JSON.parse(st.get('calib-site:link') || 'null');\n"
            "const box = (st) => JSON.parse(st.get('calib-site:outbox') || '[]');\n"
            "const arch = (st) => JSON.parse(st.get('calib-site:archive') || '[]');\n"
            "const cloudData = () => JSON.parse(env.DB.raw.prepare('SELECT data FROM campaigns').get().data);\n"
            f"const boot = (st, ip) => stub.boot({json.dumps(page)}, {json.dumps(core)}, st, dev(ip));\n"
            "const login = async (e, user) => { e('c-ws').value = 'team-1'; e('c-key').value = 'correct horse battery'; e('c-user').value = user; e('c-login').click(); await until(() => !e('c-in')._classes.has('hidden')); };\n"
            "const settled = (st) => until(() => link(st) && link(st).version >= 1 && link(st).rev === link(st).synced);\n"
            "const start = (e) => { e('s-tank').value = 'alpha'; e('s-D').value = '2400'; e('s-L').value = '5000'; e('s-dip').value = '100'; e('s-step').value = '?'; e('s-go').click(); e('d-val').value = '100'; e('d-go').click(); };\n"
            "const openCloud = (e, id) => e('c-list')._listeners.click[0]({ target: { closest: () => ({ dataset: { cid: id, act: 'open' } }) } });\n"
            "const openArchive = (e, i) => e('f-archive')._listeners.click[0]({ target: { closest: () => ({ dataset: { i: String(i), act: 'open' } }) } });\n"
        )

    def _team(self):
        """Two devices on one campaign: A (An) counts the cans, B (Binh) dips.

        Both hold version 1: row 1 is the start level, decided.  A's can size
        is 200 L.  note(e, row, text) saves a note from the Log table;
        sync(e, st) waits until the upload ends (saved or conflict).
        """
        return (
            self._devices()
            + "const s1 = new Map(), s2 = new Map(); const pa = boot(s1, '10.0.0.1'), pb = boot(s2, '10.0.0.2'), a = pa.el, b = pb.el;\n"
            "await login(a, 'An'); start(a); a('t-unit').value = '200'; a('c-sync').click(); await settled(s1);\n"
            "await login(b, 'Binh'); const id = link(s1).id;\n"
            "openCloud(b, id); await until(() => link(s2) && link(s2).id === id);\n"
            "const note = (e, row, text) => { const click = (sel, data) => e('log-table')._listeners.click[0]({ target: { closest: (s) => (s === sel ? { dataset: data } : null) } });\n"
            "  click('button[data-note-edit]', { noteEdit: String(row) }); e('note-edit').value = text; click('button[data-note-save]', { noteSave: String(row) }); };\n"
            "const sync = async (e, st) => { e('c-sync').click(); await until(() => link(st).rev === link(st).synced || link(st).conflict); await new Promise((r) => setTimeout(r, 20)); };\n"
            "const follow = async (e, st, v) => { e('c-sync').click(); await until(() => link(st).version >= v); };\n"
            "const active = (st) => JSON.parse(st.get('calib-site:active'));\n"
        )

    def test_case_a_dipper_writes_while_the_counter_counts(self):
        got = _run(
            self._team()
            # A counts a can (not sent yet); B writes a note and saves first
            + "a('t-plus').click();\n"
            "note(b, 1, 'datum plate wet'); await sync(b, s2);\n"
            "await sync(a, s1);\n"
            "out.hdr = a('hdr-cloud').textContent;\n"
            "out.cloud = [cloudData().levels[0].note, cloudData().batch];\n"
        )
        self.assertEqual(got["hdr"], "cloud: conflict")
        self.assertEqual(got["cloud"], ["datum plate wet", None], "the cloud keeps B's note, not A's can")

    def test_case_b_edit_pour_against_the_dip_of_the_same_level(self):
        got = _run(
            self._team()
            # A closes a batch of 2 cans; B follows: row 2 waits for its dip
            + "a('t-plus').click(); a('t-plus').click(); a('p-go').click(); await sync(a, s1);\n"
            "await follow(b, s2, link(s1).version);\n"
            # A recounts (Edit pour) while B dips the same row
            "dlg.prompt = '600'; a('a-edit').click(); dlg.prompt = null;\n"
            "b('d-val').value = '130'; b('d-go').click(); await sync(b, s2);\n"
            "await sync(a, s1);\n"
            "out.hdr = a('hdr-cloud').textContent;\n"
            "out.cloud = [cloudData().levels[1].step.text, cloudData().levels[1].dips];\n"
        )
        self.assertEqual(got["hdr"], "cloud: conflict", "both changed row 2: no safe merge")
        self.assertEqual(got["cloud"], ["400", [130]])

    def test_case_c_timers_form_without_a_change(self):
        got = _run(
            self._team()
            # A presses Save timers and device with nothing changed; B writes a note first
            + "const rev = link(s1).rev;\n"
            "a('tm-sound').checked = false; a('tm-save').click();\n"
            "out.same = [link(s1).rev === rev, JSON.parse(s1.get('calib-site:prefs')).sound];\n"
            "note(b, 1, 'datum plate wet'); await sync(b, s2);\n"
            "await follow(a, s1, link(s2).version);\n"
            "out.hdr = a('hdr-cloud').textContent;\n"
            "out.followed = active(s1).levels[0].note;\n"
            # a real change of the campaign's timers is a cloud change
            "a('tm-settle').value = '6:00'; a('tm-save').click(); await sync(a, s1);\n"
            "out.settle = [link(s1).rev > rev, cloudData().config.settleSeconds];\n"
        )
        self.assertEqual(got["same"], [True, False], "a device setting stays on the device: no cloud change")
        self.assertEqual(got["hdr"], "cloud: saved", "no conflict")
        self.assertEqual(got["followed"], "datum plate wet")
        self.assertEqual(got["settle"], [True, 360])

    def test_case_d_write_on_a_stale_copy(self):
        got = _run(
            self._team()
            # A counts a can and saves; B has not seen it, and writes a note
            + "a('t-plus').click(); await sync(a, s1);\n"
            "note(b, 1, 'datum plate wet'); await sync(b, s2);\n"
            "out.hdr = b('hdr-cloud').textContent;\n"
            "out.cloud = [cloudData().levels[0].note, cloudData().batch.cans.length];\n"
        )
        self.assertEqual(got["hdr"], "cloud: conflict")
        self.assertEqual(got["cloud"], ["", 1], "the cloud keeps A's can, not B's note")

    def test_fast_follow_after_a_new_version(self):
        got = _run(
            self._devices()
            # B's page keeps its interval timers and runs on a clock the test moves
            + "let skew = 0; const RD = Date;\n"
            "class FD extends RD { constructor(...x) { if (x.length) super(...x); else super(RD.now() + skew); } static now() { return RD.now() + skew; } }\n"
            "const iv = [];\n"
            "const s1 = new Map(), s2 = new Map(); const a = boot(s1, '10.0.0.1').el;\n"
            f"const pb = stub.boot({json.dumps((ROOT / 'site' / 'page.html').as_posix())}, {json.dumps((ROOT / 'site' / 'site_core.js').as_posix())}, s2,\n"
            "  Object.assign(dev('10.0.0.2'), { Date: FD, setInterval: (fn, ms) => { iv.push({ fn, ms }); return iv.length; } })), b = pb.el;\n"
            "out.timers = iv.map((x) => x.ms);\n"
            "const fast = () => iv.find((x) => x.ms === 3000).fn(), slow = () => iv.find((x) => x.ms === 10000).fn();\n"
            "await login(a, 'An'); start(a); a('c-sync').click(); await settled(s1);\n"
            "await login(b, 'Binh'); const id = link(s1).id;\n"
            "openCloud(b, id); await until(() => link(s2) && link(s2).id === id);\n"
            "const dipA = async (v) => { a('d-val').value = String(v); a('d-go').click(); a('c-sync').click(); await settled(s1); };\n"
            "const seen = () => link(s2).version;\n"
            # nothing new came in yet: the 3 s timer does not ask
            "await dipA(101); fast(); await new Promise((r) => setTimeout(r, 50));\n"
            "out.quiet = seen() < link(s1).version;\n"
            "slow(); await until(() => seen() === link(s1).version);\n"
            # a new version came in: now every 3 s
            "await dipA(102); fast(); out.fast = await until(() => seen() === link(s1).version);\n"
            # 2 minutes later: back to 10 s
            "skew = 121000;\n"
            "await dipA(103); fast(); await new Promise((r) => setTimeout(r, 50));\n"
            "out.after = seen() < link(s1).version;\n"
        )
        self.assertIn(3000, got["timers"])
        self.assertIn(10000, got["timers"])
        self.assertTrue(got["quiet"], "no new version yet: the 3 s timer does not ask")
        self.assertTrue(got["fast"], "after a new version: the 3 s timer asks")
        self.assertTrue(got["after"], "after 2 minutes: the 10 s timer only")

    def test_hidden_page_uploads_at_once(self):
        page = (ROOT / "site" / "page.html").as_posix()
        core = (ROOT / "site" / "site_core.js").as_posix()
        got = _run(
            self._devices()
            + "const s1 = new Map(), d = dev('10.0.0.1'), f0 = d.fetch, puts = [];\n"
            "d.fetch = (u, i) => { if (i && i.method === 'PUT') puts.push(!!i.keepalive); return f0(u, i); };\n"
            f"const p = stub.boot({json.dumps(page)}, {json.dumps(core)}, s1, d), a = p.el;\n"
            "await login(a, 'An'); start(a); a('c-sync').click(); await settled(s1);\n"
            "const v = link(s1).version; puts.length = 0;\n"
            # a new dip: the 1.5 s upload timer is a stub that never fires here
            "a('d-val').value = '101'; a('d-go').click();\n"
            "out.dirty = link(s1).rev > link(s1).synced;\n"
            "p.document.hidden = true; p.document.fire('visibilitychange');\n"
            "out.uploaded = await until(() => link(s1).version === v + 1 && link(s1).rev === link(s1).synced);\n"
            "out.puts = puts;\n"
            "out.cloudDips = cloudData().levels[0].dips;\n"
        )
        self.assertTrue(got["dirty"])
        self.assertTrue(got["uploaded"], "out of view: the change uploads now, not at the next open")
        self.assertEqual(got["puts"], [True], "one upload, with keepalive")
        self.assertEqual(got["cloudDips"], [100, 100, 101], "the start reading twice, then the new dip")

    def test_take_cloud_then_reopen_never_overwrites(self):
        got = _run(
            self._devices()
            + "const s1 = new Map(), s2 = new Map(); const a = boot(s1, '10.0.0.1').el, b = boot(s2, '10.0.0.2').el;\n"
            "await login(a, 'An'); start(a); a('c-sync').click(); await settled(s1);\n"
            "await login(b, 'Binh'); const id = link(s1).id;\n"
            "openCloud(b, id); await until(() => link(s2) && link(s2).id === id);\n"
            # both write: A first, then B gets the conflict
            "a('d-val').value = '120'; a('d-go').click(); a('c-sync').click(); await settled(s1);\n"
            "b('d-val').value = '777'; b('d-go').click(); b('c-sync').click();\n"
            "await until(() => link(s2).conflict);\n"
            "out.conflictShown = !b('c-conflict')._classes.has('hidden');\n"
            "const v = link(s1).version, before = JSON.stringify(cloudData());\n"
            "b('c-take').click();\n"
            "await until(() => !link(s2).conflict);\n"
            "out.took = [link(s2).version === v, JSON.parse(s2.get('calib-site:active')).levels[0].dips];\n"
            "out.archived = [arch(s2)[0].session.levels[0].dips, !!arch(s2)[0].cloud.conflict];\n"
            # open the archived copy again, edit, sync: still a conflict, the cloud stays
            "openArchive(b, 0);\n"
            "out.reopened = [b('hdr-cloud').textContent, !b('c-conflict')._classes.has('hidden')];\n"
            "b('d-val').value = '778'; b('d-go').click(); b('c-sync').click();\n"
            "await new Promise((r) => setTimeout(r, 50));\n"
            "out.cloudSame = JSON.stringify(cloudData()) === before;\n"
        )
        self.assertTrue(got["conflictShown"])
        self.assertTrue(got["took"][0], "the cloud copy is open")
        self.assertEqual(got["archived"][1], True, "my copy keeps its conflicted link in the archive")
        self.assertEqual(got["reopened"], ["cloud: conflict", True], "opened again: the same choice")
        self.assertTrue(got["cloudSame"], "the archived copy never overwrites the cloud copy")

    def test_close_while_offline_uploads_later(self):
        got = _run(
            self._devices()
            + "const s1 = new Map(); const a = boot(s1, '10.0.0.1').el;\n"
            "await login(a, 'An'); start(a); a('c-sync').click(); await settled(s1);\n"
            "const id = link(s1).id;\n"
            "net.on = false;\n"
            "a('d-val').value = '120'; a('d-go').click();\n"
            "a('f-new').click();\n"
            "out.closed = [link(s1), box(s1).length, arch(s1)[0].cloud.id === id];\n"
            "out.note = a('c-state').textContent;\n"
            "net.on = true;\n"
            "a('c-sync').click();\n"
            "await until(() => box(s1).length === 0);\n"
            "out.server = cloudData().levels[0].dips;\n"
            "const al = arch(s1)[0].cloud;\n"
            "out.archLink = [al.rev === al.synced, al.version];\n"
        )
        self.assertEqual(got["closed"], [None, 1, True], "closed offline: the changes wait")
        self.assertIn("wait for upload: 1", got["note"])
        self.assertEqual(got["server"][-1], 120, "the change made before the close reached the cloud")
        self.assertEqual(got["archLink"], [True, 2], "the archive entry is in step: opened again, no conflict")

    def test_transfer_tank_switch_is_no_cloud_change(self):
        got = _run(
            self._devices()
            + "const s1 = new Map(); const p = boot(s1, '10.0.0.1'), a = p.el;\n"
            "await login(a, 'An');\n"
            "a('s-dir-transfer').click();\n"
            "a('s-tank').value = 'alpha'; a('s-D').value = '1800'; a('s-L').value = '3000';\n"
            "a('sB-tank').value = 'beta'; a('sB-D').value = '2480'; a('sB-L').value = '5200';\n"
            "a('s-dip').value = '1800'; a('sB-dip').value = '400'; a('s-unit').value = '200';\n"
            "a('s-go').click();\n"
            "a('d-val').value = '1800'; a('d-val-b').value = '400'; a('d-go-a').click(); a('d-go-b').click();\n"
            "a('c-sync').click(); await settled(s1);\n"
            "const rev = link(s1).rev;\n"
            "a('tiles')._listeners.click[0]({ target: { closest: () => ({ dataset: { tank: 'in' } }) } });\n"
            "out.active = JSON.parse(s1.get('calib-site:active')).active;\n"
            "out.same = link(s1).rev === rev;\n"
        )
        self.assertEqual(got["active"], "in", "the view is kept in this browser")
        self.assertTrue(got["same"], "switching the tank view is not a cloud change")

    def test_two_devices_follow_one_campaign(self):
        stub = (HERE / "page_stub.js").as_posix()
        page = (ROOT / "site" / "page.html").as_posix()
        core = (ROOT / "site" / "site_core.js").as_posix()
        got = _run(
            f"const stub = require({json.dumps(stub)});\n"
            "const env = h.makeEnv();\n"
            "await h.call(env, 'POST', '/api/workspaces', { workspace: 'team-1', keyword: 'correct horse battery', user: 'An', signup_code: 'test-signup-code' });\n"
            "let online = true;\n"
            "const dev = (ip) => { const f = h.fetchFor(env, ip); return { fetch: (u, i) => online ? f(u, i) : Promise.reject(new TypeError('offline')), location: { protocol: 'https:', origin: h.BASE } }; };\n"
            "const until = async (ok) => { for (let i = 0; i < 300 && !ok(); i++) await new Promise((r) => setTimeout(r, 10)); return ok(); };\n"
            "const link = (st) => JSON.parse(st.get('calib-site:link') || 'null');\n"
            "const levels = () => JSON.parse(env.DB.raw.prepare('SELECT data FROM campaigns').get().data).levels.length;\n"
            "const s1 = new Map(), s2 = new Map();\n"
            f"const p1 = stub.boot({json.dumps(page)}, {json.dumps(core)}, s1, dev('10.0.0.1')), a = p1.el;\n"
            "out.before = a('c-in')._classes.has('hidden');\n"
            "a('c-ws').value = 'team-1'; a('c-key').value = 'correct horse battery'; a('c-user').value = 'An';\n"
            "a('c-login').click();\n"
            "out.loggedIn = await until(() => !a('c-in')._classes.has('hidden'));\n"
            "out.keyCleared = a('c-key').value;\n"
            "a('s-tank').value = 'alpha'; a('s-D').value = '2400'; a('s-L').value = '5000'; a('s-dip').value = '100'; a('s-step').value = '?';\n"
            "a('s-go').click();\n"
            "a('d-val').value = '100'; a('d-go').click();\n"
            "out.linked = !!link(s1);\n"
            "a('c-sync').click();\n"
            "await until(() => link(s1).version >= 1 && link(s1).rev === link(s1).synced);\n"
            "out.hdr = a('hdr-cloud').textContent;\n"
            "out.server1 = levels();\n"
            "online = false;\n"
            "a('p-vol').value = '300'; a('p-go').click();\n"
            "a('c-sync').click();\n"
            "await until(() => /Offline/.test(a('c-state').textContent));\n"
            "out.offline = [a('hdr-cloud').textContent, a('c-state').textContent];\n"
            "out.localLevels = JSON.parse(s1.get('calib-site:active')).levels.length;\n"
            "online = true;\n"
            "a('c-sync').click();\n"
            "await until(() => levels() === 2);\n"
            "out.server2 = levels();\n"
            # the second device
            f"const p2 = stub.boot({json.dumps(page)}, {json.dumps(core)}, s2, dev('10.0.0.2')), b = p2.el;\n"
            "b('c-ws').value = 'team-1'; b('c-key').value = 'correct horse battery'; b('c-user').value = 'Binh';\n"
            "b('c-login').click();\n"
            "await until(() => /alpha/.test(b('c-list').innerHTML));\n"
            "out.list = /alpha/.test(b('c-list').innerHTML) && /2 levels/.test(b('c-list').innerHTML);\n"
            "const id = link(s1).id;\n"
            "b('c-list')._listeners.click[0]({ target: { closest: () => ({ dataset: { cid: id, act: 'open' } }) } });\n"
            "await until(() => s2.has('calib-site:active'));\n"
            "out.opened = JSON.parse(s2.get('calib-site:active')).levels.length;\n"
            "out.sameId = link(s2).id === id;\n"
            "a('d-val').value = '130'; a('d-go').click();\n"
            "a('c-sync').click();\n"
            "await until(() => link(s1).rev === link(s1).synced);\n"
            "b('c-sync').click();\n"
            "await until(() => link(s2).version === link(s1).version);\n"
            "out.followed = JSON.parse(s2.get('calib-site:active')).levels[1].dips;\n"
            "out.followMsg = b('c-state').textContent;\n"
        )
        self.assertTrue(got["before"], "logged out: the login form shows")
        self.assertTrue(got["loggedIn"])
        self.assertEqual(got["keyCleared"], "", "the keyword leaves the form after the login")
        self.assertTrue(got["linked"], "logged in: a new campaign goes to the cloud")
        self.assertEqual(got["hdr"], "cloud: saved")
        self.assertEqual(got["server1"], 1)
        self.assertEqual(got["offline"][0], "cloud: waiting")
        self.assertIn("Offline", got["offline"][1])
        self.assertEqual(got["localLevels"], 2, "offline, the browser keeps every entry")
        self.assertEqual(got["server2"], 2, "back online, the change uploads")
        self.assertTrue(got["list"])
        self.assertEqual(got["opened"], 2)
        self.assertTrue(got["sameId"])
        self.assertEqual(got["followed"], [130], "the second device follows the first")
        self.assertIn("Updated from the cloud", got["followMsg"])


if __name__ == "__main__":
    unittest.main()
