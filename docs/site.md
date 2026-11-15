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
| Reading repeatability σ | **Settings → Noise and limits**. From a repeat study (below). Default 0.4 mm. |
| Pour noise | **Settings → Noise and limits**. From the can calibration (§3.1). Default 0.5 % + 3 L. |
| Datum | **Settings → Noise and limits**. 0 ± 80 mm unless you sounded the bottom. |
| Fill or drain | *Fill: pour in* (default), *Drain: pump out*, or *Two tanks: pump A → pour B* (below). |
| First level | The heel volume (or `?`) and the first reading. A drain also asks where the first level stands. |

Every ± means "the truth is almost surely inside" (2σ).

### Repeat study: measure σ once per tape and team

Fill the tank to one level and let it settle. Dip 20–40 times without pouring,
and record every reading. The standard deviation is σ. A good team with a good
tape gets 0.2–0.4 mm. Do not use the §9 interval σ (about 1–1.5 mm) here: that
σ includes pour noise, and with it a 3 mm slip passes as "agreement".

## Settings

The **Settings** tab holds every number the check uses, in three cards:

| Card | Holds | When |
|---|---|---|
| This campaign | Tank name, D, L, pour unit and their ± | After the first level |
| Noise and limits | Reading σ, pour noise, datum ±, brim ± at the neck entrance (drain) | Before or during a campaign |
| Timers, alarm and device | Settle and dip times, fill time per can, alarm lead, animation, sound, vibration, screen | After the first level |

The noise card is also the draft for the next campaign: change it before you
start, and *Start campaign* uses it. A change during a campaign refits the
running shell from the levels already accepted and moves the z of every new
check (§9.1). The levels keep their state; the next pour uses the new numbers.

A change of the noise also restarts the noise scale. Each earlier z was formed
with the old σ, so those rows keep their z but no longer set the scale; new
rows set it again. Without this, a corrected σ would count twice.

The campaign card corrects a wrong tank record after the first level: a typo
in D or L is fixed here, not by starting again. A change refits the running
shell; the accepted levels stay accepted. Leave *L is good to ±* blank to take
the 3 % default from the L you enter, so a corrected L also gets a new limit.

The timers and device settings are operator settings, not data: they never
enter the raw file or the fit.

## Each pour

The Live tab has two modes. Use the *Simple · Verbose* switch at the top of
the tab; the device keeps your choice. **Verbose** (the default) shows every
explanation. **Simple** shows only what to do and the numbers to read:

- the level, and the next pour with the level to expect:
  `Next: 2 × 200 L → expect 531.4 ± 2.3 mm`;
- the can target (`Target: 2 × 200 L`) and every warning (brim, bottom,
  overflow, drift alarm);
- a short settle line (`Settling: 3:20 left.`, `Settled: dip now.`) and the
  expected level in the dip panel (`Expect 572.8 ± 3.3 mm`);
- each verdict as its title and its action, without the numbers behind it.

Simple mode hides the help paragraphs, the shell figures (liquid, brim,
slope), the time-to-brim block and the drift line until it alarms. The check
is the same in both modes: only the text changes.

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

**The Now card previews the pour.** As you tap cans or enter litres, the Now
card shows the level that pour must give, for example
`After this pour (400 L): 486.0 mm ± 8.7 mm (2σ) · +86.0 mm rise · ≈ 1663 L
· too wide to judge: expect two readings`. Use it to choose the pour size: a
large pour has a wide band, and a band wider than 3 mm (2σ) means the check
will ask for a second reading. A part can, an unknown pour and an overflow
have no prediction. The line is empty while a level waits for its dip. The
litres field clears after a pour, so a repeated manual pour needs the value
again, or *Use advice*.

The line shows the expected level **before** the dip, so it weakens the blind
repeat (§10a.6). The page hides the check's own prediction while a level is
pending, but it cannot hide a number already read. If the dip must stay blind,
do not read the line before you dip.

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

Open **Settings → Timers, alarm and device**, enter the times, and press
*Save timers and device*. Write each time as `m:ss` (`1:30`). A plain number is
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

The table and the chart select one level together. Tap a row: the row gets
a yellow background, and its mark in the chart gets a dark ring and a dashed
vertical line. Tap a mark: its row is selected in the same way, and the
table scrolls to it. Tap the same row or mark again, or an empty part of
the chart, to clear the selection. The selection stays when you change the
chart. A level with no mark in the chart now shown (the first level, a
pending level, an unknown pour) says so in the line under the chart. The
*time* column gives when the pour ended and when each reading was taken.

## Drain campaign (reverse strapping)

A drain campaign runs the calibration from the top down. The tank is full of
water at the start. A pump draws the water out into calibrated cans. Each
batch of cans is one step, and the level falls from the brim (or the neck) to
the bottom. Use it when the tank is already full, when filling from the bottom
is not possible, or to check a fill campaign in the other direction.

Choose **Drain: pump out** on the *New campaign* card. The direction is fixed
for the whole campaign: Settings shows it but cannot change it. The step
volumes stay positive: they are the litres pumped out. The raw file keeps the
same three columns, and the heights fall.

### Where the first level stands

| Choice | When | What the page does |
|---|---|---|
| **At the neck entrance** (recommended) | Pump the neck down until the level just reaches the shell crown. Then dip. | The reading is the brim `B` (§5.3a). The running shell takes `2r + h0 = B ± 6 mm` (2σ) from the first level. Change the ± under **Settings → Noise and limits**. |
| In the neck | The level is in the neck. | The reading is vent-column height, not shell level. Tick *level still in the neck* on each drain while the level stays in the neck. |
| In the shell | The level is below the brim. | A plain start: only D, L and the datum teach the shape. |

Use the neck entrance when you can. The reading is the brim itself, so the
running shell knows the top before the first interval. In the simulation
below this catches more slips and gives fewer false alarms than a plain shell
start.

A neck level, and the first shell level after it, have no prediction. Each
needs two readings, and the verdict is **Neck reading recorded** or **Neck
interval recorded** (blue). Their intervals span the neck. They feed the brim
constraint `Vcap − F(H) ≤ P` of the final fit (§5.3a) and stay out of the
running fit. The next level is checked against the first shell level as
usual.

The first row's step is `?`: the volume in the tank is not known. If you
metered the prefill, enter the litres.

### Rules for a drain

- **Prime the pump before the start reading.** Fill the pump and the hose
  first. Water that fills them after the first dip leaves the tank but not the
  record.
- **The hose rule.** The hose must be in the same state at every dip. Keep it
  always full (a check valve at the suction end), or always drained back into
  the tank before you dip. A hose that is full at one dip and empty at the
  next moves its volume between the tank and the record.
- **Fill each can to the calibrated mark.** A spill at the can is litres that
  left the tank but are not on the record.
- **The end.** Near the bottom the pump loses suction. The last can is then a
  part can: tap it, and tick *pump lost suction: last can part* (`N+?`).
  If you measure the part can, enter its litres instead. The pour advice warns
  when the level after the advised drain is within 60 mm of the bottom, or
  when less than 5 % of the capacity is left. A drain never halves near the
  brim.
- **After the drain.** Sound the bottom and record the heel. Inspect the empty
  tank: an object seen on the bottom or on the wall explains an `OBJECT?`.

### The signs in a drain

The residual is still `resid = s − pred` (§2), with `pred = F(H_before) −
F(H_after)`. The meaning of each sign changes with the direction:

| Sign | Fill | Drain |
|---|---|---|
| `resid < 0` | the rise came too cheap: OBJECT? or an under-recorded pour | the fall came too large: OBJECT? or LEAK? or an under-recorded drain (a spill at the can counts here) |
| `resid > 0` | the rise came too small: LOSS? or an over-recorded pour | the fall came too small: RETURN? (the hose drained back, wall film) or an over-recorded drain |

A leak now gives `resid < 0`, not `resid > 0`. The pair rule keeps the meaning
of `δ` (recorded − true): the page computes `δ = dir·(r2 − r1)/(2m)`, so a drain
gives the same `δ` as a fill.

The Now card shows the drain, for example
`After this drain (400 L): 486.0 mm ± 8.7 mm (2σ) · −86.0 mm fall · ≈ 1663 L
left`, and the time to half and to the bottom. The charts and the Levels table
work for a falling level: the points run from right to left.

### Simulation

`node site/simulate.js --runs 200 --deltas 3,4`, then the same with `--drain`
and with `--drain --start shell`. The drain run starts at the brim (true brim +
reading noise) and drains the fill schedule in reverse. `--start shell` takes
the same first reading as a plain shell start, without the brim prior. One
reading per run is slipped by δ.

| Campaign | Slip | Caught | Kept > 1.5 mm off | Extra dips at honest levels | False ALARM | mean \|Δr\| | mean \|ΔL\| |
|---|---|---|---|---|---|---|---|
| Fill | 3 mm | 92 % | 8 % | 3.8 % | 0.10 % | 2.0 mm | 13.3 mm |
| Fill | 4 mm | 99 % | 1 % | 4.2 % | 0.04 % | 2.0 mm | 12.8 mm |
| Drain | 3 mm | 91 % | 9 % | 2.4 % | 0.16 % | 1.2 mm | 8.6 mm |
| Drain | 4 mm | 99 % | 1 % | 2.5 % | 0.03 % | 1.2 mm | 8.6 mm |
| Drain, shell start | 3 mm | 88 % | 13 % | 2.8 % | 0.51 % | 1.3 mm | 9.1 mm |
| Drain, shell start | 4 mm | 99 % | 2 % | 3.1 % | 0.38 % | 1.2 mm | 8.5 mm |

σr 0.4 mm, pours 0.5 % + 3 L, D ± 200 mm, seed 1. The brim prior of the
neck-entrance start catches more 3 mm slips (91 % against 88 %) and gives
fewer false alarms (0.16 % against 0.51 %): the early checks know the top.
The final running shell is about the same with either start.

## Two tanks at once (transfer)

Choose **Two tanks: pump A → pour B** to calibrate two tanks with one water.
A pump draws known volumes out of the full **tank A** into calibrated cans,
and the same cans are emptied into **tank B**. Tank A is a drain (see above);
tank B is a fill. One batch of cans is one step for both tanks: A falls, B
rises. The method is §3.12 of the methodology.

The setup asks for both tanks: A's record (it is a drain, so the start-level
choice applies to A) and B's record with its heel. Both first levels are
dipped before the first batch, two readings each. Then each batch is: pump
cans from A → *Batch done* → empty the cans into B → dip A → dip B. The dip
card has **one field per tank** and one button per tank: *Check alpha*
submits A's reading, *Check beta* submits B's. Each button reads only its
own field, so you can check one tank now and the other later. A decided
tank's field and button are closed; *Take another reading* re-opens it. The
two fields sit in their own tinted cards, under a **Same batch** header,
with a tank pictogram that shows the level and the arrow direction, a large
arrow watermark in the input, and a role legend line. Each field carries its
role: a **↑ pump out** badge on A's field and a **↓ pour in** badge on B's,
with the input edge in the same colour. The arrow follows the water: out of
the underground tank is up, into it is down.

Each tank keeps its own check, its own running shell and its own raw file.
The header's **Current tank** switch names each tank with its role
(`alpha · out`, `beta · in`). It selects the tank that the Log & charts,
Shell and campaign cards show, and the tank that *Take another reading* and
*Accept anyway* apply to; the Live tab marks the current tank. The switch
hides on Replay and Help, where it changes nothing. The Log & charts tab
carries the same switch, and its table and chart are always the named tank's
own (A's table reads *drained L*, B's *pour L*). The Live tab always shows
both tanks. *Files* exports one raw CSV per tank.

**The pair view.** When both dips of a batch are in, the page compares the
two residuals of the same batch — but only on levels the prediction test
decided: a recount to `?`, an override, or a neck or overflow reading leaves
no comparable residual, and the finding leaves with it. The cans are shared,
so a pour error shows the same litres in both tanks, and the pour noise
cancels in the difference:

| The two residuals say | Cause | Do |
|---|---|---|
| the same litres, both at the action bar | the cans: a miscount, or a can not filled to its mark | Count the cans again. *Recount: edit pour* edits both tanks at once. |
| litres that only B misses, A clean | liquid lost on the way: a spill at the carry, a can not emptied | Check the path and the cans. B's interval goes to the register (LOSS?); A's is good. |
| only A shows it | A's side: the hose, the pump seal, a spill at the can (LEAK? / RETURN?) | Check the hose state. A's interval goes to the register; B's is good. |
| only B shows it, rise too cheap | an object in B in this band (OBJECT?) | Inspect B, or repeat a pour into it (§6.2). A's interval is good. |
| both at the bar, different litres | superposed causes | Decompose before correcting either tank (§6.2). |

A wide check on one side can confirm nothing: the page says so instead of
guessing, and a recount of the cans always comes first, because one edit
fixes both files. The finding goes into the note of both raw files, for
example `transfer: shared pour error`.

The batch advice takes the tighter of the two 30 mm targets, and warns for
both limits at once: A's bottom (the pump may lose suction — tick *pump lost
suction: last can part*) and B's brim (tick *tank B: reached the neck* on the
final batch). The campaign ends when A is empty or B is full, whichever
comes first. The noise, the cans and the timers are one set for both tanks
(§9.1).

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
node site/replay.js TANK_raw.csv --D 2480 --L 5280 --drain --neck-entrance   # a drain
node site/simulate.js --runs 200       # detection rate for slips of 1–10 mm
node site/simulate.js --runs 200 --drain
```

A drain replay takes `--drain`, `--neck ROWS` (the rows that are neck levels,
for example `1,2`) and `--neck-entrance` (row 1 is the brim reading). Without
`--drain`, the replay finds a drain from falling heights and says so. The
*Replay* tab has the same options.

## Files

| File | Role |
|---|---|
| `site/site_core.js` | The rules and the maths. One source for the page and the tests. |
| `site/page.html` | The page template. |
| `site/calib_site.html` | The built page. Copy this file to the device. |
| `site/replay.js` | Replay a raw CSV from a terminal. |
| `site/simulate.js` | Detection-rate study on synthetic campaigns. |
| `tests/test_site.py` | Build check; with Node: geometry against Python, demo replay, session rules, detection rate. |
