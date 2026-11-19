# Cloud: share campaigns in a team

The on-site page can keep a copy of each campaign in the cloud, so that a team
can open it on several devices. This is optional. The page always saves in the
browser first, and it works without a network.

```
 phone A ──┐                          ┌── Worker /api/*  (worker/index.js)
 phone B ──┼── browser copy first ──► │      │
 laptop  ──┘   (works offline)        │      ▼
                                      └── D1 database  (worker/schema.sql)
```

## The idea in four words

| Word | Meaning |
|---|---|
| Workspace | A team space. Its name and its **secret keyword** are the login. |
| Campaign | One session of the page (one tank, or a transfer of two tanks). |
| Version | Goes up by one on each save. A save names the version it started from. |
| Conflict | Someone else saved first. Nothing is overwritten. You choose what to do. |

## Use it on site

1. Open **Files → Cloud**.
2. Enter the workspace, the secret keyword and your name. Press **Log in**.
   Leave **Server address** blank on the hosted page. On the local file
   (`calib_site.html`), enter the address of the hosted page.
3. With **upload new campaigns to the cloud** on, each new campaign goes to
   the cloud. **Upload this campaign** sends the one that is open now.
4. Work as usual. Each entry saves in the browser. About 1.5 s later it
   uploads. The header shows `cloud: saved`, `cloud: waiting` (offline),
   `cloud: log in`, `cloud: conflict`, `cloud: deleted` (someone deleted the
   campaign; your copy stays) or `cloud: other workspace` (you are logged in
   to a workspace that does not hold this campaign). For the last two,
   **Upload as a new cloud campaign** puts your copy in this workspace.
5. On another device, log in to the same workspace, press **Sync now**, and
   **Open** the campaign. That device follows the campaign: every 30 s it gets
   the newer version, while it has no changes of its own.

### Offline

No network: every entry stays in the browser, and the header shows
`cloud: waiting`. When the network is back, the page uploads the changes as
one save. The page also tries again every 30 s.

You can close the campaign or open another one while changes wait. The
closed campaign goes to the archive as usual, and its changes wait in an
outbox in the browser. They upload at the next sync. If someone else saved
that campaign first, nothing is overwritten: the page tells you, and opening
the campaign from the archive shows the same choice as below.

When an upload reaches the cloud but its answer is lost (a weak network), the
page knows its own save at the next try. That is not a conflict.

Switching between tank A and tank B of a transfer is a view on one device. It
is not a change to the campaign, and other devices keep their own view.

### One writer at a time

Many people can each run their own campaign at the same time. Many people can
also watch one campaign. But two people who **write** into one campaign at the
same moment get a conflict. The second save stops, and the page offers:

- **Take the cloud copy.** Your copy goes to the archive (Files), so nothing
  is lost. Opened from the archive again, it still shows the conflict: it
  never overwrites the cloud copy.
- **Keep mine as a new cloud campaign.** The cloud then holds both.

For two tanks at once, use one transfer campaign on one device (§3.12), or one
campaign per tank.

## Make a workspace

A new workspace needs the **signup code**. The person who runs the server keeps
it (see below). In **Files → Cloud → New workspace**, enter a workspace name
(3 to 40 characters: letters, digits, `-`, `_`), a secret keyword of 12
characters or more, your name, and the signup code. Then give the workspace
name and the keyword to the team.

Choose a long keyword, for example four random words. Anyone with the keyword
can read and change every campaign in the workspace. To change the keyword,
make a new workspace.

## Security

| What | How |
|---|---|
| Keyword | Stored only as PBKDF2-SHA256, 100 000 rounds, random salt. |
| Login | A random token for 30 days, stored only as SHA-256. **Log out** deletes it. |
| Who can make workspaces | Only people with the signup code (Worker secret `SIGNUP_CODE`). |
| Isolation | Every query is scoped to the workspace of the token. |
| Overwrites | None: a save with an old version gets a conflict (409). |
| CSRF | No cookies. The token goes in the `Authorization` header only. |
| Page headers | `site/_headers`: CSP with `connect-src 'self'` and `worker-src 'self'` (the offline copy), no framing, no referrer. |
| Delete | Soft: the row stays in D1 with `deleted_at`, so an operator can restore it. A save never brings it back: it gets 409. |

## Flood and abuse limits

| Limit | Value | Where |
|---|---|---|
| API requests per IP address | 300 per minute | rate limit binding `API_LIMIT` |
| Login and signup per IP address | 10 per minute | rate limit binding `AUTH_LIMIT` |
| Failed logins per IP address | 10 in 15 min, then locked to the end of the window | D1 table `fails` |
| Failed logins per workspace | 50 in 15 min, then locked | D1 table `fails` |
| Request body | 1 MB | Worker |
| Campaigns per workspace | 2000 | Worker |

The API answers only on the host names in `API_HOSTS` (from `.env`). The
`workers.dev` and preview addresses still serve the page, but their API answers
403, so every API call goes through the zone firewall below. On those
addresses the page works offline only.

Only `/api/*` runs the Worker (`run_worker_first`). The page is a static asset,
so an API flood does not stop the page from loading, and the page keeps working
offline. Cloudflare's network also blocks large floods before they reach the
Worker. A team on one phone hotspot shares one IP address: 300 per minute is
enough for about 30 devices.

Free plan limits (2026): Workers 100 000 requests per day; D1 5 GB, 5 million
row reads and 100 000 row writes per day. One device that follows a campaign
makes about 2 requests per minute.

## Firewall (Cloudflare zone)

These rules are set in the Cloudflare dashboard (Security → WAF) for the zone
of the page. Each rule applies only to the page's host name, so other sites in
the zone do not change. They run before the Worker, so a blocked request costs
no Worker request and no D1 read.

| Rule | Phase | Expression (`<HOST>` = the page's host name) | Action |
|---|---|---|---|
| calib: serve only the page and the API | custom | `http.host eq "<HOST>" and not (http.request.uri.path in {"/" "/index.html"} or starts_with(http.request.uri.path, "/api/"))` | block |
| calib: API methods | custom | `http.host eq "<HOST>" and starts_with(http.request.uri.path, "/api/") and not http.request.method in {"GET" "POST" "PUT" "DELETE" "OPTIONS"}` | block |
| calib: no crawlers on the API | custom | `http.host eq "<HOST>" and starts_with(http.request.uri.path, "/api/") and cf.client.bot` | block |
| calib: API flood limit per IP | rate limit | `http.host eq "<HOST>" and starts_with(http.request.uri.path, "/api/")`, 50 per 10 s per IP and data center, blocked for 10 s | block |

The Free plan also runs the Cloudflare Free Managed Ruleset and the L7 DDoS
ruleset on the zone; they need no setup. The Free plan allows one rate limit
rule, with a 10 s period and a 10 s block. 50 per 10 s matches the Worker's
own limit of 300 per minute.

## Secrets: where each one lives

| Value | Where | Never in |
|---|---|---|
| Signup code | `.env` and the Worker secret `SIGNUP_CODE` | the page, git, the API answers |
| D1 database id | `.env` (`D1_DATABASE_ID`); `make deploy` writes `wrangler.deploy.jsonc` (ignored by git) | `wrangler.jsonc`, the page |
| Host names | `.env` (`SITE_URL`, `WORKERS_DEV_URL`, `API_HOSTS`) | docs, git, the page |
| Keyword hashes, salts, token hashes | D1 only | every API answer: the queries name their columns, and none of these |

The page is one static file. It holds no server code, no SQL and no ids. The
site serves only `/` and `/api/*`; any other path (`/.env`, `/worker/…`) gets
403 from the firewall, or 404 from the asset store on other addresses.
`tests/test_secrets.py` checks this on each test run: no value from `.env` may
appear in the built page or in any file that git tracks or could track.

## Set up the server (once)

The Worker is `tank-calibration-site` in `wrangler.jsonc`. Its addresses and
the signup code are in `.env`, which is not committed.

```bash
npx wrangler@4 d1 create tank-calibration          # once; put the id in .env as D1_DATABASE_ID
# also in .env: API_HOSTS=<the page's host name>
make db-schema                                     # create the tables (safe to repeat)
npx wrangler@4 secret put SIGNUP_CODE              # the code that allows new workspaces
make deploy                                        # build the page, copy _headers, upload
```

To stop new workspaces, delete the secret: `npx wrangler@4 secret delete SIGNUP_CODE`.

### Build from git (Workers Builds)

The Worker is connected to the repository, and `site/public/` is committed,
so the build finds the assets directory. It is a copy of the built page:

    site/calib_site.html      the page for a phone (one file)
    site/public/index.html    the same bytes, for the Worker's assets
    site/public/_headers      the security headers
    site/public/sw.js         the offline copy of the page (site/sw.js)

A test fails when the copy is stale. After a change to the page, run
`make site`: it builds `site/calib_site.html` and copies it into
`site/public/`. Commit both.

The deploy still needs the D1 id, which stays out of git: the committed
`wrangler.jsonc` keeps the placeholder `D1_DATABASE_ID`, and a deploy with it
fails with `binding DB of type d1 must have a valid database_id specified`
(code 10021). So the dashboard sets (Worker → Settings → Build):

| Setting | Value |
|---|---|
| Build command | empty |
| Deploy command | `sh scripts/cloud-build.sh && npx wrangler deploy --config wrangler.deploy.jsonc --var API_HOSTS:$API_HOSTS` |
| Variables and Secrets | `D1_DATABASE_ID` and `API_HOSTS`, the values from `.env` |

Put the two variables in the **Workers Builds** section. The Worker's own
*Variables and Secrets* (Settings → Variables and Secrets) are runtime
values: the build cannot see them, and a `D1_DATABASE_ID` there does nothing
but add a Worker variable.

The script writes `wrangler.deploy.jsonc` with the id and refreshes the copy
from `site/calib_site.html`. A failed build deploys nothing: the live site
keeps the last good version.

## The API

All bodies are JSON. Send `Authorization: Bearer <token>` after the login.

| Call | Body or query | Answer |
|---|---|---|
| `POST /api/workspaces` | `workspace, keyword, user, signup_code` | `201 {token, workspace, user, expires}` |
| `POST /api/login` | `workspace, keyword, user` | `200 {token, …}` · `401` · `429` |
| `POST /api/logout` | — | `200` |
| `GET /api/me` | — | `{workspace, user, expires}` |
| `GET /api/campaigns` | — | `{campaigns: [{id, tank, levels, version, updated_at, updated_by, …}]}` |
| `GET /api/campaigns/:id` | `?have=N` (optional) | `{data, version, …}`, or `{same: true}` when you have version N |
| `PUT /api/campaigns/:id` | `data, base_version` (0 = new) | `200/201 {version}` · `409 {current}` (`current.deleted_at` set: deleted) |
| `DELETE /api/campaigns/:id` | `?base_version=N` | `200` · `409` |
| `GET /api/health` | — | `{ok: true}` |

## Files

| File | Role |
|---|---|
| `worker/index.js` | The Worker: routes, auth, limits |
| `worker/schema.sql` | The D1 tables |
| `site/cloud.js` | The page's client: login, link, sync, conflict, poll (inlined in the page) |
| `site/_headers` | Security headers for the hosted page |
| `site/sw.js` | The hosted page's offline copy (service worker, copied to `site/public/`) |
| `tests/test_cloud.py` | Tests: the Worker on an in-memory SQLite D1, the client, two page devices |
| `tests/test_secrets.py` | No `.env` value or server code in the page or in git |
| `tests/cloud_harness.mjs` | Runs the Worker under Node (`node:sqlite`, Node 22.5 or newer) |
