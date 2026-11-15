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

1. **Pour.** Tap *+1 can poured* each time a can is empty, then press
   *Batch done* (see *A batch of cans* below). For a meter or an unknown pour,
   open *Enter litres instead*. Tick *whole pour unknown* for `?`, or *plus an
   unknown extra* for `N+?`. Tick *reached the neck / overflowed* for the last
   pour.
2. **Wait.** The settle timer on the dip card counts down the settle time
   (5:00 unless you change it) and rings when the level is ready to dip
   (§3.5).
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

## A batch of cans

A level often needs more than one can: 1200 L with a 200 L can is six cans,
then one dip. The can count is the weak point. One can too many or too few is
a pour error of a full unit, and the level that could show it is gone after
the next batch.

- **Tap when each can is empty.** The page shows the count, the litres and the
  time of each can. The count is saved after each tap, so a closed page or a
  locked phone does not lose it.
- **One size per can.** *Can size for the next can* sets the size of the next
  tap, so one batch can mix sizes: 2 × 200 L then 4 × 100 L. The buttons below
  the field give the sizes already used and the default from the setup. The
  default can size is optional: with none set, enter the size of the first
  can and the buttons follow. After a reload the field starts at the last
  can's size.
- **The advice is a target, not a limit.** The page shows the advised number
  of cans for a rise of about 30 mm. It warns near the brim, and when the
  batch is more than the gap that is left in the shell.
- **A second tap in less than 20 s** asks if it is a new can.
- **Undo last can** removes one tap. *Undo last entry* does the same while a
  batch is open. After *Batch done*, *Undo last entry* opens the batch again
  with its cans.
- **Last can not fully poured** records the batch as `N+?`: the full cans are
  known, and the shell estimates the part can. The part can is the last tap,
  so tap it with its own size.
- **Batch done** closes the batch and starts the settle timer from the last
  can. The raw file keeps the count and the times in the note, for example
  `cans 6x200 L 14:02-14:19`, or `cans 2x200+4x100 L` for a mixed batch.

After the dip, a confirmed miss of a whole number of cans names the count
error: *the miss is 0.99 can of 200 L: 1 can more than the count (7, not 6)
explains it*. Count the empty cans before the next pour. If the count was
wrong, press *Recount: edit pour*. The message appears only when the miss is
within a quarter can of a whole number and the changed count brings z below 2
(§3.10, §6.2). With mixed sizes the page tests each size in the batch and
names the one that fits.

## Timers and alarm

Open **Timers and alarm** at the bottom of the Live tab, enter the times, and
press *Save timers*. Write each time as `m:ss` (`1:30`). A plain number is
minutes (`1.5` = 1:30).

| Setting | Meaning | Default |
|---|---|---|
| Fill (pump) time per can size | The time the pump needs to fill one can | blank: no timer for that size |
| Alarm lead before full | The alarm rings this long before the can is full | 15 s |
| Settle (idle) after a batch | Wait before the first dip (§3.5) | 5:00 |
| One dip and its entry | Only used for the time estimate | 1:00 |
| pour animation | The hose, the can and the tank drawing in the timer | on |
| sound, vibrate, keep the screen on | Device settings: they stay on this phone | all on |

The page warns when the settle time is less than 5 minutes.

**Fill timer.** The timer is for the pump, not for the drain. Press *Start
fill timer* when you start the pump. The hose fills the can and the clock
counts down. *+20 s* and *−20 s* change this one run. Untick *pour animation*
to drop the drawing: the clock, the bar and the alarm stay.

| Time left | Panel | Alarm | Do |
|---|---|---|---|
| more than the lead | blue, *Filling a 200 L can* | — | watch the can |
| the lead or less | amber, *15 s to full: close the valve now* | two beeps | close the valve |
| 0:00 | green, *Can full: the pump must be off* | three beeps every 2.5 s for 3 min | pump off, tap *+1 can poured* |

The lead is the time from the alarm to the closed valve, not a safety margin.
If you close faster than the lead, every can is short by that difference, and
the calibration reads it as a loss at every interval. Time yourself once:
alarm to valve closed. 15 s of a 90 s fill is 33 L of a 200 L can, so the lead
must be right.

The timer does not count the can. Tap *+1 can poured* when the can is full.
That tap is the record, and it also stops the timer and the alarm. Emptying
the can into the tank has no timer.

**Settle timer.** *Batch done* starts the settle timer from the last can.
The dip card counts down and rings once when the level is ready to dip.

**Time to half and to the brim.** The Now card shows how long it takes to
reach half of the capacity and the brim, the clock time when you will be
done, and the levels and cans that are left. Each level takes the advised
number of cans for a rise of about 30 mm, so near the brim the levels get
smaller. A milestone is done when the first level at or above it is dipped.
The estimate follows the running shell and has no time for extra dips, so
early in the campaign it can be off by several levels.

**Cycle time from the taps.** The gap between two taps of the same size in
one batch holds the fill, the carry and the drain. The page takes the median
of those gaps and uses it for the estimate, because that is the time one can
costs the campaign. It cannot give the fill time alone, so it never feeds the
timer.

Sound starts only after a tap on the page. *Test alarm* checks the volume.
The timers never go into the raw file or the fit.

### Keep the screen on

A locked phone stops the page, its timers and its alarm. With *keep the screen
on* ticked, the page asks the browser to keep the screen on for as long as the
campaign is open and the page is visible. A line under the setting says if it
works on this phone.

| Line | Do |
|---|---|
| kept on | Nothing. |
| open the page over https | Use the published https address, not a copy of the file. |
| this browser cannot keep it on | Use a recent Chrome (Android) or Safari (iOS 16.4 or later), or set the phone timeout (below). |
| the phone refused | Turn off the battery saver or Low Power Mode. |

The screen turns off again if you switch to another app or press the power
button. Come back to the page and it asks again.

If the browser cannot keep the screen on, set the phone instead, for the
campaign only:

- **Android:** Settings → Display → Screen timeout → the longest time. With
  the phone on a charger, Developer options → *Stay awake* keeps it on.
- **iPhone / iPad:** Settings → Display & Brightness → Auto-Lock → Never.
  Guided Access (Settings → Accessibility) also keeps the phone in the page.

Set it back after the campaign. A screen that stays on uses the battery, so
keep a charger or a power bank near the tank.

## Charts during the campaign

The **Log & charts** tab shows four charts. Tap a button above the chart, or
swipe the chart left or right, to change the chart.

| Chart | What it shows | What to look for |
|---|---|---|
| Miss | Reading minus predicted level, at the time of the dip, with its ±2σ bar | Points outside the ±3 mm lines |
| Slope | Pour ÷ rise for each interval, on the slope line of the running shell | A point off the smooth line: a wrong pour count or a wrong dip |
| Drift | Running sum of the residuals, with the ±3σ√n band (§10 DRIFT) | A spike that returns = one misread dip. A step = one event. A ramp = stop and audit (§6.6) |
| z alarm | z = residual ÷ σ for each interval, with the ±2 and ±3 lines | Points outside ±2 (CHECK) or ±3 (ALARM) |

Slope, Drift and z alarm use the running shell as it is now. Thus they can
differ from the z in the Levels table, which is the z at the time of the dip.
An unknown pour and an overflow reading have no point on these charts.

The **Levels** table lists every level. Its note cell has an *Edit* button:
correct a typo or add what you learned after the pour. *Save* keeps the new
note and *Cancel* leaves the old one. The note goes into the raw CSV with its
level. The site's own markers, such as *pour edited on site* and *accepted
against the check*, stay apart from the note: an edit cannot erase them, and
the cell shows them before the note in grey.

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
