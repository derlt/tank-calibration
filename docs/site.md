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
set `CLOUDFLARE_API_TOKEN` in the environment. The dashboard's git build (Workers
Builds) deploys the committed `site/public/`; after a page change run
`make site` and commit both files, see
[cloud.md](cloud.md#build-from-git-workers-builds). The Worker is
`tank-calibration-site` (`wrangler.jsonc`). Its addresses are in `.env`, which
is not committed; the custom domain is attached once in Cloudflare and is not
part of the repository.

The same Worker runs the optional cloud store on D1 (`/api/*`): a team can log
in to a workspace with a secret keyword and share campaigns. See
[cloud.md](cloud.md). The deploy also needs the D1 database and the
`SIGNUP_CODE` secret; that page has the steps.

The hosted page still works offline after it loads. It makes network requests
only when you log in to the cloud, and every entry saves in the browser first.
To keep the one file on a phone, use `site/calib_site.html`.

## Before the first pour

| Field | What to enter |
|---|---|
| Diameter estimate D | Brim-to-bottom with the tape, or the drawing. |
| D is good to ± | Your honest limit. ±200 mm is acceptable: the data take over within a few pours. |
| Length estimate L | Outside length minus the end plates. |
| L is good to ± | Leave blank for ±3 %. |
| Brim reading | Optional. A **measured** tape reading at the brim (where the neck meets the shell), for example from an earlier campaign with the same tape and datum plate. Blank: the running shell computes the brim from D, L and the datum. |
| Brim is good to ± | The limit of that reading. Leave blank for ±6 mm. |
| Pour unit | Can size or meter step, L. The pour advice rounds to it. |
| Batch plan | Optional: the can sizes, the nominal capacity and the batches (see *The batch plan* below). Without a plan the page advises each pour for a rise of about 30 mm. |
| Reading repeatability σ | **Settings → Noise and limits**. From a repeat study (below). Default 0.4 mm. |
| Pour noise | **Settings → Noise and limits**. From the can calibration (§3.1). Default 0.5 % + 3 L. |
| Datum | **Settings → Noise and limits**. 0 ± 80 mm unless you sounded the bottom. |
| Fill or drain | *Fill: pour in* (default), *Drain: pump out*, or *Two tanks: pump A → pour B* (below). |
| First level | The heel volume (or `?`) and the first reading. A drain also asks where the first level stands. |

Every ± means "the truth is almost surely inside" (2σ).

### The brim reading

The brim B is a tape reading: the dip at the top of the shell, where the neck
starts. In the shell model B = 2r + h0, the diameter plus the datum offset.
A typed brim does three things:

1. **On the page.** The running shell takes 2r + h0 = B ± the typed limit, as
   a prior, from the first level. The brim on the Now card, the near-brim
   warning, the time to the brim, the batch plan and the tile's `≥` limit all
   follow it. The Now card says where it came from: `(typed 1830.0 mm)`.
2. **In the raw file.** Row 1 gets the note `brim 1830.0 ± 6.0 mm`.
3. **In `calib fit`.** `calib init` reads the note as `brim.declared`. The fit
   compares its own free brim with it and reports the difference, never
   enforces it (§5.3a): a wrong number cannot bend the shell.

A drain that starts at the brim measures the brim now. That start reading
wins: it is the prior, and the CSV keeps both notes. If the two differ by
more than √2 × the limit, the start verdict and the Now card say so. Check the
typed brim.

A wrong typed brim pulls the early predictions with it, because ±6 mm is a
strong prior. Type it only when it was measured. Change or clear it in
*Settings → This campaign*: the running shell refits.

### Repeat study: measure σ once per tape and team

Fill the tank to one level and let it settle. Dip 20–40 times without pouring,
and record every reading. The standard deviation is σ. A good team with a good
tape gets 0.2–0.4 mm. Do not use the §9 interval σ (about 1–1.5 mm) here: that
σ includes pour noise, and with it a 3 mm slip passes as "agreement".

## Settings

The **Settings** tab holds the display settings and every number the check
uses, in four cards:

| Card | Holds | When |
|---|---|---|
| Display | The language of the page (English or Tiếng Việt) and the theme (Auto, Light, Dark) | Any time |
| This campaign | Tank name, D, L, the brim reading, pour unit and their ± (in a transfer: the chosen tank) | After the first level |
| Noise and limits | Reading σ, pour noise, datum ±, suction floor (drain) | Before or during a campaign |
| Timers, alarm and device | Settle and dip times, fill and drain time per can, alarm lead, animation, sound, vibration, screen | After the first level |

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

### Theme

Choose the theme in **Settings → Display → Theme**. *Auto* (the default)
follows the phone: dark when the phone is in dark mode. *Light* and *Dark*
fix the theme. The device keeps the choice, and the page applies it before
it draws, so a dark choice never flashes light. Dark mode helps at night and
in a dark pump room; in strong sun, *Light* reads better.

Every colour of the page is a CSS variable with a light and a dark value, in
the `:root` block of `page.html`; the charts read the same variables when
they draw. `tests/test_site.py` fails on a colour written outside the
variables.

### Language

Choose the language in **Settings → Display**. The device keeps the choice;
the page reloads in the new language (the open session is saved). Without a
choice, a phone set to Vietnamese starts in Vietnamese, any other in English.

Only what the page shows changes. The exported raw CSV and the session JSON
stay in English: they are the record that `calib init` and `calib fit` read,
and a site marker such as *pour edited on site* means the same in every
campaign. Status codes of the anomaly register (`OBJECT?`, `LOSS?`, `LEAK?`,
`RETURN?`) stay as they are in both languages. Notes and tank names stay as
typed.

**How the translation works.** The page and the core write English. The
translator in `site/i18n.js` shows each text in the chosen language: a DOM
observer translates every text the page writes, when it writes it. The
dictionary maps English to Vietnamese. A key is a whole text, or a pattern:
`{0}`…`{9}` take a number, a named placeholder such as `{name}` takes text
within one sentence. A text with no key is split at ` · `, ` — ` and sentence
ends, and each part is looked up alone; a part with no key stays English.

**When you change a text on the page or in the core,** add its Vietnamese key
to `site/i18n.js`. `tests/test_i18n.py` fails on any English text with no key:
it drives the page through fill, drain, transfer, simple and verbose mode,
errors, timers and replay (`tests/i18n_harness.js`), and reads the static
HTML of `page.html`. To list the whole texts behind the missing parts, run
`I18N_WHOLE=1 node tests/i18n_harness.js vi STATIC.json`.

## Each pour

The Live tab has two modes. Tap the small box at the right end of the header
to switch: **Aa** means verbose, **A** means simple. It shows on every tab
once a campaign is open, and the device keeps your choice. **Verbose** (the default) shows every
explanation. **Simple** shows only what to do and the numbers to read:

- the level, and where the batch in the pour panel lands:
  `After 400 L: 531.4 ± 2.3 mm`;
- the batch line (`Batch 800 L · 3/8`) and every warning (brim, bottom,
  overflow, drift alarm);
- a short settle line (`Settling: 3:20 left.`, `Settled: dip now.`) and the
  expected level in the dip panel (`Expect 572.8 ± 3.3 mm`);
- the time to the brim (a drain: the suction floor) as one short line: the
  way left now, after the batch, the time and the clock;
- each verdict as its title and its action, without the numbers behind it.

Simple mode hides the help paragraphs, the shell figures (liquid, brim,
slope), the full time block (*To half* and its breakdown), the batch plan's
note under the pour card's batch line (a changed count still shows in the line, `Batch 800 L · 5/9 (plan
8)`) and the drift line until it alarms. The check
is the same in both modes: only the text changes.

1. **Pour.** Tap *+1 can poured* each time a can is empty, then press
   *Batch done* (see *A batch of cans* below). The card reads from the top:
   the batch line, the count, the can tally, the timer, and one action bar:
   *↶* (Undo last can), the big pour button, *✓* (Batch done). Then
   *Options*. *Options* folds the can size first, then the part-can tick,
   *reached the neck / overflowed*, *level still in the neck*, the note and
   *Enter litres instead* (meter, unknown pour). The Now card follows the
   pour card. Tick *whole pour
   unknown* for `?`, or *plus an unknown extra* for `N+?`.
2. **Wait.** The settle timer on the dip card counts down the settle time
   (5:00 unless you change it) and rings when the level is ready to dip
   (§3.5). In a fill, you can fill the next can now: see *Next can while the
   dip waits* below.
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

**The Now card previews the batch.** The line shows the level the batch must
give, for example
`After this pour (400 L): 486.0 mm ± 8.7 mm (2σ) · +86.0 mm rise · ≈ 1663 L
· too wide to judge: expect two readings`. Use it to choose the pour size: a
large pour has a wide band, and a band wider than 3 mm (2σ) means the check
will ask for a second reading.

The line is there whenever a level is decided, and it is the same number as
the tank tile, drawn from the same calculation:

- with a batch plan, the end of the plan's batch, the litres the tile's
  track counts down: `After the plan's batch (400 L, 200 L tapped so far)`;
- before that plan, or without one, the tapped cans;
- typed litres (*Options → Enter litres instead*) replace the batch on both,
  also when cans are tapped; the
  ticks *whole pour unknown*, *plus an unknown extra*, *part can* and
  *reached the neck* give their reason on both;
- with no can, no plan and no typed litres it says `pour to predict`, as the
  tile does.

Past the brim, below the suction floor or to a dry shell it keeps its number
as a limit, marked as on the tile:
`After this pour (400 L): ≥ 1800.0 mm · the brim · ≈ 96 L more than the gap:
the pour reaches the neck` (a drain: `≤ 52.3 mm · below the suction floor
(65 mm) · ≈ 80 L the pump cannot draw`). While the dip waits, the line is
the expected dip: it shows for the first reading only and then hides, the
blind repeat (§10a.6). The litres field clears after a pour, so a repeated
manual pour needs the value again, or *Use advice*.

This is the only prediction on the Now card: it does not predict an advised
next pour, drain or batch. The advised size is the *Target* in the can tally.
The Now card keeps the warnings: near the brim (halve the pour), near the
bottom (a part can is fine), in the neck, and the drift alarm.

**The way to the brim, and to the suction floor.** The Now card always shows
how far the limit is, in height and in litres, from the last accepted dip
*and* from the predicted level: a fill counts to the brim
(`brim ≈ 1800 ± 6 mm (typed 1800.0 mm) · 412 mm · ≈ 1800 L to go · after this
pour: 330 mm · ≈ 1400 L`), a drain to the suction floor
(`suction floor 65 mm · ≈ 1735 mm to go · ≈ 7546 L to pump · after this
drain: …`). A batch that passes the limit says so and counts the litres past
it: `after this pour: reaches the brim · ≈ 96 L more than the gap`, or
`after this drain: below the floor · ≈ 80 L the pump cannot draw`. In simple
mode the time block becomes one short line for the same limit:
`To brim: 412 mm · ≈ 1800 L · after this pour: 330 mm · ≈ 1400 L · ≈ 2 h 10 ·
done ≈ 14:35`.

**Finish a tank.** The Now card has *Finish this calibration* once one level
is accepted: the calibration is done, also when it has not reached the brim
or the bottom. The pour and dip cards close, the tile says `finished`, and a
banner names the level and the clock. The last row of the raw CSV carries
`finished at 1700.0 mm`, so the file says why the record stops; `calib`
reads that note as text and ignores it. A level still waiting for its dip is
discarded. *Reopen this calibration* takes the finish back and brings the
pour and dip cards back.

**Fold the Now card.** Tap its title line to fold it or open it; the device
keeps the choice. Folded, the line keeps the level and any warning in red,
for example `NOW 1700.0 mm · near the brim`.

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
- **One cell per can.** The tally is a row of cells, one per can of the
  batch, each as wide as its can size, with the size inside. The time of
  each can is under its cell. When the cans are many and the cells are
  narrow (about 9 cans or more on a phone), the row shows one time, the
  last can's (`last 08:04`); hold a finger on a cell (or hover it) for its
  size and time.
- **One size per can.** The block at the foot of the card sets the size of
  the next tap with *Can size for the next can*, so one batch can mix sizes:
  2 × 200 L then 4 × 100 L. The buttons under the field give the sizes
  already used and the default from the setup. The *−50 L* and *+50 L*
  buttons beside the field step the size by the campaign's pour unit
  (*Settings → This campaign → Pour unit*); the size never goes below one
  pour unit, and with no pour unit set there are no step buttons. The
  default can size is optional: with none set, enter the size of the first
  can and the buttons follow. After a reload (and after the return from
  Shortcuts, which reloads the page) the field keeps the size you chose last,
  even before the first can of the batch. With no size chosen on this
  device, it starts at the last can's size, then at the default. The big
  pour button keeps the size in its label: `+1 can poured (200 L)`.
- **The advice is a target, not a limit.** Without a plan the batch line
  shows the advised batch for a rise of about 30 mm (`Batch ≈ 400 L`), and
  the tally has one cell per can of it. With a batch plan, the cells are the
  plan's batch in its cans (`200 + 100 L` for 300 L).
- **The volume warning.** When the batch passes a litre limit — the shell
  gap of a fill, the liquid left of a drain, for a transfer the nearer of
  tank A's liquid and tank B's gap — a red chip follows the batch line
  (`⚠ overflow · gap ≈ 784 L`), a line marks the limit on the tally, and the
  cans past it are hatched (a counted one is solid red). The line under the
  bar names the limit in place of the finish times. The warning counts the
  whole planned or advised batch, so it shows before the can that passes the
  limit. Near the brim (a drain: the bottom) the chip is amber
  (`⚠ near the brim`) and the tally has no line. Tap the chip for the full
  sentence; tap it again to fold it.
- **A second tap in less than 20 s** asks if it is a new can.
- **Undo last can** (*↶*, the left end of the action bar) asks first
  (*Remove the last can from the count?*) and removes one tap on *OK*. *Undo last entry* does the same while a batch is
  open, also with a question. After *Batch done*, *Undo last entry* opens the
  batch again with its cans.
- **Last can not fully poured** records the batch as `N+?`: the full cans are
  known, and the shell estimates the part can. The part can is the last tap,
  so tap it with its own size. The tick is in *Options*.
- **Batch done** (*✓*, the right end of the action bar, as wide as *↶*)
  closes the batch and starts the settle timer from the last can. It is quiet
  below the batch's cans, green on the last can, and amber one can past it.
  Below the batch it asks first (*Only 2 of 4 cans. Close the batch?*),
  unless *Options* says why: typed litres or a part can. With no can it is
  green when *Options* has typed litres or *whole pour unknown*, and disabled
  without them. The raw file keeps the count and the times in the
  note, for example `cans 6x200 L 14:02-14:19`, or `cans 2x200+4x100 L` for a
  mixed batch.
- **Typed litres replace the batch volume.** Enter the measured volume in
  *Options → Enter litres instead* also when cans are tapped, for example
  2 × 200 L then 87 L of a part can. The step records `487`; the note keeps
  `cans 2x200 L 14:02-14:19; typed 487 L`, and the taps still feed the time
  trend. A typed volume is a measurement, so the page adds no count-error
  hint to this level. A transfer records the typed volume for both tanks.
- **Options folds and stays folded.** The device keeps the choice, as it does
  for the Now card. The can size, the part-can, neck, overflow, note and
  manual litres fields are inside. With no can size known, *Options* opens by
  itself, so the size field shows.

After the dip, a confirmed miss of a whole number of cans names the count
error: *the miss is 0.99 can of 200 L: 1 can more than the count (7, not 6)
explains it*. Count the empty cans before the next pour. If the count was
wrong, press *Recount: edit pour*. The message appears only when the miss is
within a quarter can of a whole number and the changed count brings z below 2
(§3.10, §6.2). With mixed sizes the page tests each size in the batch and
names the one that fits.

## The batch plan

A batch is the cans of one level, then one dip. A batch size is not a can
size: a 300 L batch with a 100 L can is 3 cans, with a 150 L can 2 cans. The
plan says before the first pour which batches the campaign needs and how
many of each.

On the *New campaign* card, under **Batch plan**:

| Field | What to enter |
|---|---|
| Can sizes you have | The default can size is always one of them; *Add* puts more sizes in the list. Tap a size to remove it. |
| Nominal capacity | The capacity on the drawing or the name plate, L. The line under it gives π·D²/4·L from your estimates, as a check. A transfer asks for both tanks. |
| Batches | One row per group: `− 2 +` is the count, then the batch size in litres. The row shows the cans of one batch, for example `= 200 + 100 L`. *+ group* adds a row; *Mirror bottom half* writes the top half from the rows up to the largest batch. |

The rows go from the first level to the last: a fill from the bottom up, a
drain from the top down. A transfer follows tank B from the bottom up. The
page starts a campaign with a plan only when the plan is good:

- every batch is a sum of the can sizes;
- the batches add up to the nominal capacity (a transfer: the smaller of
  the two nominals, because the campaign ends at the first tank that is
  empty or full);
- the groups are symmetric about the middle, with the smallest batches at
  the bottom and the top and the largest in the middle.

The line under the rows says what is wrong, for example *The batches add up
to 10000 L, not the nominal 10500 L (−500 L).* The device keeps the plan for
the next campaign. *Settings → This campaign* shows the plan of the open
campaign; it is fixed at the start.

**The cans of a batch.** The page gives each batch the fewest cans, and of
those the largest cans: 300 L with 200 L and 100 L cans is `200 + 100`, not
`3 × 100`. Fewer cans is less pumping and less carrying. The size field of
the pour card starts each batch at its first can and moves to the next can
of the plan after each tap. The tally cells of the cans to come show their sizes.
You can still choose another size.

**The batch tally.** The batch line under the pour card's title shows the
batch size and its number in the group in work, for example
`Batch 800 L · 5/8`. The tally counts only the adjacent batches of one group:
the 300 L batches at the bottom and the 300 L batches at the top are two
groups. Each level records its group, so a reload or an undo keeps the
tally. The Now card adds `batch plan: 8 of 16 batches poured · nominal
10000 L`.

**The end of the campaign.** The nominal capacity is not the real
capacity. Up to the mid-dip level (half the shell's volume in, or for a
drain half of it out), the plan stands as declared. After that level, the
page recounts the batches still to come from the litres the running shell
says are left:

- while the middle (largest) group is still in work, it takes a batch more
  for a larger tank, or a batch less for a smaller one; the groups after it
  keep their counts, so the small batches stay at the top (fill) or the
  bottom (drain);
- in a later group, that group takes the change;
- the last group takes as many batches as the gap needs: a fill ends with
  the planned overflow pour (§3.7), a drain with a part can.

The pour card then shows the new count with the planned one, for example
`batch 5 of 9 (plan 8)`, and says why: *The running shell puts the tank at
≈ 10600 L (nominal 10000 L): the end of the plan changes. Group 3: 9 × 800 L
(plan 8).* At the end of a campaign, the counts are not symmetric any more;
this is correct.

The shell's figure moves a little with each dip. So a count changes only
when the recount is clearly away from it: more than ¾ of a batch from the
count the last batch was poured with. A count changes once, not back and
forth (`8`, `9`, `8`). A small surplus can stay with the last group: it
takes as many batches as the gap needs. A group that is finished keeps the
batches poured into it; its count never drops below them.

**The 30 mm rule stays as a check.** The plan sets the batch size, but the
page still compares each batch with §3.4: a batch that gives less than 15 mm
of rise, or more than 100 mm, gets a note. Near the brim the page warns, but
it does not halve a planned batch: the small top group is the plan's answer.

**The time estimate** walks the batches of the plan, each with its cans and
the fill and drain times of each can size.

## Timers and alarm

Open **Settings → Timers, alarm and device**, enter the times, and press
*Save timers and device*. Write each time as `m:ss` (`1:30`). A plain number is
minutes (`1.5` = 1:30).

| Setting | Meaning | Default |
|---|---|---|
| Fill (pump) time per can size | The time the pump needs to fill one can | blank: the timer takes the trend of the timed cans, else no timer |
| Alarm lead before full | The alarm rings this long before the can is full | 15 s |
| Settle (idle) after a batch | Wait before the first dip (§3.5) | 5:00 |
| One dip and its entry | Only used for the time estimate | 1:00 |
| pour animation | The hose, the can and the tank drawing in the timer | on |
| sound, vibrate, keep the screen on | Device settings: they stay on this phone | all on |

The page warns when the settle time is less than 5 minutes.

**Fill timer.** The timer is for the pump, not for the drain. Press *Start
fill timer* when you start the pump. The hose fills the can and the clock
counts down. The duration is the typed fill time; with none typed, the
trend of the cans you already timed (the start button says which:
*▶ Start fill timer (1:40)*). *+20 s* and *−20 s* change this one run.
Untick *pour animation* to drop the drawing: the clock, the bar and the
alarm stay. The panel has no text under the clock: its colour tells the
state. A screen reader still reads the state.

| Time left | Panel | Alarm | Do |
|---|---|---|---|
| more than the lead | blue | — | watch the can |
| the lead or less | amber | two beeps, banner *Close the valve* | close the valve |
| 0:00 | green, *+1 can* pulses | three beeps every 2.5 s for 3 min, banner *Can full: pump off* | pump off, tap *+1 can poured* |

The lead is the time from the alarm to the closed valve, not a safety margin.
If you close faster than the lead, every can is short by that difference, and
the calibration reads it as a loss at every interval. Time yourself once:
alarm to valve closed. 15 s of a 90 s fill is 33 L of a 200 L can, so the lead
must be right.

The timer does not count the can. Tap *+1 can poured* when the can is full.
That tap is the record, and it also stops the timer and the alarm. Emptying
the can into the tank has no timer.

**Next can while the dip waits.** In a fill, the pump fills the can from
outside the tank, so the next can can fill while the level settles and you
dip. After *Batch done* (or *Poured*), the pour card stays under the dip
card, titled *1 · Next can*:

- *Start fill timer*, *Stop timer*, *±20 s* and the can size (in *Options*)
  work;
- *+1 can*, *Undo last can*, *Batch done* and the other options are locked
  (hidden), and a line says why: empty the can into the tank after the dip;
- at 0:00 the panel turns green and *+1 can* does not pulse: empty the can
  into the tank after the dip, then tap *+1 can poured*.

When the dip is decided, the card moves back above the dip card and opens.
The timer runs on: tap *+1 can* as usual. That can gives no fill time to the
time trend, because it waited full for the verdict.

| Campaign | The next fill timer unlocks |
|---|---|
| fill | at *Batch done* or *Poured* |
| transfer | when tank A is decided (or finished): only B waits. B's field stays open |
| drain, and a transfer while A waits | never: the pump draws from the tank being dipped |

In a transfer, *Take another reading* or *Undo last entry* on tank A while a
fill timer runs asks *Stop the pump and the timer?* first: the pump changes
A's level. *Cancel* keeps A decided and the timer on. A recount that opens A
again stops the timer without a question.

While a fill alarm shows, the settle alarm does not replace it: the dip card
still says *Settled: dip now*.

**Live indicator in the header.** A small can before the tank name and a
thin line along the bottom edge of the header show the can in work, on every
tab:

| Can | Line | When |
|---|---|---|
| blue, fills up | grows as the can fills | the fill timer runs |
| amber, nearly full, blinks | near the full width | the alarm lead: close the valve |
| green, full, with a tick | full width | the timer is at 0:00: the can is full |
| teal, empties | shrinks as the can empties | after *+1 can*, for the drain time of that can size |
| none | none | no can is in work |

The draining state needs a drain time for the can size (*Timers, alarm and
device*): without one the page cannot know when the can is empty. A new fill
timer ends it. Hold a finger on the can (or hover it) for the state in words.

**The tank tiles.** A third row sits under the header and the tab labels, on
every tab: one tile per tank. The header, the tab labels and the tiles stay
at the top when you scroll.

Each tile has two short lines:

- top: the role arrow over a small wave for the liquid surface (↑ pour in,
  ↓ pump out), then the tank name;
- bottom: the last accepted dip in mm, a thin track that fills with the
  tapped litres over the batch, and the prediction at the end of the current
  batch in mm.

The tile has no can tally: the batch card on the Live tab has it.

A small red ring after the dip means a reading at the open level is not
decided yet: a first reading that waits for its pair, a pair that disagrees,
or a miss that asks for another dip. The number stays the last accepted dip
until the page decides.

**The result mark.** After each reading, a small coloured mark at the right
of the tank name shows the result of the reading card in one word, so you
see it at the top of every tab without a scroll:

| Mark | Verdict |
|---|---|
| `✓ good` (green) | *Reading good*, *Reading confirmed* |
| `✓ learning` (green) | *Reading confirmed, shape still unknown* |
| `! watch` (blue) | *Reading confirmed: watch item* |
| `✕ off` (red) | *The pour or the tank is off* |
| `✓ kept` (amber) | *Accept anyway* |
| `neck`, `overflow` (blue) | a level in the neck, an overflow reading |
| `↻ again` (amber) | the page asks for another reading (with the red ring) |

The mark stays while you tap the cans of the next batch, and goes at *Batch
done*: the new level has no reading yet. A finished tank has no mark. The
tooltip names the verdict. On the Live tab, tap a tile with a mark to bring
the full reading card into view. In a transfer, each tile has its own mark;
the pair view of the two tanks stays in the card.

The chosen tank keeps the thick line under it in its role colour (amber for
A, blue for B). Tap a tile to choose the tank: the Log & charts, Shell,
Settings and Files tabs follow it. On Replay and How it works the tiles are
read-only. The row hides before a campaign is open.

The prediction is the level after the plan's current batch. Without a batch
plan it is the level after the cans already tapped, and the track is a plain
connector; before the first can the tile says *pour to predict*. After *Batch
done* the prediction is the expected dip, the same number as the dip card.
The tile shows no ±: the dip card has it.

A level in the neck, or an overflow reading, has no shell prediction: the
tile shows that reading as the level and *no prediction* beside it.

A batch that passes a limit keeps its number, in the warning colour:

| mark | when | the number |
|---|---|---|
| `≥ 1800.0` | a fill passes the brim | the brim of the running shell (2r + h0): the water goes into the neck |
| `≤ 52.3` | a drain goes below the suction floor (*Settings*, 65 mm by default) | the predicted level: the pump cannot draw it |
| `≤ 0.0` | a drain empties the shell | the floor of the shell |

The tooltip names the limit. The dip card still shows no prediction for a
batch past the brim or a dry shell.

The arrow bobs while the live can state moves that tank's water: down while
the pump fills the can in a drain (A in a transfer), up while the can empties
into the tank in a fill (B in a transfer). The wave under it flows sideways
at the same time. *Reduce Motion* stops the bob, the wave and the ring.

The prediction is visible before the dip, as the Now card's line is. An
operator who wants a blind repeat must not read the tile before dipping
(§10a.6).

**iPhone timer on the lock screen.** iOS stops a page's scripts and its
sound when the phone locks, and a page cannot show a countdown on the lock
screen. The iPhone's own Clock timer can do both. On an iPhone or iPad,
*Timers, alarm and device* has the switch *also start the iPhone timer
(Shortcuts)*. With it on, *Start fill timer* also runs a Shortcut that starts
the Clock timer. That timer rings with the page's first alarm (fill time −
alarm lead: close the valve), on the lock screen too, and in silent mode.

Make the Shortcut once per phone: in the Shortcuts app, add the action
*Start Timer*, set its duration to *Shortcut Input* in seconds, and name it
`Calib timer` (or the name you type in the setting). Then tap *Test iPhone
timer (10 s)*. The page opens

    shortcuts://x-callback-url/run-shortcut?name=Calib%20timer&input=text&text=75&x-success=<page address>

Safari first asks *Open in "Shortcuts"?*. The iPhone timer starts only when
you tap *Open*, so the page timer does not start at the tap on *Start fill
timer*. The panel waits in amber with the full time on the clock, and the page
timer starts when iOS leaves the page for Shortcuts: both timers run
together. While it waits, *Open Shortcuts again* asks again, *Start without
iPhone timer* starts the page timer alone, and *Cancel* stops the wait. If
Shortcuts does not open within 60 s, the wait ends: leaving the page later
starts nothing.

While the iPhone timer runs, the page's own fill alarms stay quiet: no
alarm banner, no beep and no vibration at *close the valve* or at *can
full*, because the iPhone rings. The timer panel still turns amber and
green, and *+1 can* still pulses. A timer started with *Start without
iPhone timer* keeps the page alarm. The settle alarm and *Test alarm* do
not change.

Shortcuts opens for a moment and Safari comes back to the page. A page opened
from a Home Screen icon has no address iOS can open, so the link has no
`x-success`: swipe back to the page. *Stop timer*, *+20 s* and *−20 s* do
not change the iPhone timer; stop it in the Clock app.

**Swipe between tabs.** On a touch screen, swipe left in the middle of the
screen for the next tab (Live → Log & charts → Shell → …) and right for the
one before. Once the drag is clearly sideways, the tab follows the finger
and the page does not scroll. Let go after a quarter of the screen width, or
with a fast flick, and the next tab slides in from that side; let go sooner
and the tab springs back. Past the first or the last tab the drag gives way
and springs back. A swipe does nothing when it starts on the frozen stack
(the header, the tab labels, the tank tiles), a field, the chart, a box that
scrolls sideways (the level table), or within 24 px of the screen edge, where
the phone has its own back gesture. A drag that starts up or down stays a
page scroll. With *Reduce Motion* on in the phone's settings, the tab does
not move: the new tab fades in.

**Settle timer.** *Batch done* starts the settle timer from the last can.
The dip card counts down and rings once when the level is ready to dip.

**Time to half, to the brim and to the suction floor.** The page measures
the cans itself. When the fill timer runs, a can's life is on the clock:
*Start fill timer* to *+1 can* is its **fill time**, *+1 can* to the next
*Start fill timer* is the **drain time** of the can before (emptying it and
carrying it back), and tap to tap is its **cycle**. The page takes the
**trend** of each: a weighted mean in which the most recent cans weigh most
(a can three cans back weighs half), so a pump that slows or a team that
gets faster moves the estimate the same day. One long break cannot drag it:
each can is held within a third and three times the median.

The typed times under *Timers, alarm and device* count where the campaign
has not timed a can yet, and the fill **alarm** always uses the typed fill
time: the trend changes nothing by itself. The Now card shows the trend as
*Your trend for 200 L cans (3 cans, the most recent weigh most) · fill
1:28 · drain 0:40*, and the button *Use the trend: fill 1:28, drain 0:40
per 200 L can* copies it into the settings — also one button per can size
in *Timers, alarm and device*. An empty field's placeholder shows the
trend.

The Now card shows how long it takes to reach half of the capacity and the
brim (a drain: the suction floor, below), and the clock time when you will
be done, counted can by can:

    time = Σ (fill time + drain time of each can still to come)

It counts pouring time only: no settle time and no dip time. Each level
takes the recommended batch (the plan's batch, else the advised number of
cans for a rise of about 30 mm), so near the brim the levels get smaller.
The line also counts what is left to pour: the batches by volume and the
cans by size, for example `31 batches: 400 + 30 × 200 L · 30 cans:
30 × 200 L`. The estimate follows the running shell, so early in the
campaign it can be off by several levels. With no trend and only one typed
time, the estimate is a lower bound. With no typed time and no trend at all,
each can counts a fixed guess, fill 1:30 + drain 0:40, the same for every
size: the line says *default time per can* is a rough guess. The fill alarm
never takes that guess.

**The suction floor (drain).** A pump cannot suck from below a certain
height: under it the liquid stays in the tank — a dead region. The floor is
a tape reading, like a dip: 0 mm is the tank bottom, the default is **65
mm**. Set it under **Settings → Noise and limits**; the Now card shows it
(`suction floor 65 mm · ≈ 1735 mm to go · ≈ 7546 L to pump`), and the time
estimate is **time to the suction floor**, not to the bottom. The last can
down to the floor is a part can (*pump lost suction: last can part*). The
advice's bottom watch warns before the level reaches the floor.

**The tap check.** The page notes the clock at each *+1 can* tap, with or
without the fill timer. Tap gaps between two cans of one size give the
cycle trend; the fill timer splits that cycle into the fill and the drain.
The tap gap never feeds the fill timer.

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
swipe the chart left or right, to change the chart. The chosen tank is the
tile with the thick line in the frozen row; the chart and Levels titles carry
no tank name.

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
| **At the brim** (recommended) | Pump the neck down until the level just reaches the brim. Then dip. | The reading is the brim `B` (§5.3a). The running shell takes `2r + h0 = B ± 6 mm` (2σ) from the first level. The ± is the campaign's *Brim is good to ±* field. |
| In the neck | The level is in the neck. | The reading is vent-column height, not shell level. Tick *level still in the neck* on each drain while the level stays in the neck. |
| In the shell | The level is below the brim. | A plain start: only D, L, the datum and the typed brim (if any) teach the shape. |

Start at the brim when you can. The reading is the brim itself, so the
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
- **The end.** The pump cannot draw below the **suction floor** (a tape
  reading, 65 mm by default; **Settings → Noise and limits**). The last can
  is then a part can: tap it, and tick *pump lost suction: last can part*
  (`N+?`). If you measure the part can, enter its litres instead. The
  pour advice warns before the level reaches the floor, or when less than
  5 % of the capacity is left. A drain never halves near the brim.
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
left`, the way left to the suction floor now and after the drain, and the
time to half and to the floor. The charts and the Levels table
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
start at the brim catches more 3 mm slips (91 % against 88 %) and gives
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
The tank tiles name the tanks: A's tile falls (pump out), B's rises (pour
in), and the chosen tile keeps the thick line in its role colour (amber for
A, blue for B). The tiles choose the tank that the Log & charts, Shell and
campaign cards show, and the tank that *Take another reading* and *Accept
anyway* apply to; the Live tab marks the current tank. The tiles are
read-only on Replay and Help, where they change nothing. The Log & charts tab
has no switch of its own: its table and chart are always the chosen tank's
own (A's table reads *drained L*, B's *pour L*). The Live tab always shows
both tanks. *Files* exports one raw CSV per tank.

**Finishing one tank.** Each tank's line in the Now card has a *Finish*
button once that tank has an accepted level: the tank is done, and the page
stops asking for its dip. Its dip field stays in place, closed, and reads
`alpha: finished at 1800.0 mm`; its tile keeps the last level with the word
`finished`; the verdict box says the tank is finished. The water still moves
— the pump and the cans still count for the other tank — and *Batch done*
closes the shared tally for the open tank only, so no level opens on the
finished one. The open tank alone sets the batch advice, the shared plan's
room and the time line; the pair view is off while one tank is finished.
Both tanks finished: `Both tanks are finished: close the session on Files.`

The finish can be taken back with *Reopen* only **before the next batch**: a
level dipped after the skip would leave the finished tank's step wrong, so
the page keeps the mark once a batch has gone by. The finished tank's raw
CSV keeps its rows and their `finished at …` note; *Files* still exports both
tanks and the session JSON, which saves the mark.

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
both limits at once: A's suction floor (the pump may lose suction — tick
*pump lost suction: last can part*) and B's brim (tick *tank B: reached the
neck* on the final batch). Typed litres in *Options* close the batch on both
tanks with the typed volume. The campaign ends when A is down to its suction
floor or B is full, whichever comes first. The noise, the cans and the
timers are one set for both tanks (§9.1).

## After the campaign

1. *Files → Download raw CSV* gives `WORKSPACE_TANK_raw.csv`: one row per level with the
   adopted reading (the mean of the two readings that agree). The note holds
   every reading and the live state. *Download session JSON* keeps the full
   session, the times included, as `WORKSPACE_TANK_site.json` (a transfer:
   `WORKSPACE_A-B_site.json`). WORKSPACE is the cloud workspace of the
   campaign; a campaign only in this browser takes the workspace logged in on
   this device. With no workspace at all, the name starts at the tank:
   `TANK_raw.csv`. A character that a file system refuses (`/ \ : * ? " < >
   |`) becomes `-`.
2. Run the normal pipeline:

   ```bash
   uv run python -m calib init WORKSPACE_TANK_raw.csv --r <D/2> --L <L>
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
node site/replay.js TANK_raw.csv --D 2480 --L 5280 --drain --at-brim   # a drain
node site/simulate.js --runs 200       # detection rate for slips of 1–10 mm
node site/simulate.js --runs 200 --drain
```

A drain replay takes `--drain`, `--neck ROWS` (the rows that are neck levels,
for example `1,2`) and `--at-brim` (row 1 is the brim reading; `--neck-entrance` still works). Without
`--drain`, the replay finds a drain from falling heights and says so. The
*Replay* tab has the same options.

## Files

| File | Role |
|---|---|
| `site/site_core.js` | The rules and the maths. One source for the page and the tests. |
| `site/i18n.js` | The page translator and the Vietnamese dictionary. |
| `site/cloud.js` | The optional cloud client: login, sync, conflicts ([cloud.md](cloud.md)). |
| `site/_headers` | Security headers for the hosted page. |
| `site/page.html` | The page template. |
| `site/calib_site.html` | The built page. Copy this file to the device. |
| `site/replay.js` | Replay a raw CSV from a terminal. |
| `site/simulate.js` | Detection-rate study on synthetic campaigns. |
| `tests/test_site.py` | Build check; with Node: geometry against Python, demo replay, session rules, detection rate. |
| `tests/test_i18n.py`, `tests/i18n_harness.js` | The translator's rules, and a Vietnamese key for every text the page can show. |
