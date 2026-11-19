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
| Conflict | Someone else saved first (409). The page merges both people's work when that is safe; otherwise nothing is overwritten and you choose. |

## Use it on site

1. Open **Files → Cloud**.
2. Enter the workspace, the secret keyword and your name. Press **Log in**.
   Leave **Server address** blank on the hosted page. On the local file
   (`calib_site.html`), enter the address of the hosted page.
3. With **upload new campaigns to the cloud** on, each new campaign goes to
   the cloud. **Upload this campaign** sends the one that is open now.
4. Work as usual. Each entry saves in the browser. About 1.5 s later it
   uploads; when the page goes out of view first (the phone locks, the
   Shortcuts timer opens), it uploads at once. The header shows `cloud: saved`, `cloud: waiting` (offline),
   `cloud: log in`, `cloud: conflict`, `cloud: deleted` (someone deleted the
   campaign; your copy stays) or `cloud: other workspace` (you are logged in
   to a workspace that does not hold this campaign). For the last two,
   **Upload as a new cloud campaign** puts your copy in this workspace.
5. On another device, log in to the same workspace, press **Sync now**, and
   **Open** the campaign. That device follows the campaign: while the page is
   in view, it asks every 10 s, and at once when it comes back into view, and
   gets the newer version while it has no changes of its own. A question that
   finds nothing new sends no campaign data.

### Offline

No network: every entry stays in the browser, and the header shows
`cloud: waiting`. When the network is back, the page uploads the changes as
one save. The page also tries again every 10 s.

**A weak network.** An upload is the whole campaign, about 1.5 KB per level
as text. The page sends it gzipped, about a fifth of that (a browser without
`CompressionStream` sends the text), and gives a large upload more time: 15 s
plus 1 s per 4 KB. At 64 kbit/s, 100 levels upload in about 4 s instead of
20 s. The server knows a gzip body by its first two bytes, and its size limit
holds for the unpacked text too.

You can close the campaign or open another one while changes wait. The
closed campaign goes to the archive as usual, and its changes wait in an
outbox in the browser. They upload at the next sync. If someone else saved
that campaign first, nothing is overwritten: the page tells you, and opening
the campaign from the archive shows the same choice as below.

When an upload reaches the cloud but its answer is lost (a weak network), the
page knows its own save at the next try. That is not a conflict.

Switching between tank A and tank B of a transfer is a view on one device. It
is not a change to the campaign, and other devices keep their own view.

### Two writers of one campaign

Many people can each run their own campaign at the same time, and many can
watch one campaign. Two people can also **write** into one campaign: on site,
one person counts the cans on a phone while another dips and enters the
readings on a second phone. The two roles take turns, so only one device writes
at a time in the normal flow.

When the second save finds that another device saved first (409), the page
**merges**: it takes the cloud copy and replays this device's own actions on
it (each tap, dip, note, recount, Dip again, finish), through the same code
that made them. The result goes up as the next version, and both people's work
stays. The page says `Merged with Binh's changes at 10:42.`

The replay is accepted only when neither person's work changes:

1. every part of the cloud copy that this device's actions did not touch is
   byte-identical in the merged copy;
2. every row and the can tally that this device's actions made or changed is
   byte-identical to this device's copy;
3. the link's list of actions explains this device's copy.

Otherwise the user gets the conflict choice, as before, with a short reason:

- **Take the cloud copy.** Your copy goes to the archive (Files), so nothing
  is lost. Opened from the archive again, it still shows the conflict: it
  never overwrites the cloud copy.
- **Keep mine as a new cloud campaign.** The cloud then holds both.

The merge is refused, for example, when both people changed the same level
(one edits the pour after a recount while the other dips that level), when both
count cans in one tally, or when the other person removed a row. It also waits,
with no conflict shown, while a note is being typed, while another tab of the
page changed the session, or when a change lands during the sync; the next
10 s tick tries again.

What the merge keeps:

- Only the open campaign merges. A closed campaign whose changes wait in the
  outbox keeps the choice.
- A transfer merges by the same path, one tank at a time; each device keeps
  its own tank view.
- An action that cannot be replayed (Undo, Reopen, a new campaign, the Settings
  and Timers forms) makes the list not replayable until the next saved
  upload: such a save keeps the choice.
- An upload whose answer was lost may have reached the cloud. If the cloud has
  moved on in a way the page cannot tell apart, it keeps the choice, so no tap
  or dip goes in twice.
- A third device that saves during the upload gives one more 409 and one more
  replay, up to three tries; after that the choice stays.

**Files → Cloud** has the merge switch (`merge two writers of one campaign`,
on by default: off gives the choice every time, with no deploy needed), the
**Merge log** (the last 20 merges and refusals with their reason, which shows
which rule refuses most on site), and **Restore my copy from before the
merge** (the copy this device held before its last merge; it then goes through
the normal choice).

For two tanks at once, use one transfer campaign on one device (§3.12), or one
campaign per tank.

### The fill timer on every device

The devices on one campaign share the fill timer that runs now. When one
person presses *Start fill timer*, the other devices show the same countdown
and ring their own alarms at the same moment: *Close the valve* and *Can
full: pump off*. *Stop timer*, *+20 s*, *−20 s*, *+1 can*, *Batch done* and
*Poured* on any device change it on all. The timer card of a timer from
another device says *Started by Binh.*

| What | How |
|---|---|
| Upload | At once after the change, with keepalive when the page is hidden. |
| Follow | Every 10 s; every 3 s while a fill timer runs. A question that finds nothing new sends no timer. |
| Two changes at once | The later change wins (by the time of the change, not of the upload). An offline stop that comes in late does not undo a newer start. |
| Clocks | Every timer answer has the server's clock. Each device turns the start time into its own clock, so phones whose clocks differ by some seconds ring together. |
| Campaign data | None. A timer change is no new version: it never gives a merge, a conflict or an upload of the campaign. |
| Late join | A device that opens the campaign during a run shows it and rings the alarm of the state the run is in now. It does not ring when the can was full more than 3 min before. |
| iPhone timer | Only the device that started the timer runs it. The other devices ring with the page. |

The timer starts in the cloud after the campaign's first upload. A timer that
runs before the login goes up when the cloud has none for that campaign.
Only the open campaign shares its timer. The settle timer needs no sharing:
it runs from the batch's pour time, which is campaign data.

A server without the `timers` table (the schema was not applied after an
update) answers 500 to the timer calls. The timer then stays on each device
and the page tries again. Run `make db-schema`: it adds the table and keeps
the data.

The merge adds these keys to the browser's storage: the action list and a
fingerprint of the base version inside `calib-site:link` (about 20 bytes per
row, tens of bytes per action, at most 500 actions), `calib-site:premerge`
(one copy of the session, from before the last merge) and `calib-site:merges`
(the last 20 results).

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
| Page headers | `site/_headers`: CSP with `script-src` set to the SHA-256 hash of each inline script of the page (no `'unsafe-inline'`: an injected script does not run), `connect-src 'self'` and `worker-src 'self'` (the offline copy), no framing, no referrer. `calib site-page` (`make site`) writes the hashes; `--check` and the tests fail when they are stale. |
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
makes about 2 requests per minute, and every 3 s for 2 minutes after a newer
version from another device came in (about 20 per minute in that window).
While a fill timer runs, each device asks for the timer every 3 s (about 20
per minute): a device that runs timers for 10 hours makes about 12 000
requests a day.

## Firewall (Cloudflare zone)

These rules are set in the Cloudflare dashboard (Security → WAF) for the zone
of the page. Each rule applies only to the page's host name, so other sites in
the zone do not change. They run before the Worker, so a blocked request costs
no Worker request and no D1 read.

A new static file in `site/public/` needs its path in the first rule, or the
custom domain answers 403 for it (the workers.dev address has no such rule).
`/sw.js`, the offline copy, was added for that reason.

| Rule | Phase | Expression (`<HOST>` = the page's host name) | Action |
|---|---|---|---|
| calib: serve only the page and the API | custom | `http.host eq "<HOST>" and not (http.request.uri.path in {"/" "/index.html" "/sw.js"} or starts_with(http.request.uri.path, "/api/"))` | block |
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
`make site`: it builds `site/calib_site.html`, writes the script hashes into
`site/_headers`, and copies both into `site/public/`. Commit them all.

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
| `GET /api/campaigns/:id/timer` | `?have=REV` (optional) | `{rev, timer, changed_at, updated_by, now}`, or `{same: true, rev, now}`; no timer yet: `{rev: 0, timer: null, now}` |
| `PUT /api/campaigns/:id/timer` | `timer` (`{run, start, dur, size, lead, early}` or `null`), `at` (the time of the change) | `200 {rev, changed_at, now}` · `409 {current}` (a later change is there) · `404` |
| `GET /api/health` | — | `{ok: true}` |

## Files

| File | Role |
|---|---|
| `worker/index.js` | The Worker: routes, auth, limits |
| `worker/schema.sql` | The D1 tables (`timers`: the shared fill timer) |
| `site/cloud.js` | The page's client: login, link, the action list, sync, the merge, conflict, poll, the shared fill timer (inlined in the page) |
| `site/_headers` | Security headers for the hosted page |
| `site/sw.js` | The hosted page's offline copy (service worker, copied to `site/public/`) |
| `tests/test_cloud.py` | Tests: the Worker on an in-memory SQLite D1, the client, two page devices, the merge, a seeded two-writer stress run and the shared fill timer |
| `tests/test_secrets.py` | No `.env` value or server code in the page or in git |
| `tests/cloud_harness.mjs` | Runs the Worker under Node (`node:sqlite`, Node 22.5 or newer) |
