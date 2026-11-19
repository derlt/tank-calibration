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
class TestActionList(unittest.TestCase):
    """The link's action list (site/cloud.js): what the merge replays."""
    PRELUDE = TestClient.PRELUDE

    def test_ops_base_and_reasons(self):
        got = _run(
            self.PRELUDE
            + "const at = { row: 1, dips: 0, state: 'start', finished: false, levels: 1, tally: 0 };\n"
            "let data = h.session('alpha', 2);\n"
            "A.linkNew();\n"
            "out.new = [A.actions().why, !!A.link().baseSig];\n"
            "out.first = (await A.sync(() => data)).state;\n"
            "out.base = [A.actions().why === undefined, !!A.link().baseSig, A.link().baseSig.rows.length];\n"
            # an action joins the list; an untap right after its tap takes both out
            "A.markDirty({ k: 'tap', a: [10, 200], t: 1, at });\n"
            "A.markDirty({ cancel: 'tap' });\n"
            "out.pair = [(A.link().ops || []).length, A.actions().why === undefined, A.link().rev];\n"
            # an untap not right after its tap cannot be replayed
            "A.markDirty({ k: 'tap', a: [11, 200], t: 3, at });\n"
            "A.markDirty({ k: 'dip', a: [105, 4], t: 4, at });\n"
            "A.markDirty({ cancel: 'tap' });\n"
            "out.late = [A.actions().why, (A.link().ops || []).length];\n"
            # a saved upload moves the base and empties the list
            "out.saved = (await A.sync(() => data)).state;\n"
            "out.clean = [A.actions().why === undefined, (A.link().ops || []).length, A.link().baseSig.all === cloud.sessionSig(data)];\n"
            # a save with no action: not replayable until the next upload
            "out.timers = (A.markDirty('setTimers'), A.actions().why);\n"
            "await A.sync(() => data);\n"
            "out.again = A.actions().why || 'none';\n"
            # a poll and a take move the base too
            "B.linkTo(await B.fetchCampaign(A.link().id));\n"
            "A.markDirty({ k: 'tap', a: [12, 200], t: 5, at });\n"
            "out.beforePoll = (A.link().ops || []).length;\n"
            "const d2 = h.session('alpha', 3); data = d2;\n"
            "await A.sync(() => data);\n"
            "out.carried = [(A.link().ops || []).length, !!A.link().baseSig];\n"
            # a closed copy carries the list in the outbox and back
            "A.markDirty({ k: 'tap', a: [13, 200], t: 6, at });\n"
            "const closed = A.detach(data);\n"
            "out.box = [(A.outbox()[0].link.ops || []).length, !!A.outbox()[0].link.baseSig];\n"
            "const back = A.attach(closed);\n"
            "out.back = [(A.link().ops || []).length, A.link().baseSig.all === cloud.sessionSig(data)];\n"
            # the list has a cap
            "for (let i = 0; i < cloud.OPS_MAX + 1; i++) A.markDirty({ k: 'tap', a: [i, 200], t: i, at });\n"
            "out.cap = [cloud.OPS_MAX, A.actions().why];\n"
        )
        self.assertEqual(got["new"], ["base", False], "no cloud copy yet: nothing to merge with")
        self.assertEqual(got["first"], "saved")
        self.assertEqual(got["base"], [True, True, 2])
        self.assertEqual(got["pair"], [0, True, 3], "a wrong tap leaves no trace: rev moves, the list does not")
        self.assertEqual(got["late"], ["untap", 0], "a change that cannot be replayed takes the list with it")
        self.assertEqual(got["saved"], "saved")
        self.assertEqual(got["clean"], [True, 0, True], "the base is the saved copy, to the byte")
        self.assertEqual(got["timers"], "setTimers")
        self.assertEqual(got["again"], "none", "the upload settles it")
        self.assertEqual(got["carried"], [0, True], "the upload of the action empties the list")
        self.assertEqual(got["box"], [1, True], "a closed copy keeps its list")
        self.assertEqual(got["back"], [1, True], "and gets it back")
        self.assertEqual(got["cap"], [500, "long"])

    def test_fingerprint_and_canonical_json(self):
        got = _run(
            self.PRELUDE
            + "const a = { b: 1, a: [2, { z: 3, y: 4 }] }, b = { a: [2, { y: 4, z: 3 }], b: 1 };\n"
            "out.canon = cloud.canon(a) === cloud.canon(b);\n"
            "out.sig = cloud.sessionSig(a) === cloud.sessionSig(b);\n"
            "const s = h.session('alpha', 2), t = { version: 1, kind: 'transfer', active: 'out', lastDip: 'in', out: s, in: s };\n"
            "out.active = cloud.sessionSig(t) === cloud.sessionSig(Object.assign({}, t, { active: 'in', lastDip: 'out' }));\n"
            "const f = cloud.fingerprint(t);\n"
            "out.print = [f.kind, f.out.rows.length, f.in.rows.length, !!f.rest, f.all === cloud.sessionSig(t)];\n"
            "out.rows = f.out.rows[0] !== s.levels[0] && f.out.rows[0] === f.in.rows[0];\n"
        )
        self.assertTrue(got["canon"])
        self.assertTrue(got["sig"])
        self.assertTrue(got["active"], "the tank view and the last dip are per device")
        self.assertEqual(got["print"], ["transfer", 2, 2, True, True])
        self.assertTrue(got["rows"])


@unittest.skipUnless(SQLITE, "node with node:sqlite is not installed")
class TestMergeClient(unittest.TestCase):
    """The merge loop (site/cloud.js): when it uploads, waits, or gives the choice."""
    PRELUDE = TestClient.PRELUDE
    AT = "{ row: 1, dips: 2, state: 'start', finished: false, levels: 1, tally: 0 }"

    def test_a_merge_uploads_the_replayed_copy(self):
        got = _run(
            self.PRELUDE
            + f"const at = {self.AT};\n"
            "const calls = []; let data = h.session('alpha', 1);\n"
            "const C = new cloud.Client({ storage: mem(), fetch: net('10.0.0.7'), origin: h.BASE,\n"
            "  rebase: (c, x) => { calls.push([c.version, c.by, x.ops.length, !!x.baseSig, c.local.levels[0].note, !!c.local]);\n"
            "    const m = h.session('alpha', 1); m.levels[0].note = 'mine'; data = m; return { ok: true }; } });\n"
            "await C.login('', 'team-1', 'correct horse battery', 'Chi');\n"
            "C.linkNew(); await C.sync(() => data);\n"
            "const id = C.link().id;\n"
            "const tb = h.session('alpha', 1); tb.levels[0].note = 'wet';\n"
            "B.linkTo(await B.fetchCampaign(id)); B.markDirty(); await B.sync(() => tb);\n"
            "C.markDirty({ k: 'dip', a: [105, 5], t: 1, at });\n"
            "const r = await C.sync(() => data);\n"
            "out.r = [r.state, r.merged && r.merged.by, r.merged && r.merged.n];\n"
            "out.calls = calls;\n"
            "out.link = [C.link().version, C.link().rev === C.link().synced, (C.link().ops || []).length, !!C.link().conflict];\n"
            "out.cloud = (await C.fetchCampaign(id)).data.levels[0].note;\n"
        )
        self.assertEqual(got["r"], ["saved", "Binh", 1])
        self.assertEqual(got["calls"], [[2, "Binh", 1, True, None, True]], "the cloud copy, a named user, my list and base")
        self.assertEqual(got["link"], [3, True, 0, False], "one upload after the merge, the list empty")
        self.assertEqual(got["cloud"], "mine")

    def test_a_wait_and_a_refusal(self):
        got = _run(
            self.PRELUDE
            + f"const at = {self.AT};\n"
            "let how = 'wait'; let data = h.session('alpha', 1);\n"
            "const C = new cloud.Client({ storage: mem(), fetch: net('10.0.0.7'), origin: h.BASE, rebase: () => (how === 'wait' ? { wait: 'note' } : { refused: how }) });\n"
            "await C.login('', 'team-1', 'correct horse battery', 'Chi');\n"
            "C.linkNew(); await C.sync(() => data);\n"
            "const id = C.link().id;\n"
            "const tb = h.session('alpha', 1); tb.levels[0].note = 'wet';\n"
            "B.linkTo(await B.fetchCampaign(id)); B.markDirty(); await B.sync(() => tb);\n"
            "C.markDirty({ k: 'dip', a: [105, 5], t: 1, at });\n"
            "const w = await C.sync(() => data);\n"
            "out.wait = [w.state, w.why, C.dirty(), !!C.link().conflict];\n"
            "how = 'same';\n"
            "const r = await C.sync(() => data);\n"
            "out.refused = [r.state, r.why, C.link().conflict && C.link().conflict.why, C.link().conflict && C.link().conflict.updated_by];\n"
        )
        self.assertEqual(got["wait"], ["wait", "note", True, False], "a wait is not a conflict: the next tick tries again")
        self.assertEqual(got["refused"], ["conflict", "same", "same", "Binh"])

    def test_a_lost_answer_stops_the_merge(self):
        got = _run(
            self.PRELUDE
            + f"const at = {self.AT};\n"
            "let lose = false, calls = 0;\n"
            "const f = h.fetchFor(env, '10.0.0.9');\n"
            "const C = new cloud.Client({ storage: mem(), origin: h.BASE, rebase: () => { calls++; return { ok: true }; },\n"
            "  fetch: async (u, i) => { const r = await f(u, i); if (lose && i.method === 'PUT') { lose = false; throw new TypeError('lost'); } return r; } });\n"
            "await C.login('', 'team-1', 'correct horse battery', 'Chi');\n"
            "let data = h.session('alpha', 1);\n"
            "C.linkNew(); out.first = (await C.sync(() => data)).state;\n"
            "lose = true; data = h.session('alpha', 2); C.markDirty({ k: 'tap', a: [1, 200], t: 1, at });\n"
            "out.lost = (await C.sync(() => data)).state;\n"
            # the lost save landed (v2); another device writes on top (v3)
            "const tb = h.session('alpha', 3); tb.levels[0].note = 'wet';\n"
            "B.linkTo(await B.fetchCampaign(C.link().id)); B.markDirty(); await B.sync(() => tb);\n"
            "out.again = (await C.sync(() => data)).state;\n"
            "out.why = [C.link().conflict && C.link().conflict.why, calls];\n"
        )
        self.assertEqual(got["first"], "saved")
        self.assertEqual(got["lost"], "offline")
        self.assertEqual(got["again"], "conflict", "the cloud may hold the actions: no replay")
        self.assertEqual(got["why"], ["lost", 0], "the merge was never tried")

    def test_a_third_writer_gets_one_more_replay(self):
        got = _run(
            self.PRELUDE
            + f"const at = {self.AT};\n"
            "const f = h.fetchFor(env, '10.0.0.7');\n"
            "let inject = 0, calls = 0, tok = null, id = null;\n"
            "const C = new cloud.Client({ storage: mem(), origin: h.BASE, rebase: () => { calls++; return { ok: true }; },\n"
            "  fetch: async (u, i) => {\n"
            "    if (i.method === 'PUT' && inject > 0) {\n"
            "      inject--;\n"
            "      const cur = (await h.call(env, 'GET', '/api/campaigns/' + id, null, tok)).body;\n"
            "      await h.call(env, 'PUT', '/api/campaigns/' + id, { data: h.session('alpha', cur.version + 2), base_version: cur.version }, tok);\n"
            "    }\n"
            "    return f(u, i); } });\n"
            "await C.login('', 'team-1', 'correct horse battery', 'Chi');\n"
            "let data = h.session('alpha', 1);\n"
            "C.linkNew(); await C.sync(() => data);\n"
            "id = C.link().id; tok = C.auth().token;\n"
            "B.linkTo(await B.fetchCampaign(id)); B.markDirty(); await B.sync(() => h.session('alpha', 1));\n"
            "const one = (n) => { const s = h.session('alpha', 1); s.levels[0].note = 'n' + n; return s; };\n"
            # two writers during the upload: two merges, then saved
            "inject = 2; data = one(1); C.markDirty({ k: 'dip', a: [105, 5], t: 1, at });\n"
            "const r = await C.sync(() => data);\n"
            "out.two = [r.state, calls, C.link().version, !!C.link().conflict];\n"
            "calls = 0;\n"
            "B.markDirty(); await B.sync(() => one(9));\n"
            # a writer at every try: the conflict choice, as before
            "inject = 4; data = one(2); C.markDirty({ k: 'dip', a: [106, 6], t: 2, at });\n"
            "const r2 = await C.sync(() => data);\n"
            "out.many = [r2.state, r2.why, calls, !!C.link().conflict, C.link().conflict && C.link().conflict.why];\n"
        )
        self.assertEqual(got["two"], ["saved", 2, 5, False], "a third writer: one more 409, one more replay")
        self.assertEqual(got["many"], ["conflict", "loop", 3, True, "loop"], "after 3 tries: the choice")


@unittest.skipUnless(SQLITE, "node with node:sqlite is not installed")
class TestStress(unittest.TestCase):
    """Two writers, one campaign, a few hundred seeded steps: the merge keeps both.

    The counter taps cans and closes batches; the dipper dips, re-dips,
    overrides and writes notes; either phone hides, shows, goes offline and
    back, and syncs.  After each sync:
      - a device that ends in step with the cloud shows the cloud copy;
      - a row in the cloud changes only by its own writer (the pour and its
        cans by the counter, the readings and the verdict by the dipper);
      - the cloud never holds more taps or dips than the two people made
        (no doubled action), and never fewer than before (no lost one,
        except through a conflict choice the test makes);
      - every 409 ends merged or in the choice, and every refusal in the
        merge log names its reason.
    """

    STEPS = 200
    SEEDS = (11, 12, 13)

    def _run_one(self, seed: int):
        page = (ROOT / "site" / "page.html").as_posix()
        core = (ROOT / "site" / "site_core.js").as_posix()
        stub = (HERE / "page_stub.js").as_posix()
        body = (
            f"const stub = require({json.dumps(stub)});\n"
            "const env = h.makeEnv();\n"
            "await h.call(env, 'POST', '/api/workspaces', { workspace: 'team-1', keyword: 'correct horse battery', user: 'An', signup_code: 'test-signup-code' });\n"
            "const slow = [];\n"
            "const until = async (ok, tag, tries) => { const n = tries || 400; let i = 0; for (; i < n && !ok(); i++) await new Promise((r) => setTimeout(r, 5)); if (i > 40) slow.push([tag || '?', i]); return ok(); };\n"
            "const link = (st) => JSON.parse(st.get('calib-site:link') || 'null');\n"
            "const active = (st) => JSON.parse(st.get('calib-site:active') || 'null');\n"
            "const cloudData = () => { const r = env.DB.raw.prepare('SELECT data FROM campaigns').get(); return r ? JSON.parse(r.data) : { levels: [] }; };\n"
            "const dlg = { prompt: null };\n"
            "const mk = (ip) => {\n"
            "  const st = new Map(), f = h.fetchFor(env, ip);\n"
            "  const d = { st, on: true, iv: [], ip };\n"
            "  d.fetch = (u, i) => d.on ? f(u, i) : Promise.reject(new TypeError('offline'));\n"
            "  const p = stub.boot(PAGE, CORE, st, Object.assign(d, { location: { protocol: 'https:', origin: h.BASE }, prompt: () => dlg.prompt,\n"
            "    setInterval: (fn, ms) => { d.iv.push({ fn, ms }); return d.iv.length; } }));\n"
            "  d.el = p.el; d.doc = p.document;\n"
            "  return d;\n"
            "};\n"
            f"const PAGE = {json.dumps(page)}, CORE = {json.dumps(core)};\n"
            "let rs = {};\n"
            "const rnd = (() => { let a = SEED >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; })();\n"
            "const pick = (n) => Math.floor(rnd() * n);\n"
            "const A = mk('10.1.0.1'), B = mk('10.1.0.2'), D = [A, B];\n"
            "const NAME = ['An', 'Binh'];\n"
            "const err = (d) => (d.el('p-err').textContent || d.el('d-err').textContent || d.el('log-err').textContent || '');\n"
            "const login = async (d, user) => { d.el('c-ws').value = 'team-1'; d.el('c-key').value = 'correct horse battery'; d.el('c-user').value = user; d.el('c-login').click(); await until(() => !d.el('c-in')._classes.has('hidden'), 'login'); };\n"
            "const start = (d) => { d.el('s-tank').value = 'alpha'; d.el('s-D').value = '2400'; d.el('s-L').value = '5000'; d.el('s-dip').value = '100'; d.el('s-step').value = '?';\n"
            "  d.el('s-unit').value = '200'; d.el('s-go').click(); d.el('d-val').value = '100'; d.el('d-go').click(); };\n"
            # one sync; -> what the cloud rows were before, the actions this device held
            "const snap = () => { const c = cloudData(); return JSON.stringify({ levels: c.levels || [], batch: c.batch || null }); };\n"
            "const lv = (s) => JSON.parse(s || '{\"levels\":[]}').levels;\n"
            "const bt = (s) => JSON.parse(s || '{}').batch || null;\n"
            "const sync = async (d) => {\n"
            "  const l0 = link(d.st); if (!l0) return null;\n"
            "  const before = snap(), kinds = (l0.ops || []).map((o) => o.k);\n"
            "  d.el('c-sync').click();\n"
            "  await until(() => { const l = link(d.st); return l && (l.rev === l.synced || l.conflict); }, 'sync', d.on ? 400 : 8);\n"
            "  await new Promise((r) => setTimeout(r, 20));\n"
            "  await settle(d);\n"
            "  return { before, kinds, conflict: !!link(d.st).conflict, after: snap(), state: d.el('hdr-cloud').textContent };\n"
            "};\n"
            "const POUR = ['step', 'cans', 'plan', 'from', 'pourTime', 'overflow', 'neck', 'transfer'];\n"
            "const settle = async (d) => { if (!d.on || !link(d.st)) return; for (let i = 0; i < 80; i++) { const x = link(d.st); if (x && (x.rev === x.synced || x.conflict)) return; await new Promise((r) => setTimeout(r, 5)); } slow.push('settle'); };\n"
            # a note and a tag: either writer may add one
            "const EITHER = ['note', 'tags', 'row'];\n"
            "const part = (r) => { const o = Object.assign({}, r || {}); for (const k of POUR.concat(EITHER)) delete o[k]; return JSON.stringify(o); };\n"
            "const pour = (r) => JSON.stringify(POUR.map((k) => (r || {})[k]));\n"
            "const note = (r) => (r || {}).note;\n"
            "const rows = (s) => JSON.parse(s || '{\"levels\":[]}').levels;\n"
            "const tapsIn = (levels, batch) => levels.reduce((a, L) => a + (L.cans ? (L.cans.tapped || 0) : 0), 0) + (batch ? batch.cans.length : 0);\n"
            "const dipsIn = (levels) => levels.reduce((a, L) => a + (L.dips || []).length, 0);\n"
            "const bad = [], log = [];\n"
            "const check = (d, i, s) => {\n"
            "  if (!s) return;\n"
            "  const a = rows(s.before), b = rows(s.after), n = Math.max(a.length, b.length);\n"

            "  const has = (...k) => k.some((x) => s.kinds.indexOf(x) >= 0);\n"
            "  for (let r = 0; r < n; r++) {\n"
            "    if (JSON.stringify(a[r]) === JSON.stringify(b[r])) continue;\n"
            "    if (!a[r]) { if (!has('pour', 'closeBatch')) bad.push(['new row', wish, r, s.kinds.join(','), a.length, b.length]); continue; }\n"
            "    if (pour(a[r]) !== pour(b[r]) && !has('pour', 'closeBatch', 'editPour')) bad.push(['pour part', wish, r, s.kinds.join(',')]);\n"
            "    if (part(a[r]) !== part(b[r]) && !has('dip', 'redip', 'override', 'editPour')) bad.push(['dip part', wish, r, s.kinds.join(',')]);\n"

            "  }\n"
            "  const m = JSON.parse(d.st.get('calib-site:merges') || '[]');\n"
            "  for (const x of m) log.push([x.ok, x.why || null]);\n"
            "  if (s.conflict && !d.el('c-conflict')._classes.has('hidden') === false) bad.push(['conflict hidden', wish]);\n"
            "};\n"
            "let wish = 0;\n"
            "const attempts = { taps: 0, dips: 0 };\n"
            "const conflicts = [];\n"
            "const lost = { taps: 0, dips: 0 };\n"
            "const take = async (d) => {\n"
            "  const l = link(d.st), kinds = (l.ops || []).map((o) => o.k);\n"
            "  lost.taps += kinds.filter((k) => k === 'tap').length;\n"
            "  lost.dips += kinds.filter((k) => k === 'dip' || k === 'dipBoth').length;\n"
            "  d.el('c-take').click(); await until(() => !link(d.st).conflict, 'take');\n"

            "};\n"

            "const guess = (levels) => 100 + 30 * Math.max(0, levels.length - 1) + (rnd() * 4 - 2);\n"
            "const dipNow = (d, n) => { for (let k = 0; k < n; k++) { const v = guess(active(d.st).levels); d.el('d-val').value = String(v); d.el('d-go').click(); if (err(d)) break; attempts.dips++; } };\n"
            "const misc = async (d, i) => {\n"
            "  const q = pick(4);\n"
            "  if (q === 0) { d.doc.hidden = true; d.doc.fire('visibilitychange'); await settle(d); d.doc.hidden = false; d.doc.fire('visibilitychange'); await settle(d); }\n"
            "  else if (q === 1) d.on = !d.on;\n"
            "  else if (q === 2) { const t = d.iv.find((x) => x.ms === 10000); if (t) t.fn(); await new Promise((r) => setTimeout(r, 10)); await settle(d); }\n"
            "  else { const s2 = await sync(d); check(d, i, s2); if (s2 && s2.conflict) { conflicts.push(['sync', link(d.st).conflict.why || 'none']); await take(d); } }\n"
            "};\n"
            "const counter = async (d) => {\n"                            # taps, Batch done, a recount
            "  const s = active(d.st), L = s.levels[s.levels.length - 1];\n"
            "  if (!s || s.finished || !L) return;\n"
            "  const r = pick(10);\n"
            "  if (r < 6 && L.state !== 'pending') { d.el('t-unit').value = '200'; d.el('t-plus').click(); if (!err(d)) attempts.taps++; }\n"
            "  else if (r < 8 && s.batch && s.batch.cans.length) { d.el('p-vol').value = ''; d.el('p-go').click(); }\n"
            "  else if (r < 9 && !L.start) { dlg.prompt = String(400 + 200 * pick(3)); d.el('a-edit').click(); dlg.prompt = null; }\n"
            "  else await misc(d, 0);\n"
            "};\n"
            "const dipper = async (d) => {\n"                             # dips, Dip again, Accept anyway, notes
            "  const s = active(d.st), L = s.levels[s.levels.length - 1];\n"
            "  if (!s || !L) return;\n"
            "  const r = pick(10);\n"
            "  if (r < 5 && L.state === 'pending') dipNow(d, 1 + pick(2));\n"
            "  else if (r < 7 && L.state !== 'pending') { d.el('a-redip').click(); dipNow(d, 1 + pick(2)); }\n"
            "  else if (r < 8 && L.state !== 'pending') { d.el('a-redip').click(); d.el('d-val').value = String(guess(s.levels) + 40); d.el('d-go').click(); if (!err(d)) attempts.dips++; dlg.prompt = 'stress'; d.el('a-override').click(); dlg.prompt = null; }\n"
            "  else if (r < 9 && s.levels.length > 1) {\n"                # a note on an earlier row
            "    const row = 1 + pick(s.levels.length - 1);\n"
            "    d.el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'log' } }) } });\n"
            "    d.el('log-table')._listeners.click[0]({ target: { closest: (x) => (x === 'button[data-note-edit]' ? { dataset: { noteEdit: String(row) } } : null) } });\n"
            "    d.el('note-edit').value = 'dip note ' + wish;\n"
            "    d.el('log-table')._listeners.click[0]({ target: { closest: (x) => (x === 'button[data-note-save]' ? { dataset: { noteSave: String(row) } } : null) } });\n"
            "    d.el('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'live' } }) } });\n"
            "  } else await misc(d, 1);\n"
            "};\n"
            "const act = async (i) => {\n"
            "  const d = D[i];\n"
            "  if (i === 0) await counter(d); else await dipper(d);\n"
            "  if (i === 0 && rnd() < 0.35 || i === 1 && rnd() < 0.35) {\n"
            "    const s2 = await sync(d); check(d, i, s2);\n"
            "    if (s2 && s2.conflict) { conflicts.push([['counter', 'dipper'][i], link(d.st).conflict.why || 'none']); await take(d); }\n"
            "  }\n"
            "};\n"
            "const totals = [];\n"
            "const mark = () => { const c = cloudData(); totals.push([tapsIn(c.levels, c.batch), dipsIn(c.levels)]); };\n"
            "await login(A, 'An'); start(A); attempts.dips += 2;\n"
            "const sA = await sync(A);\n"
            "await login(B, 'Binh');\n"
            "B.el('c-list')._listeners.click[0]({ target: { closest: () => ({ dataset: { cid: link(A.st).id, act: 'open' } }) } });\n"
            "await until(() => link(B.st) && link(B.st).id === link(A.st).id);\n"
            "mark();\n"
            f"for (let k = 0; k < {self.STEPS}; k++) {{ wish = k; await act(pick(2)); mark(); }}\n"
            # settle: both online, both synced, until quiet
            "A.on = true; B.on = true;\n"
            "const ok = [false, false];\n"
            "for (let k = 0; k < 6; k++) {\n"
            "  for (let i = 0; i < 2; i++) {\n"
            "    const s2 = await sync(D[i]); check(D[i], i, s2);\n"
            "    if (s2 && s2.conflict) { conflicts.push([['counter', 'dipper'][i], link(D[i].st).conflict.why || 'none']); await take(D[i]); }\n"
            "    const l = link(D[i].st);\n"
            "    ok[i] = l.rev === l.synced && !l.conflict && cloud.sessionSig(active(D[i].st)) === cloud.sessionSig(cloudData());\n"

            "  }\n"
            "}\n"
            "const c = cloudData();\n"
            "Object.assign(out, {\n"
            "  bad, attempts, conflicts, log: log.slice(-3), merges: log.filter((x) => x[0]).length, refusals: log.filter((x) => !x[0]).map((x) => x[1]),\n"
            "  cloud: [tapsIn(c.levels, c.batch), dipsIn(c.levels), c.levels.length],\n"
            "  monotone: totals.every((t, i) => i === 0 || (t[0] >= totals[i - 1][0] && t[1] >= totals[i - 1][1])),\n"
            "  over: totals.some((t) => t[0] > attempts.taps || t[1] > attempts.dips),\n"
            "  settled: ok,\n"
            "  lost,\n"
            "  exact: [tapsIn(c.levels, c.batch) + lost.taps, dipsIn(c.levels) + lost.dips],\n"

            "  states: [A.el('hdr-cloud').textContent, B.el('hdr-cloud').textContent],\n"
            "  dbg: slow.slice(0, 8),\n"

            "});\n"
        )
        return _run(f"const SEED = {seed};\n" + body)

    def test_two_writers_of_one_campaign(self):
        merges = 0
        for seed in self.SEEDS:
            with self.subTest(seed=seed):
                got = self._run_one(seed)
                self.assertEqual(got["bad"], [], "a row changed by the wrong writer, a doubled action, or a hidden conflict")
                self.assertEqual(got["dbg"], [], "no upload stalled: every sync settled at once")
                self.assertFalse(got["over"], "the cloud holds more taps or dips than were made")
                self.assertTrue(got["monotone"], "the cloud lost a tap or a dip outside a conflict choice")
                self.assertEqual(got["settled"], [True, True], "both devices end in step with the cloud")
                self.assertEqual(got["states"], ["cloud: saved", "cloud: saved"])
                self.assertEqual(got["exact"], [got["attempts"]["taps"], got["attempts"]["dips"]],
                                 "every tap and dip is in the cloud, or was lost by a conflict choice")
                for why in got["refusals"]:
                    self.assertTrue(why and why != "off", "a refusal names its reason")
                merges += got["merges"]
        self.assertGreater(merges, 0, "at least one merge ran: the test has teeth")


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
            "b('t-unit').value = '200';   // the can size on B's device too\n"
            "const note = (e, row, text) => { const click = (sel, data) => e('log-table')._listeners.click[0]({ target: { closest: (s) => (s === sel ? { dataset: data } : null) } });\n"
            "  click('button[data-note-edit]', { noteEdit: String(row) }); e('note-edit').value = text; click('button[data-note-save]', { noteSave: String(row) }); };\n"
            "const sync = async (e, st) => { e('c-sync').click(); await until(() => link(st).rev === link(st).synced || link(st).conflict); await new Promise((r) => setTimeout(r, 20)); };\n"
            "const follow = async (e, st, v) => { e('c-sync').click(); await until(() => link(st).version >= v); };\n"
            "const active = (st) => JSON.parse(st.get('calib-site:active'));\n"
            "const dip = (e, ...vs) => { for (const v of vs) { e('d-val').value = String(v); e('d-go').click(); } };\n"
        )

    def test_case_a_dipper_writes_while_the_counter_counts(self):
        got = _run(
            self._team()
            # A counts a can (not sent yet); B writes a note and saves first
            + "a('t-plus').click();\n"
            "note(b, 1, 'datum plate wet'); await sync(b, s2);\n"
            "await sync(a, s1);\n"
            "out.hdr = a('hdr-cloud').textContent;\n"
            "out.msg = a('c-state').textContent;\n"
            "out.cloud = [cloudData().levels[0].note, cloudData().batch.cans.length];\n"
            "out.mine = active(s1).batch.cans.length;\n"
            "out.clean = [link(s1).rev === link(s1).synced, !!link(s1).conflict, (link(s1).ops || []).length];\n"
        )
        self.assertEqual(got["hdr"], "cloud: saved", "a merge, not a conflict")
        self.assertIn("Merged with Binh's changes", got["msg"])
        self.assertEqual(got["cloud"], ["datum plate wet", 1], "both the note and the can are in the cloud")
        self.assertEqual(got["mine"], 1, "this device shows both too")
        self.assertEqual(got["clean"], [True, False, 0], "the upload settled and the list is empty")

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
            "out.msg = a('c-state').textContent;\n"
            "out.cloud = [cloudData().levels[1].step.text, cloudData().levels[1].dips];\n"
        )
        self.assertEqual(got["hdr"], "cloud: conflict", "both changed row 2: no safe merge")
        self.assertIn("Binh changed the same level or tally", got["msg"])
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
            "out.mine = [active(s2).levels[0].note, active(s2).batch.cans.length];\n"
        )
        self.assertEqual(got["hdr"], "cloud: saved", "a stale write merges")
        self.assertEqual(got["cloud"], ["datum plate wet", 1], "B's note and A's can are both kept")
        self.assertEqual(got["mine"], ["datum plate wet", 1])

    def test_a_stale_dip_merges_with_their_note(self):
        got = _run(
            self._team()
            # A closes a batch and follows: row 2 waits for its dip
            + "a('t-plus').click(); a('t-plus').click(); a('p-go').click(); a('c-sync').click(); await settled(s1);\n"
            "await follow(b, s2, link(s1).version);\n"
            # B has not seen it and dips row 2 at once; A writes a note on row 1 meanwhile
            "dip(b, 130, 130);\n"
            "note(a, 1, 'datum plate wet'); await sync(a, s1);\n"
            "await sync(b, s2);\n"
            "out.hdr = b('hdr-cloud').textContent;\n"
            "out.cloud = [cloudData().levels[0].note, cloudData().levels[1].dips, cloudData().levels[1].state];\n"
            "out.mine = [active(s2).levels[0].note, active(s2).levels[1].dips];\n"
            "out.state = active(s2).levels[1].state;\n"
        )
        self.assertEqual(got["hdr"], "cloud: saved", "the dip merges with the note")
        self.assertEqual(got["cloud"][:2], ["datum plate wet", [130, 130]])
        self.assertEqual(got["cloud"][2], got["state"], "the cloud keeps the verdict the dipper saw")
        self.assertEqual(got["mine"], ["datum plate wet", [130, 130]], "the dipper sees the note too")

    def test_a_finish_merges_with_a_count(self):
        got = _run(
            self._team()
            # A counts a can (not sent); B finishes the tank
            + "a('t-plus').click();\n"
            "b('now-fin-a').click(); await sync(b, s2);\n"
            "await sync(a, s1);\n"
            "out.hdr = a('hdr-cloud').textContent;\n"
            "out.cloud = [!!cloudData().finished, cloudData().batch.cans.length];\n"
        )
        self.assertEqual(got["hdr"], "cloud: saved", "a can counted, then the tank finished, is a state the page makes")
        self.assertEqual(got["cloud"], [True, 1])

    def test_a_third_writer_between_the_merge_and_its_upload(self):
        # A counts a can (not sent); B notes row 1 (v2); A merges, and B writes
        # again just before A's merged copy goes up: a second merge.
        got = _run(
            self._devices()
            + "const s1 = new Map(), s2 = new Map();\n"
            "let puts = 0, tokB = null, id = null;\n"
            "const d1 = dev('10.0.0.1'), f1 = d1.fetch;\n"
            "d1.fetch = async (u, i) => {\n"
            "  if (i && i.method === 'PUT' && ++puts === 3) {\n"
            "    const cur = (await h.call(env, 'GET', '/api/campaigns/' + id, null, tokB)).body;\n"
            "    const d = JSON.parse(env.DB.raw.prepare('SELECT data FROM campaigns').get().data);\n"
            "    d.levels[0].note = 'second note';\n"
            "    await h.call(env, 'PUT', '/api/campaigns/' + id, { data: d, base_version: cur.version }, tokB);\n"
            "  }\n"
            "  return f1(u, i);\n"
            "};\n"
            f"const a = stub.boot({json.dumps((ROOT / 'site' / 'page.html').as_posix())}, {json.dumps((ROOT / 'site' / 'site_core.js').as_posix())}, s1, d1).el;\n"
            "const b = boot(s2, '10.0.0.2').el;\n"
            "const active = (st) => JSON.parse(st.get('calib-site:active'));\n"
            "await login(a, 'An'); start(a); a('t-unit').value = '200'; a('c-sync').click(); await settled(s1);\n"
            "id = link(s1).id;\n"
            "await login(b, 'Binh'); openCloud(b, id); await until(() => link(s2) && link(s2).id === id);\n"
            "tokB = JSON.parse(s2.get('calib-site:cloud')).token;\n"
            "b('t-unit').value = '200';\n"
            "const note = (e, row, text) => { const click = (sel, data) => e('log-table')._listeners.click[0]({ target: { closest: (x) => (x === sel ? { dataset: data } : null) } });\n"
            "  click('button[data-note-edit]', { noteEdit: String(row) }); e('note-edit').value = text; click('button[data-note-save]', { noteSave: String(row) }); };\n"
            "a('t-plus').click();\n"
            "note(b, 1, 'first note'); b('c-sync').click(); await until(() => link(s2).rev === link(s2).synced);\n"
            "a('c-sync').click(); await until(() => link(s1).rev === link(s1).synced || link(s1).conflict);\n"
            "await new Promise((r) => setTimeout(r, 30));\n"
            "out.hdr = a('hdr-cloud').textContent;\n"
            "out.puts = puts;\n"
            "out.cloud = [cloudData().levels[0].note, cloudData().batch.cans.length];\n"
            "out.mine = [active(s1).levels[0].note, active(s1).batch.cans.length];\n"
            "out.ops = (link(s1).ops || []).length;\n"
            "out.log = JSON.parse(s1.get('calib-site:merges') || '[]');\n"
        )
        self.assertEqual(got["hdr"], "cloud: saved")
        self.assertEqual(got["puts"], 4, "the campaign, the tap, the merged copy, then the second merge's copy")
        self.assertEqual(got["cloud"], ["second note", 1], "the third writer's note and A's can both stay")
        self.assertEqual(got["mine"], ["second note", 1])
        self.assertEqual(got["ops"], 0)
        self.assertEqual([x["version"] for x in got["log"]], [3, 2], "two merges, each one in the log")

    def test_a_tap_after_a_new_level_is_refused(self):
        got = _run(
            self._team()
            # A closes a batch; B follows and dips row 2; A already poured row 3
            + "a('t-plus').click(); a('t-plus').click(); a('p-go').click(); dip(a, 130, 130);\n"
            "a('t-plus').click(); a('t-plus').click(); a('p-go').click(); a('c-sync').click(); await settled(s1);\n"
            "out.aLevels = active(s1).levels.length;\n"
            # B, stale at row 2 decided, counts a can: row 3 waits there on the cloud
            "b('t-plus').click(); await sync(b, s2);\n"
            "out.hdr = b('hdr-cloud').textContent;\n"
            "out.msg = b('c-state').textContent;\n"
            "out.cloud = cloudData().levels.length;\n"
        )
        self.assertEqual(got["hdr"], "cloud: conflict")
        self.assertIn("An changed the level this device used", got["msg"])
        self.assertEqual(got["cloud"], 3, "no wrong row from the stale tap")

    def test_undo_is_not_replayable(self):
        got = _run(
            self._team()
            # A closes a batch, dips, then takes the last reading back (Undo); B writes a note first
            + "a('t-plus').click(); a('t-plus').click(); a('p-go').click(); dip(a, 130, 130); a('a-undo').click();\n"
            "note(b, 1, 'datum plate wet'); await sync(b, s2);\n"
            "await sync(a, s1);\n"
            "out.hdr = a('hdr-cloud').textContent;\n"
            "out.msg = a('c-state').textContent;\n"
            "out.cloud = [cloudData().levels.length, cloudData().levels[0].note];\n"
        )
        self.assertEqual(got["hdr"], "cloud: conflict")
        self.assertIn("You removed an entry.", got["msg"])
        self.assertEqual(got["cloud"], [1, "datum plate wet"], "the cloud keeps its own level")

    def test_an_action_that_throws_stops_the_merge(self):
        got = _run(
            self._team()
            # A counts a can; the list's can size turns bad (a bug on site)
            + "a('t-plus').click();\n"
            "const l = link(s1); l.ops[0].a[1] = -5; s1.set('calib-site:link', JSON.stringify(l));\n"
            "note(b, 1, 'datum plate wet'); await sync(b, s2);\n"
            "await sync(a, s1);\n"
            "out.hdr = a('hdr-cloud').textContent;\n"
            "out.msg = a('c-state').textContent;\n"
            "out.cloud = [cloudData().levels[0].note, cloudData().batch];\n"
        )
        self.assertEqual(got["hdr"], "cloud: conflict")
        self.assertIn("An action of this device does not apply", got["msg"])
        self.assertEqual(got["cloud"], ["datum plate wet", None])

    def test_a_missing_action_stops_the_merge(self):
        got = _run(
            self._team()
            # A counts a can; its signature no longer explains the copy (a crash between two writes)
            + "a('t-plus').click();\n"
            "const l = link(s1); l.ops[l.ops.length - 1].after = '0:0'; s1.set('calib-site:link', JSON.stringify(l));\n"
            "note(b, 1, 'datum plate wet'); await sync(b, s2);\n"
            "await sync(a, s1);\n"
            "out.hdr = a('hdr-cloud').textContent;\n"
            "out.msg = a('c-state').textContent;\n"
        )
        self.assertEqual(got["hdr"], "cloud: conflict")
        self.assertIn("missing from its action list", got["msg"])

    def test_the_merge_waits_for_a_note_and_for_another_tab(self):
        got = _run(
            self._team()
            # A counts a can; a note is open in the Log; B writes first
            + "a('t-plus').click();\n"
            "a('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'log' } }) } });\n"
            "a('log-table')._listeners.click[0]({ target: { closest: (s) => (s === 'button[data-note-edit]' ? { dataset: { noteEdit: '1' } } : null) } });\n"
            "note(b, 1, 'datum plate wet'); await sync(b, s2);\n"
            "await sync(a, s1);\n"
            "out.note = [a('hdr-cloud').textContent, !!(link(s1) && link(s1).conflict), link(s1).rev > link(s1).synced];\n"
            # the note closes; the next sync merges
            "a('note-edit').value = ''; a('log-table')._listeners.click[0]({ target: { closest: (s) => (s === 'button[data-note-cancel]' ? { dataset: { noteCancel: '1' } } : null) } });\n"
            "await sync(a, s1);\n"
            "out.after = [a('hdr-cloud').textContent, cloudData().batch.cans.length];\n"
            # another tab wrote: the merge waits, no conflict
            "a('t-plus').click();\n"
            "note(b, 1, 'second row'); await sync(b, s2);\n"
            "const st = JSON.parse(s1.get('calib-site:active')); st.levels[0].note = 'other tab'; s1.set('calib-site:active', JSON.stringify(st));\n"
            "await sync(a, s1);\n"
            "out.tab = [!!(link(s1) && link(s1).conflict), link(s1).rev > link(s1).synced];\n"
        )
        self.assertEqual(got["note"], ["cloud: waiting", False, True], "an open note holds the merge back: no conflict")
        self.assertEqual(got["after"], ["cloud: saved", 1], "the next sync merges")
        self.assertEqual(got["tab"], [False, True], "another tab holds it back too")

    def test_every_session_button_makes_an_action_or_blocks_the_list(self):
        # The page test of the action list: each button that changes the
        # session makes an op, or marks the list not replayable.  A change
        # outside the wrapper (a direct write to S) fails check 3 instead.
        got = _run(
            self._devices()
            + "const s1 = new Map(); const a = boot(s1, '10.0.0.1').el;\n"
            "const dip = (e, ...vs) => { for (const v of vs) { e('d-val').value = String(v); e('d-go').click(); } };\n"
            "const log = (name) => { const l = link(s1) || {}; if (!l) { out[name] = ['no link']; return; } const ops = l.ops || [], last = ops[ops.length - 1];\n"
            "  out[name] = l.noReplay ? ['no', l.noReplay.why] : [last && last.k, ops.length, last && last.a.length]; };\n"
            "const sync = async () => { a('c-sync').click(); await settled(s1); };\n"
            "await login(a, 'An'); start(a); a('t-unit').value = '200'; await sync();\n"
            "a('t-plus').click(); log('tap');\n"
            "a('t-plus').click(); a('t-undo').click(); log('cancel');\n"
            # a batch with 3 cans, closed
            "a('t-plus').click(); a('t-plus').click(); a('p-vol').value = '600'; a('p-go').click(); log('close');\n"
            "dip(a, 130, 130); log('dip');\n"
            "await sync();\n"
            "a('a-redip').click(); log('redip');\n"
            "a('d-val').value = '131'; a('d-go').click(); a('d-val').value = '131'; a('d-go').click();\n"
            "dlg.prompt = '600'; a('a-edit').click(); dlg.prompt = null; log('editPour');\n"
            "await sync();\n"
            # two readings that disagree: Accept anyway
            "a('a-redip').click(); a('d-val').value = '999'; a('d-go').click(); log('pending');\n"
            "dlg.prompt = 'checked'; a('a-override').click(); dlg.prompt = null; log('override');\n"
            "await sync();\n"
            # the Log note, then the Settings and Timers forms
            "a('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'log' } }) } });\n"
            "a('log-table')._listeners.click[0]({ target: { closest: (s) => (s === 'button[data-note-edit]' ? { dataset: { noteEdit: '2' } } : null) } });\n"
            "a('note-edit').value = 'slow pump';\n"
            "a('log-table')._listeners.click[0]({ target: { closest: (s) => (s === 'button[data-note-save]' ? { dataset: { noteSave: '2' } } : null) } });\n"
            "log('note');\n"
            "await sync();\n"
            "a('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'settings' } }) } });\n"
            "a('set-tank').value = 'alpha'; a('set-D').value = '2400'; a('set-L').value = '5000'; a('set-save').click(); log('settings');\n"
            "await sync();\n"
            "a('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'live' } }) } });\n"
            "a('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'settings' } }) } });\n"
            "a('tm-settle').value = '6:00'; a('tm-save').click(); log('timers');\n"
            "a('c-sync').click(); await until(() => link(s1).rev === link(s1).synced);\n"
            "a('tabs')._listeners.click[0]({ target: { closest: () => ({ dataset: { tab: 'live' } }) } });\n"
            "a('now-fin-a').click(); log('finish');\n"
            "a('now-fin-a').click(); log('reopen');\n"
            "a('a-undo').click(); log('undo');\n"
            "a('f-new').click(); log('close campaign');\n"
        )
        self.assertEqual(got["tap"][0], "tap")
        self.assertEqual(got["cancel"][:2], ["tap", 1], "a tap and its untap leave the list as it was")
        self.assertEqual(got["close"][0], "closeBatch")
        self.assertEqual(got["dip"][0], "dip")
        self.assertEqual(got["redip"][0], "redip")
        self.assertEqual(got["editPour"][0], "editPour")
        self.assertEqual(got["pending"][0], "dip")
        self.assertEqual(got["override"][0], "override")
        self.assertEqual(got["note"][0], "editNote")
        self.assertEqual(got["settings"], ["no", "setCampaign"])
        self.assertEqual(got["timers"], ["no", "setTimers"])
        self.assertEqual(got["finish"][0], "finish")
        self.assertEqual(got["reopen"], ["no", "reopen"])
        self.assertEqual(got["undo"], ["no", "undo"])

    def test_the_switch_the_log_and_the_restore(self):
        got = _run(
            self._team()
            # the switch is on by default; off: today's conflict choice
            + "out.on = a('c-merge').checked;\n"
            "a('c-merge').checked = false; a('c-merge')._listeners.change[0]();\n"
            "out.off = [JSON.parse(s1.get('calib-site:cloud')).merge, a('c-merge').checked];\n"
            "a('t-plus').click();\n"
            "note(b, 1, 'datum plate wet'); await sync(b, s2);\n"
            "await sync(a, s1);\n"
            "out.offConflict = [a('hdr-cloud').textContent, (link(s1).ops || []).length];\n"
            "out.offLog = JSON.parse(s1.get('calib-site:merges') || '[]').length;\n"
            # on again, back on the cloud copy: the merge runs, the log says so
            "a('c-take').click(); await until(() => !link(s1).conflict);\n"
            "a('c-merge').checked = true; a('c-merge')._listeners.change[0]();\n"
            "a('t-plus').click();\n"
            "note(b, 1, 'dipped twice'); await sync(b, s2);\n"
            "await sync(a, s1);\n"
            "out.merged = a('hdr-cloud').textContent;\n"
            "const log = JSON.parse(s1.get('calib-site:merges') || '[]');\n"
            "out.log = [log[0].ok, log[0].by, log[0].n];\n"
            "out.logLine = a('c-merges').innerHTML;\n"
            "out.fold = !a('c-merges-box')._classes.has('hidden');\n"
            "const pre = JSON.parse(s1.get('calib-site:premerge'));\n"
            "out.pre = [pre.session.levels[0].note, !!pre.cloud];\n"
            "out.restoreShown = !a('c-premerge')._classes.has('hidden');\n"
            # restore: the copy from before the merge, then the usual choice
            "a('c-restore').click();\n"
            "await new Promise((r) => setTimeout(r, 30));\n"
            "out.restored = [active(s1).levels[0].note, s1.get('calib-site:premerge'), link(s1).noReplay && link(s1).noReplay.why];\n"
            "await sync(a, s1);\n"
            "out.choice = [a('hdr-cloud').textContent, !!link(s1).conflict];\n"
            "out.cloud = cloudData().levels[0].note;\n"
        )
        self.assertTrue(got["on"], "the merge is on by default")
        self.assertEqual(got["off"], [False, False])
        self.assertEqual(got["offConflict"], ["cloud: conflict", 1], "off: the conflict choice, the list kept")
        self.assertEqual(got["offLog"], 0, "a switched-off merge is not a result")
        self.assertEqual(got["merged"], "cloud: saved")
        self.assertEqual(got["log"], [True, "Binh", 1])
        self.assertIn("merged", got["logLine"])
        self.assertTrue(got["fold"], "the log shows under its fold")
        self.assertEqual(got["pre"], ["datum plate wet", True], "my copy from before the merge is kept")
        self.assertTrue(got["restoreShown"])
        self.assertEqual(got["restored"], ["datum plate wet", None, "restore"])
        self.assertEqual(got["choice"], ["cloud: conflict", True], "a restored copy goes through the normal choice")
        self.assertEqual(got["cloud"], "dipped twice", "the cloud copy stays")

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
            "b('t-unit').value = '200';   // the can size on B's device too\n"
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
            "b('t-unit').value = '200';   // the can size on B's device too\n"
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

    def _transfer(self):
        """Two devices on one transfer campaign: A counts, B dips both tanks."""
        return (
            self._devices()
            + "const s1 = new Map(), s2 = new Map(); const a = boot(s1, '10.0.0.1').el, b = boot(s2, '10.0.0.2').el;\n"
            "await login(a, 'An');\n"
            "a('s-dir-transfer').click();\n"
            "a('s-tank').value = 'alpha'; a('s-D').value = '1800'; a('s-L').value = '3000';\n"
            "a('sB-tank').value = 'beta'; a('sB-D').value = '2480'; a('sB-L').value = '5200';\n"
            "a('s-dip').value = '1800'; a('sB-dip').value = '400'; a('s-unit').value = '200';\n"
            "a('s-go').click();\n"
            "a('d-val').value = '1800'; a('d-val-b').value = '400'; a('d-go-a').click(); a('d-go-b').click();\n"
            "a('c-sync').click(); await settled(s1);\n"
            "await login(b, 'Binh'); const id = link(s1).id;\n"
            "openCloud(b, id); await until(() => link(s2) && link(s2).id === id);\n"
            "b('t-unit').value = '200';\n"
            "const sync = async (e, st) => { e('c-sync').click(); await until(() => link(st).rev === link(st).synced || link(st).conflict); await new Promise((r) => setTimeout(r, 20)); };\n"
            "const follow = async (e, st, v) => { e('c-sync').click(); await until(() => link(st).version >= v); };\n"
            "const active = (st) => JSON.parse(st.get('calib-site:active'));\n"
            "const both = (e, o, i) => { e('d-val').value = String(o); e('d-go-a').click(); e('d-val-b').value = String(i); e('d-go-b').click(); };\n"
        )

    def test_a_transfer_merges_a_count_and_a_dip(self):
        got = _run(
            self._transfer()
            # A counts 2 cans (not sent); B pours into both tanks and dips them: no, B only dips
            + "a('t-plus').click(); a('t-plus').click();\n"
            "both(b, 1800, 400); await sync(b, s2);\n"
            "await sync(a, s1);\n"
            "out.hdr = a('hdr-cloud').textContent;\n"
            "const c = cloudData();\n"
            "out.cloud = [c.out.levels.length, c.out.batch && c.out.batch.cans.length, c.out.levels[0].dips.length];\n"
            "out.mine = [active(s1).out.batch.cans.length, active(s1).out.levels[0].dips.length];\n"
            "out.view = active(s2).active;\n"
        )
        self.assertEqual(got["hdr"], "cloud: saved", "a transfer merges through the same path")
        self.assertEqual(got["cloud"], [1, 2, 2], "the count and B's reading are both in the cloud")
        self.assertEqual(got["mine"], [2, 2], "the counter sees the dip too")

    def test_a_transfer_refuses_the_same_tank_row(self):
        got = _run(
            self._transfer()
            # A pours a batch and B follows; B dips tank A, then A pours again and edits the same row
            + "a('t-plus').click(); a('t-plus').click(); a('p-go').click(); await sync(a, s1);\n"
            "await follow(b, s2, link(s1).version);\n"
            "a('d-val').value = '1800'; a('d-go-a').click(); a('d-val-b').value = '400'; a('d-go-b').click();\n"
            "dlg.prompt = '400'; a('a-edit').click(); dlg.prompt = null;\n"
            "await sync(a, s1);\n"
            # B, stale, dips tank A's waiting row: the same row A edited
            "b('d-val').value = '1800'; b('d-go-a').click(); await sync(b, s2);\n"
            "out.hdr = b('hdr-cloud').textContent;\n"
            "out.msg = b('c-state').textContent;\n"
            "out.cloud = [cloudData().out.levels[0].step.text, cloudData().out.levels[0].dips];\n"
        )
        self.assertEqual(got["hdr"], "cloud: conflict", "both changed tank A's row: no safe merge")
        self.assertIn("changed the same level or tally", got["msg"])
        self.assertEqual(got["cloud"], ["?", [1800, 1800]], "the cloud keeps B's reading and A's old step")

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
