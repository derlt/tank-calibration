# On site: the live dip check

`site/calib_site.html` checks each dip **before you pour the next can**. It
answers one question: is this reading good, or must I dip again? After the next
pour, that level is gone. The method is §10a of
[CALIBRATION_METHODOLOGY.md](../CALIBRATION_METHODOLOGY.md).

The page is one file. It runs offline in the browser of a phone, a tablet or a
laptop. It needs no network and no install. It saves the session in the
browser after every entry.

## Get the page

The built page is in the repository: `site/calib_site.html`. Copy that one file
to the device and open it in the browser.

To build it again after you change `site/page.html` or `site/site_core.js`:

```bash
uv run python -m calib site-page                 # writes site/calib_site.html
uv run python -m calib site-page -o C:\tank-data\calib_site.html
uv run python -m calib site-page --check         # fails if the built page is stale
```

## Publish on Cloudflare Workers

The page also runs from a URL, as a Worker with static assets:

```bash
make deploy          # check, build site/public/index.html, upload
make deploy-dry      # the same, but stop before the upload
```

The first deploy needs a Cloudflare login: run `npx wrangler login` once, or
set `CLOUDFLARE_API_TOKEN` in the environment. The Worker is
`tank-calibration-site` (`wrangler.jsonc`). Its addresses are in `.env`, which
is not committed; the custom domain is attached once in Cloudflare and is not
part of the repository.

The hosted page still works offline after it loads: it makes no network
requests. To keep the one file on a phone, use `site/calib_site.html`.

## Before the first pour

| Field | What to enter |
|---|---|
| Diameter estimate D | Brim-to-bottom with the tape, or the drawing. |
| D is good to ± | Your honest limit. ±200 mm is acceptable: the data take over within a few pours. |
| Length estimate L | Outside length minus the end plates. |
| L is good to ± | Leave blank for ±3 %. |
| Pour unit | Can size or meter step, L. The pour advice rounds to it. |
| Reading repeatability σ | From a repeat study (below). Default 0.4 mm. |
| Pour noise | From the can calibration (§3.1). Default 0.5 % + 3 L. |
| Datum | 0 ± 80 mm unless you sounded the bottom. |
| First level | The heel volume (or `?`) and the first reading. |

Every ± means "the truth is almost surely inside" (2σ).

### Repeat study: measure σ once per tape and team

Fill the tank to one level and let it settle. Dip 20–40 times without pouring,
and record every reading. The standard deviation is σ. A good team with a good
tape gets 0.2–0.4 mm. Do not use the §9 interval σ (about 1–1.5 mm) here: that
σ includes pour noise, and with it a 3 mm slip passes as "agreement".

## Each pour

1. **Pour.** Enter the litres. Tick *whole pour unknown* for `?`, or *plus an
   unknown extra* for `N+?`. Tick *reached the neck / overflowed* for the last
   pour.
2. **Wait.** The page shows the time since the pour. Let the level settle at
   least 5 minutes (§3.5).
3. **Dip.** Enter the reading and press *Check*.
4. **Read the verdict.**

| Verdict | Meaning | Do |
|---|---|---|
| **Reading good** (green) | Inside the predicted band. | Pour the next can. |
| **Check this reading** (amber) | The reading misses the prediction. | Dip again. The page hides your first reading and the prediction, so they cannot bias the second. |
| **Second reading needed** (amber) | No prediction can test this level: the first level, an unknown pour, or a band too wide to catch a 3 mm slip. | Dip again. |
| **Readings do not agree** (amber) | The readings differ by more than about 1.4 mm. | Dip again. If the readings move in one direction, the level is not settled: wait 5 minutes. |
| **Reading confirmed** (green) | Two readings agree, and the level is inside the band. | Pour the next can. |
| **Shape still unknown** (blue) | Two readings agree, but the first 3 intervals are still teaching the bottom shape. | Pour the next can. |
| **Watch item** (blue) | Two readings agree; the miss is below the action bar. | Pour the next can. |
| **The pour or the tank is off** (red) | Two readings agree and the miss is at the action bar. The dip is good. | Count the cans of this pour again. If the count was wrong, press *Recount: edit pour*. If it was right: OBJECT? or LOSS?, see the message. Pour the next can. |

*Accept anyway* keeps a level against the check. Its interval stays out of the
running fit and the note says so. *Undo last entry* removes the last reading,
or the last pour when it has no reading.

## After the campaign

1. *Files → Download raw CSV* gives `TANK_raw.csv`: one row per level with the
   adopted reading (the mean of the two readings that agree). The note holds
   every reading and the live state. *Download session JSON* keeps the full
   session, the times included.
2. Run the normal pipeline:

   ```bash
   uv run python -m calib init TANK_raw.csv --r <D/2> --L <L>
   uv run python -m calib fit TANK.json -o TANK_out
   ```

The running shell on the page is a tool for the live check. It is not the
adopted shell: the full fit makes the deliverable.

## Check the page on old data

*Replay* runs an old raw CSV through the check, as if each level were dipped
now. When the check asks for another reading, the replay repeats the recorded
reading: the answer that a correct reading gives. The same is available from a
terminal:

```bash
node site/replay.js examples/demo_raw.csv --D 1760 --L 2950 --unit 50 --overflow 22
node site/simulate.js --runs 200       # detection rate for slips of 1–10 mm
```

## Files

| File | Role |
|---|---|
| `site/site_core.js` | The rules and the maths. One source for the page and the tests. |
| `site/page.html` | The page template. |
| `site/calib_site.html` | The built page. Copy this file to the device. |
| `site/replay.js` | Replay a raw CSV from a terminal. |
| `site/simulate.js` | Detection-rate study on synthetic campaigns. |
| `tests/test_site.py` | Build check; with Node: geometry against Python, demo replay, session rules, detection rate. |
