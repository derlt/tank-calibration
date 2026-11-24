# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **Live tab: the action buttons stay last.** While a dip waits and the next can
  runs, the pour and Now cards moved below the buttons (Take another reading,
  Recount, Undo last entry …). They now sit above them: the buttons close the
  tab in every case.

### Added

- **Timer settings from the timer card.** A **Timer settings** button on the
  fill timer card opens the Settings tab at the timers. The *Timers, alarm
  and device* card is now open by default.
- **Lock-screen alarms by Web Push.** In the Home Screen app a switch in
  Settings sends the fill and settle alarms to the server, which sends a
  notification at each alarm, so it reaches the lock screen. A Durable Object
  per device holds the alarms; no cloud login (a random device secret);
  VAPID keys are a Worker secret and two variables, see docs/cloud.md. The
  first deploy applies a Durable Object migration (`wrangler deploy`). In the
  app on an iPhone, an export opens the share sheet.
- **Home Screen app.** The hosted page has a web manifest and icons
  (`site/app/`), so it installs as an app (iPhone: Share → Add to Home Screen)
  with the status bar over the header. Sessions in Safari do not move to the
  app: Settings says to log in to the cloud or use the session JSON. The
  firewall rule that serves only the page and the API needs the new paths
  (docs/cloud.md).

### Changed

- **Cloud: far fewer requests, less battery.** The page asked every 10 s (the
  campaign and the timer), every 3 s while a timer ran and for 2 minutes after
  each new version. Now: at once when the page comes into view, then every
  30 s; every 10 s while a fill timer runs or for a minute after a new
  version; nothing while the page is hidden.

### Fixed

- **Cloud: the iPhone timer stopped after Shortcuts.** With the iPhone timer
  on, the page timer starts as Shortcuts opens, and iOS stops the page before
  the start reaches the cloud. When Safari loaded the page again, the page
  took the cloud's older "no timer" (from the last can) and stopped its own
  run. The waiting change now stays in the browser across the reload, and a
  cloud state older than the device's own start no longer stops it.

### Added

- **Cloud: the fill timer runs and rings on every device of a campaign.**
  When one person starts the fill timer, the other devices on the campaign
  show the same countdown and ring *Close the valve* and *Can full* at the
  same moment, corrected for the difference between the phones' clocks.
  A stop, *±20 s* or *+1 can* on any device changes it on all; the later
  change wins. The timer is kept apart from the campaign data (a new D1
  table `timers`, `GET`/`PUT /api/campaigns/:id/timer`), so it never gives
  a merge or a conflict. Apply the schema (`make db-schema`) before the new
  Worker serves.

- **Cloud: two writers of one campaign merge instead of a conflict.** One
  person counts the cans while another dips, on two phones: when the second
  save finds that the first device saved before it, the page replays its own
  actions on the cloud copy and uploads the result, so both people's work
  stays. It is accepted only when neither person's work changes (byte for
  byte), and otherwise the usual choice stays, with a short reason. The merge
  waits rather than interrupt a note being typed. *Files → Cloud* has the
  switch (on by default), the merge log (the last 20 results and why a merge
  was refused) and *Restore my copy from before the merge*.

- **On-site page: the browser is asked to keep the saved data.** Safari
  deletes a site's saved data after 7 days without a visit (not from the
  Home Screen); other browsers delete it when space runs low. The open
  campaign and the archive live there. At the first save the page asks the
  browser to keep them (`navigator.storage.persist()`), and *Files* says
  whether it does and how to keep the data otherwise.

- **Hosted page: only its own scripts run.** The security header's
  `script-src` now lists the SHA-256 hash of each inline script of the
  page, written by `calib site-page`, instead of `'unsafe-inline'`. A
  script injected into the page does not run. `--check` and the tests fail
  when the hashes are stale.

- **On-site page: the hosted page opens without a network.** A small service
  worker (`site/sw.js`) keeps the last page the browser got. A load asks the
  network first and waits up to 3 s; with no answer, the kept page opens. A
  return from the Shortcuts timer, a reload or a tab the phone closed now
  works at a tank with no signal. Only the page itself: `/api/*` goes to the
  network as before. The security headers allow the worker
  (`worker-src 'self'`). The one file on a phone (`calib_site.html`) is not
  affected. The zone's firewall rule *calib: serve only the page and the
  API* now lets `/sw.js` through too.

- **On-site page: an F(H) calculator in the Shell tab.** Type a dip
  reading to get litres, or litres to get a dip reading. The other field
  shows the running shell's answer. Below the fields, the shell and the
  dips stand side by side, each ± 2σ, with the difference and the drift
  alarm for scale. The dips column uses calib's books (§9.3) at the
  accepted dips; between two dips it follows the shell's shape and meets
  both dips. Outside the dips it is the shell's step, marked
  *extrapolated*. Until you type, the fields hold the last good level.

- **On-site page: the trend button is a second start button.** *Use the
  trend* moved from the Now card into the timer card, next to the start
  button: *▶ Start (1:30)* starts with the setting, *▶ Trend 1:32* copies
  the trend of your cans (fill and drain) into the settings and starts the
  fill timer in one tap. It shows only while the timer is idle and the trend
  differs from the setting; when only the drain differs, it keeps the fill
  time and copies the drain time.

- **On-site page: Finish sits with the level actions.** *Finish this
  calibration* (a transfer: *Finish (tank)* per tank) and *Reopen* moved
  from the Now card to the row under the verdict, with *Take another
  reading*, *Recount: edit pour*, *Accept anyway* and *Undo last entry*.
  Its note follows the row.

- **On-site page: a denser pour card.** The batch line sits close under
  the title: `Batch 800 L · 3/8` (the batch size, its number in the group in
  work, `(plan 8)` after a recount), or `Batch ≈ 400 L` without a plan. The
  group chips and the target line (`Target: 6 × 200 L`, `Plan: …`) are gone.
  Under the full-width +1 button, *↶ Undo last can* and *✓ Batch done* sit
  side by side in one row, the same size. *Batch done* turns green on the
  last can of the batch and amber past it; below the batch it asks first
  (*Only 2 of 4 cans. Close the batch?*). The can size
  moved into *Options*, at the top. The fill timer has no text under the
  clock: its colour tells the state. The Now card follows the pour card, and
  the header drops the extra-dip count.

- **On-site page: the volume warning on the batch line and the tally.** When
  the batch passes the shell gap (a drain: the liquid left; a transfer: the
  nearer of tank A's liquid and tank B's gap), a red chip follows the batch
  line (`⚠ overflow · gap ≈ 784 L`), a line marks the limit on the can
  tally, and the cans past it are hatched. It shows before the can that
  passes the limit. Near the brim or the bottom the chip is amber. A tap on
  the chip opens the full sentence.

- **On-site page: the reading result on the tank tile.** After each
  reading, the tile in the frozen stack shows the verdict in one coloured
  word next to the tank name (`✓ good`, `↻ again`, `! watch`, `✕ off`, …),
  on every tab and without a scroll. It stays while the next batch is tapped
  and goes at *Batch done*. On the Live tab a tap on the tile brings the full
  reading card into view. A transfer marks each tank on its own tile.

- **On-site page: the next can's fill timer while the dip waits.** After
  *Batch done* (or *Poured*) in a fill, the pour card stays under the dip
  card as *1 · Next can*: the fill timer and the can size work, so the pump
  can fill the next can during the settle time and the dip. *+1 can*, *Undo
  last can*, *Batch done* and *Options* stay locked until the verdict, because
  the can goes into the tank after the dip. A transfer unlocks the timer once
  tank A is decided (or finished) and only B waits; B's field stays open. A
  drain, and a transfer while A waits, keep the timer locked: the pump draws
  from the tank being dipped. A can whose timer started while a dip waited
  gives no fill time to the trend. *Take another reading* or *Undo last
  entry* on A asks to stop the pump and the timer first. A fill alarm on the
  banner is not replaced by the settle alarm.

- **On-site page: the pour card's foot.** The card now reads +1 can →
  *Undo last can* → *Batch done* → can size → *Options*. *Batch done* is
  short, faded below the batch's target, green and bold on its last can, amber
  one can past it, and disabled with no can and no litres. *Undo last can*
  asks before it removes a tap; *Undo last entry* keeps its question. One
  folded *Options* block holds the part-can and neck ticks, the note and
  *Enter litres instead*, and the device keeps the fold. Typed litres replace
  the batch volume also when cans are tapped: the raw note keeps
  `cans 2x200 L …; typed 487 L`, the taps still feed the time trend, and the
  count-error hint stays quiet for that level. A transfer records the typed
  volume on both tanks.

- **Brim reading.** The site page asks for an optional measured brim
  reading and its ± (default 6 mm) at setup, per tank in a transfer, and
  *Settings → This campaign* changes or clears it (the running shell
  refits). It is the brim prior of the running fit, so the Now card's brim,
  the near-brim warning, the time to the brim, the batch plan and the tile
  limit follow it; the Now card names it `(typed … mm)`. A drain that starts
  at the brim keeps its start reading as the prior and warns when the typed
  brim differs by more than √2 × its ±. Row 1 of the raw CSV carries
  `brim X ± Y mm`; `calib init` reads it as `brim.declared` /
  `brim.declared_pm`, and `calib fit` uses it for the first trust marks,
  still refines the brim, and reports `declared brim … : free fit … (diff,
  z) — compared, not enforced` in the shell record and the workbook.

- On-site page: the **tank tiles**, a third frozen row under the header and
  the tab labels, on every tab. One thin tile per tank, two short lines: the
  role arrow over a wave for the liquid surface and the tank name; then the
  last accepted dip, a track that fills with the tapped litres, and the
  predicted dip at the end of the current batch. No can tally: the batch
  card has it. The chosen tile keeps the thick line in its role colour and
  chooses the tank for the other tabs. Without a batch plan the prediction
  follows the tapped cans; after *Batch done* it is the expected dip. A red
  ring after the dip shows a reading that is not decided yet. A batch past
  the brim, below the suction floor or to a dry shell keeps its number as a
  limit (`≥ 1800.0`, `≤ 52.3`) in the warning colour. While the live can
  state moves that tank's water, the arrow bobs and the wave flows.
- On-site page: a tank can be **finished**, also before it reaches the brim
  or the bottom. The Now card has *Finish* per tank (one for a single
  campaign), with a confirm; a level that still waits for its dip is
  discarded, and the finish is refused before the first accepted level. A
  finished tank takes no pour, dip or prediction: its dip field stays,
  closed, reading `alpha: finished at 1800.0 mm`, its tile says `finished`,
  and in a transfer the shared tally still closes for the open tank only.
  The open tank alone sets the batch advice, the plan's room, the pair view
  and the time line; both finished says so. *Reopen* works until the next
  batch. The session JSON saves `finished {level, row, time, levels, after}`
  and the last raw row's note gains `finished at 1700.0 mm` (read as text by
  `calib`). `Session.closeTally` splits the tally from the level, so a
  finished A still closes the batch; `TransferSession.liveKeys` / `liveKey`
  and `_afterFinish` keep the bookkeeping.
- On-site page: the **Now card's prediction is always there**, and it is the
  same calculation as the tile's. It shows the plan's batch end (or the
  tapped cans, or typed litres), the limit past the brim, the suction floor
  or a dry shell (`≥ … · the brim · ≈ … L more than the gap`), and the
  expected dip while the dip waits (first reading only). The ticks and typed
  litres now reach the tile too. The brim and suction floor rows always
  count the way left in mm and L, from the last dip and from the predicted
  level; a batch past the limit counts the litres over it. Simple mode gets
  one short line to the limit with the time and the clock. With no typed
  time and no trend, the time estimate uses a marked default of 1:30 + 0:40
  per can. `Session.tileView(input)` / `TransferSession.tiles(input)` take
  the pour panel; the view carries the band, the limit, the litres past it
  and the left figures. `Session.cycleSecondsFor` reports the default with
  source `default` (`DEFAULT_CYCLE`).
- On-site page: the time trend of the cans. With the fill timer running,
  *Start fill timer* to *+1 can* measures a can's fill time and *+1 can* to
  the next start its drain time; the trend is a weighted mean in which the
  most recent cans weigh most (a can three cans back weighs half), with
  each can held within a third and three times the median. The time-to-half
  and time-to-brim estimate follows the trend; the typed times count where
  no can was timed yet. *Use the trend* (Now card, and one button per can
  size in the timers card) copies the trend into the fill and drain
  settings; the fill alarm changes only then. With no typed fill time at all,
  the fill timer runs on the trend (the start button names the duration).
- On-site page, drain: the **suction floor** — a pump cannot suck below a
  certain height, and the liquid under it stays in the tank. The floor is a
  tape reading like a dip, 65 mm by default, in *Settings → Noise and
  limits*. The time estimate is now **time to the suction floor**, not time
  to the bottom; the Now card shows the floor, the way down to it and the
  litres still to pump.
- On-site page: the time estimate counts the batches and the cans still to
  come, by size: `31 batches: 400 + 30 × 200 L · 30 cans: 30 × 200 L`, with
  the recommended batch (the plan's batch, else the 30 mm advice).
- On-site page: a batch plan, declared on the *New campaign* card: the can
  sizes, the nominal capacity and the batches in groups (`2 × 300 L`,
  `8 × 800 L`, …). The page checks that each batch is a sum of the cans, that
  the total is the nominal and that the groups are symmetric with the
  largest in the middle. Each batch gets the fewest and largest cans. The
  pour card shows the group in work, its batch tally (adjacent batches of
  one group only) and the cans of the batch; the size field follows the
  plan. Past the mid-dip the running shell counts the end of the plan again
  for a tank larger or smaller than the nominal. Without a plan the 30 mm
  advice stays.
- On-site page: − and + buttons beside the can size step it by the pour
  unit (`−50 L`, `+50 L`); never below one pour unit.
- On-site page: a drain time per can size (Timers, alarm and device): the
  time to empty one can. The time to half and to the brim (a drain: to the
  suction floor) adds it to the fill time.
- On-site page: a live indicator in the header, on every tab: a dot before
  the tank name and a progress line along the header's bottom edge. Blue
  while the can fills, amber at the close-the-valve alarm, green when the
  can is full, teal while it drains (for the set drain time after *+1 can*).
- On-site page on iPhone and iPad: *also start the iPhone timer
  (Shortcuts)*. *Start fill timer* runs a Shortcut that starts the Clock
  timer, set to ring with the close-the-valve alarm. It shows a countdown on
  the lock screen and rings when the phone is locked. Setup steps and a
  10 s test are in *Timers, alarm and device*.
- On-site page on a touch screen: swipe left or right in the middle of the
  screen to go to the next or the previous tab. The tab follows the finger,
  the next tab slides in, and a short drag springs back (a fade with Reduce
  Motion).

### Changed

- **Cloud sync: faster, and it works on a weak network.**
  - After a newer version from another device comes in, a following device
    asks every 3 s for 2 minutes, then every 10 s again: the two people take
    turns, and the next one starts from the newest copy, so a conflict is
    rarer.
  - An upload goes gzipped, about a fifth of the size, and a large one gets
    more time (15 s plus 1 s per 4 KB). Before, 100 levels over 64 kbit/s
    took longer than the 15 s timeout and never uploaded. The Worker reads a
    gzip body (by its first two bytes) and checks its limit on the unpacked
    size.
  - A device that follows a campaign asks every 10 s while in view (was
    30 s), and at once when the page comes back into view, gets the focus
    or comes back online.
  - When the page goes out of view (the phone locks, Shortcuts opens), a
    change uploads at once, with `keepalive`, instead of after the 1.5 s
    wait or at the next open.

- **On-site page: Save timers and device saves the campaign only when its
  timers changed.** Sound, vibration, wake lock, animation and Shortcuts stay
  on the device (`calib-site:prefs`). A save with nothing in it marked the
  campaign changed, gave another writer a needless conflict, and uploaded a
  campaign that did not change.

- **On-site page: the shell fit starts from the prior only.** The fit also
  started from the last fit (a warm start) which the session JSON does not
  hold, so a copy read back from JSON judged the next dip with different low
  digits. A session read on another device is now the same session, to the
  last digit (the warm start never won by more than 1e-8 of the cost).

- **On-site page: the Vietnamese page is as fast as the English one.** The
  translator looked up every text again on each redraw and each heartbeat,
  and it also looked up its own translations (the slowest case: no key
  matches, so it tries every pattern). It now keeps each answer, and a
  translated text stays as it is. A tab switch in Vietnamese spent about ten
  times more time translating than drawing; now it is a small part.
  The first translation of the page at load is also about three times
  faster: a pattern whose fixed text is not in the text is skipped before
  its regular expression runs.

- **On-site page: a faster redraw on every tab.** The archive list (it reads
  every archived campaign) was drawn again on every tap and every cloud
  sync, on every tab. Now only the Files tab draws it. With 8 archived
  campaigns a Live redraw takes about half the time.

- **On-site page: fewer forced layouts in a redraw.** The redraw read sizes
  (the frozen stack's height, the window and chart widths, the tab label
  line) after it changed the page, so the browser laid out the page more
  than once per tap. The stack's height now comes from a ResizeObserver, the
  widths are kept from the last resize, and the tab label line is measured
  before the redraw.

- Batch plan: past the mid-dip, the litres over or under the plan go to
  the open group whose batch size is nearest to them, not always to the
  middle group. A tank 600 L larger than the nominal takes one 600 L batch
  more, not one 800 L batch and 200 L too many at the top; a larger extra
  is a sum of batches, the nearest size first (+1400 L = 800 + 600). The
  last group still fills the gap. The hold now keeps the choice of group
  too: the counts the last batch was poured with stay while the litres
  they leave to the last group are within ¾ of a batch of each group they
  changed, so the choice does not flip between 300 L and 600 L.

- **On-site page: file names carry the workspace.** The raw CSV is
  `workspace_tank_raw.csv` and the session JSON `workspace_tank_site.json`
  (also for a closed campaign in *Files*). The workspace is the campaign's
  cloud workspace, else the one logged in on the device; with none, the
  names stay `tank_raw.csv` and `tank_site.json`.
- **On-site page: the tab labels have room.** The tab row keeps a gap under
  the header and above the tank tiles.
- **On-site page: a tighter pour card.** The folded *Options* has no blank
  strip under it, and on a phone the pour card keeps a smaller gap under the
  frozen stack.

- One word, **brim**: the drain start *At the neck entrance* is now *At the
  brim*, and "neck entrance" / "shell crown" are "brim" in the page, the
  docs and the methodology. New raw files write `at brim` on row 1; `calib`
  still reads `at neck entrance` in older files. `site/replay.js` takes
  `--at-brim` (`--neck-entrance` still works). The drain setting *brim at
  the neck entrance ±* left *Noise and limits*: the brim ± is each
  campaign's own field.
- On-site page layout, checked in Chromium at 360 px and 760 px, light and
  dark: on a phone the header keeps the status on two lines and shortens a
  long title (a transfer's `A → B`) with "…", so the frozen stack stays
  143 px high, not 237 px; the frozen stack's shadow spans the full width; a
  field that takes the focus, or a card scrolled into view, stops below the
  frozen stack; a batch tally too crowded for a time under each can shows
  one pill with the last time, and each cell keeps its size and time in its
  tooltip. A turn of the phone redraws the page.
- Batch plan: a recount past the mid-dip holds to the count the last batch
  was poured with, unless the shell's figure is more than ¾ of a batch
  away. Reading noise no longer flips a group's count (`8`, `9`, `8`). A
  finished group keeps the batches poured into it: its count never drops
  below them. Each level records the plan counts it was poured with
  (`L.plan.counts`); an older session without them recounts as before. The
  pour card text now says what the recount does; simple mode hides that
  note, also when a count has changed (the head line shows `(plan 8)`).
- On-site page: the header, the tab labels and the tank tiles are one frozen
  stack. The header tank switch and the Log & charts tank switch are gone:
  the tiles choose the tank. The chart and Levels titles carry no tank name.
- Pour card: the batch tally is quantized. One cell per can of the batch
  replaces the continuous fill bar, so the count reads as cans done over
  cans planned (`3 / 5 cans · 600 L`). The cell width is the can size, so a
  300 L can takes half again the room of a 200 L can, and the size sits in
  the cell. The can in work fills inside its own cell. The finish time
  moves from the tag below the +1 button to a green pill under its own
  cell; the can in work gets a grey pill, and a can past the plan keeps its
  cell in the warning colour. Without a plan the denominator counts the
  litres already poured at their own size, so changing the can size
  mid-batch does not redraw a poured can as planned or over.
- The Simple · Verbose switch moved from its own row above the Now card to a
  small box at the right end of the header, on every tab: **Aa** = verbose,
  **A** = simple; a tap switches.
- Header live indicator: a small can replaces the dot. It fills while the
  pump fills it and empties while it drains, in the colour of the state; it
  blinks at close-the-valve and shows a tick when full. The line along the
  header's bottom edge stays.
- Header tank switch (transfer): the chosen tank is bold white with a thick
  line under it in its role colour (amber A, blue B); the other is dim. The
  chosen button used to take the header colour, so it looked off and the
  other one looked chosen.
- Now card: no prediction for an advised next pour, drain or batch (`Next
  pour ≈ …`, `Expect the next dip at …`, simple mode `Next: … → expect …`).
  The only prediction is the one for the batch in the pour panel (`After
  this pour …`). The warnings stay (near the brim, near the bottom, in the
  neck, drift). The core's advice has a new `warn` field: the warning alone.
- Now card: it folds. Tap the title line; the device keeps the choice. The
  folded line shows the level and any warning.
- The time to half and to the brim counts pouring time only (no settle, no
  dip) and uses only the typed times: the tap gap no longer replaces them
  without notice.
- Vietnamese: a can is now "bình" (was "can").
- On-site page on a phone: no tab is wider than the screen any more (Log &
  charts was 1094 px wide at 360 px; the level table now scrolls in its own
  box, and the chart takes the card width). The How it works table wraps and
  scrolls in its box; long buttons wrap. Below 560 px the tabs are one line
  that scrolls sideways, the setup and settings forms show two fields per
  line (D beside D ±), the main button of a card fills its width, the Now
  labels wrap to give the values room, the transfer header stays one line,
  and the log note field is 16 px so the phone does not zoom. Safe-area
  padding for phones with a notch.
- Transfer verdict titles join the tank name with " — " instead of ": "
  (`alpha — Reading confirmed`), like the pair box (`Both tanks — …`).
- Header: one slim line instead of two or three. The title is the tank name
  only (no "— live dip check"); the phase and the count are one line of
  small text, not two pills, and extra dips show only when there are some.
  In a transfer, the tank switch takes the place of the title, and its
  buttons read `↑ alpha` and `↓ beta` (the dip card's arrows); the full role
  stays in the tooltip and the accessible name, and the "Current tank"
  label stays for screen readers. Less padding, smaller buttons.

### Fixed

- **On-site page: a second tab no longer wipes cans and dips.** Two tabs of
  the page share one saved session, and each tab kept the session it read.
  A tap in the older tab saved its older session over the newer one: in a
  test, 3 cans counted in one tab were gone after one tap in the other. Now
  the older tab takes the newer session when the other tab saves, when it
  comes back into view and at the first tap; and a save checks that nothing
  changed since this tab read the session. If it did, the entry does not
  count, and the page asks you to enter it again.

- **On-site page: no redraw while you scroll.** Safari and Chrome on a phone
  send a resize event when their toolbar shows or hides during a scroll; the
  page drew all of itself again each time. Now only a new width (a turn of
  the phone) draws the page again.

- **On-site page: one tap on a tab label is enough on an iPhone.** After a
  tap in the content, Safari showed the label as pressed but did not switch
  the tab until a second tap. The label now switches when the finger lifts.

- Can size: a size typed or tapped before the first can of a batch was lost
  on a reload, and on the return from Shortcuts (which reloads the page); the
  field went back to the campaign's default. The chosen size is now kept on
  the device for the campaign; a new campaign starts at its own default.
- Vietnamese: a done time past midnight (`tomorrow 00:03`, `09:10 (+2
  days)`) stayed in English.
- iPhone timer: the page timer started at the tap on *Start fill timer*,
  while Safari still asked *Open in "Shortcuts"?*, so the two timers did not
  agree. The page timer now waits and starts when Shortcuts opens; the panel
  offers *Open Shortcuts again*, *Start without iPhone timer* and *Cancel*.
- iPhone timer: the page no longer shows its alarm banner (and makes no
  sound) for the fill timer while the iPhone timer runs; the two alarms
  rang together. A page timer alone keeps its alarm.
- On-site page: the tank tile's arrow had the roles the wrong way round in
  a fill and a transfer. It now follows the dip card: ↑ pump out (tank A in
  a transfer) and ↓ pour in (tank B), and a standalone drain shows ↑, a fill
  ↓. The bob and the flowing wave follow the same direction.
- On-site page: the tank tile's prediction sat lower than the last dip: a
  page paragraph style gave it a top margin. The two numbers now share a
  baseline. A tile that is not chosen keeps its card border and an empty
  strip where the role line would be, so the row does not shift.

### Added

- Cloud store for the on-site page (optional): a Worker API on Cloudflare D1
  (`worker/index.js`, `worker/schema.sql`) and a client in the page
  (`site/cloud.js`, **Files → Cloud**). A team logs in to a workspace with
  its name and secret keyword; campaigns upload about 1.5 s after each
  entry, wait in the browser while offline, and upload when the network is
  back. Each save carries a version: a stale save is a conflict, never an
  overwrite, and the user takes the cloud copy (theirs goes to the archive)
  or keeps theirs as a new campaign. A device with no changes follows a
  campaign every 30 s. The header shows the cloud state.
- Cloud sync keeps every change: a campaign closed with changes that wait
  uploads them later from an outbox in the browser; a copy taken out of a
  conflict keeps the conflict in the archive; a save whose answer was lost
  is recognised at the next try, not taken as a conflict; a campaign of
  another workspace or one deleted in the cloud is never uploaded on its
  own (the page offers to upload it as a new campaign); a save never brings
  a deleted campaign back; the tank A/B view of a transfer is not a cloud
  change.
- Security: keyword as PBKDF2-SHA256 (100 000 rounds), tokens stored as
  SHA-256 and valid 30 days, new workspaces only with the `SIGNUP_CODE`
  secret, every query scoped to the token's workspace, no cookies, CSP and
  no framing for the hosted page (`site/_headers`).
- Flood limits: 300 API requests and 10 logins per minute per IP address
  (rate limit bindings), failed-login lockout per address and per workspace,
  1 MB bodies, 2000 campaigns per workspace. Only `/api/*` runs the Worker,
  so the page stays up and offline-capable under an API flood.
- Zone firewall for the page's host (Cloudflare WAF, Free plan): only `/`
  and `/api/*` pass, only the API methods, no crawlers on the API, and a
  rate limit of 50 API requests per 10 s per IP address. The API answers
  only on the hosts in `API_HOSTS`, so the workers.dev address cannot skip
  the firewall (its page stays, offline only).
- Secrets stay in `.env`: the D1 id left `wrangler.jsonc`; `make deploy`
  writes `wrangler.deploy.jsonc` (ignored by git) and sets `API_HOSTS`.
  `tests/test_secrets.py` fails when a `.env` value is in the page or in a
  file that git tracks, or when server code reaches the page.
- `make db-schema`; `make deploy` copies `site/_headers`.
- Tests: `tests/test_cloud.py` runs the Worker on an in-memory SQLite D1
  (`tests/cloud_harness.mjs`), the client offline and online, conflicts
  between two users, and two page devices that follow one campaign.

- Dark mode for the on-site page. **Settings → Display → Theme**: *Auto*
  (the default, follows the phone), *Light* or *Dark*. The choice stays on the
  device and applies before the first paint. Every colour is a CSS variable
  with a light and a dark value; the charts, the tank pictograms and the pour
  animation use them too. The Language card is now the Display card, with the
  language and the theme.
- The on-site page speaks Vietnamese. Choose the language in **Settings →
  Language** (English or Tiếng Việt); the device keeps the choice, and a
  phone set to Vietnamese starts in Vietnamese. Every text the page shows is
  translated: the tabs, the Live tab in both modes, the verdicts and the pair
  view of the core, the charts, the timers, errors, dialogs and the help.
  The exported raw CSV and session JSON stay in English (they are the record
  for `calib`), as do the register codes (`OBJECT?`, `LOSS?`) and what the
  operator types. The translator (`site/i18n.js`, inlined by `calib
  site-page`) translates the page's text as the page writes it, so the rules
  and the render code stay in one language. `tests/test_i18n.py` fails on
  any English text with no Vietnamese key.
- Live tab: a *Simple · Verbose* switch. Simple mode shows only the actions
  and the numbers to read: the level, `Next: 2 × 200 L → expect H ± 2σ mm`,
  the can target, warnings, a short settle line, the expected level in the
  dip panel, and each verdict's title and action. It hides the help
  paragraphs, the shell figures, the time-to-brim block and the drift line
  until it alarms. Verbose is the former Live tab, unchanged, and the
  default. The choice is saved on the device; transfer campaigns follow it.
- Log & charts: the Levels table and the chart select one level together.
  A tap on a row rings its mark in the chart and draws a vertical guide at
  its level; a tap on a mark highlights its row and scrolls the table to
  it. A second tap, or a tap on an empty part of the chart, clears it. The
  selection stays across the four charts; a level with no mark in the chart
  now shown says why. Rows and marks also answer Enter and Space, and each
  mark has a wide touch area.
- Live tab: the pour advice now gives the level the next dip must find
  (§10a.2), for the advised pour, from the running shell: "Expect the next
  dip at ≈ H ± 2σ mm". A drain gives the level after the advised drain; a
  transfer gives one level per tank for the shared batch. A pour that
  reaches the neck, or a drain that runs the tank dry, says so instead. In
  a transfer, the per-tank verdict no longer repeats a per-tank "next pour"
  that is not the batch.
- Log timestamps: the Levels table has a **time** column with the time the
  pour (or drain, or batch) ended and the time of each reading, local
  clock. The exported raw CSV puts the same times in the note
  (`poured 09:15 read 09:20/09:25`), and row 1 also carries the date
  (`date 2026-11-16`). A level without recorded times (a replay, an older
  session) gets no time in its note.
- Dip panel: each dip field shows the level the waiting dip must find
  ("Expected level: H ± 2σ mm"), for the pour actually recorded. It shows
  for the first reading only; a repeat reading stays blind (§10a.6). With no
  prediction (first level, unknown pour, overflow, neck) the line says why.
- Transfer strapping (two tanks, one water, §3.12): the on-site page can
  calibrate two tanks at once. A pump draws known volumes out of the full
  tank A into calibrated cans, and the same cans are emptied into tank B: A
  is a drain, B is a fill, and one batch of cans is one step for both. Each
  tank keeps its own check, its own running shell and its own raw file; the
  page dips A then B after each batch (both readings can go in at once) and
  exports one CSV per tank. When
  both dips are in, the **pair view** compares the two residuals of the same
  batch: the same litres in both means the cans (one recount edits both
  tanks), litres only B misses means a spill on the way, a miss only one
  tank shows means that tank or its hose. The pour noise is common to both
  residuals and cancels in the difference, so the comparison is sharper than
  either check alone; a wide check on one side is reported as confirming
  nothing. The finding goes into the note of both raw files. The batch
  advice takes the tighter of the two 30 mm targets, with A's bottom watch
  and B's brim watch; the noise, the cans and the timers are one set for
  both tanks; the header's A/B switch turns the log, shell and campaign
  cards to the other tank. `TransferSession` in `site/site_core.js`;
  methodology §3.12; operator guide in `docs/site.md`;
  `tests/test_site.py::TestSiteTransfer`.
- Transfer dips enter both tanks at once: the dip card has one field and one
  button per tank, so each tank is checked as soon as its reading is in
  (`TransferSession.dipBoth`). The two fields sit in tinted cards under a
  **Same batch** header, each with a tank pictogram that shows the level and
  the arrow direction, a large arrow watermark in the input, and a role
  legend line. Each field carries a visual clue — a ↑ pump out badge on A's
  field and a ↓ pour in badge on B's, with the input edge in the same
  colour; the arrow follows the water. A decided tank's field and button are
  closed until *Take another reading*.
  The Log & charts tab carries its own A/B switch, and its table and chart
  headings name the tank they show, so the two tanks stay separate.
- The header tank switch now says what it does: a **Current tank** label,
  each button named with its role (`alpha · out`, `beta · in`), and a
  *current* marker on the Live tab's tank block. The level actions name the
  tank they apply to, an override follows the current tank while it waits,
  and the switch hides on Replay and Help, where it changes nothing.
- Reverse strapping (drain campaigns, §3.11): a tank that is already full is
  calibrated from the top down, with a pump that draws known volumes out in
  cans. `"direction": "drain"` in the campaign JSON; `calib init` infers it
  from falling heights. Steps stay positive litres and `resid = s - pred`
  keeps its sign meaning; a leak now gives `resid < 0`, and liquid that comes
  back gives `resid > 0`. Every module follows the direction: the fit and its
  covariance, the brim constraint (a drain out of the neck, `brim.neck_drain`,
  or the neck-entrance equality alone), the pair rule (`δ` flips), unknown
  drains, closure and QA (the books start at the first level in the shell),
  blocking, the grid search, the charts, the workbook formulas, the field
  check (NECK, BOTTOM-WARN), and the end heel in the shell record. The slope
  of an interval is taken at its upper level in both directions, so a drain
  gives the same numbers as the same steps poured in reverse
  (`tests/test_drain.py`).
- `examples/make_demo_drain.py` and `make demo-drain`: a synthetic drain
  campaign with known truth.

- On-site live dip check (§10a): `site/calib_site.html`, one offline page for
  a phone or tablet. It checks each dip before the next pour, while a re-dip
  is still possible. A running shell fitted on the accepted levels, with the
  on-site D and L estimates as priors, predicts each level; a miss, an unknown
  pour or a blunt prediction asks for a blind second reading. Confirmed misses
  become LEARNING, WATCH or ALARM (OBJECT? / LOSS?). The page exports the raw
  CSV for `calib init`.
- `calib site-page` builds the page from `site/page.html` and the one rules
  file `site/site_core.js`; `--check` fails on a stale page.
- `site/replay.js` replays a raw CSV through the live check;
  `site/simulate.js` measures the detection rate on synthetic campaigns.
- `docs/site.md`: the operator guide.
- Batch pours on the page: one tap for each can, a saved count with the time
  of each can, an advised can count, a brim warning, and a question on a
  second tap in less than 20 s. The raw file keeps the count in the note. An
  ALARM whose miss is a whole number of pour units names the count error
  (§3.10, §6.2).
- Each can carries its own size, so one batch can mix cans (2 × 200 L then
  4 × 100 L). The default can size is optional. The count-error hint tests
  every size in the batch.
- Timers on the page: a fill (pump) timer for each can with a small
  animation, a countdown and ±20 s. The alarm rings 15 s before the can is
  full, so the valve can be closed in time, and rings again at full; a
  settle timer after each batch rings when the level is ready to dip. The
  fill time per can size, the alarm lead, the settle time and the dip time
  are settings. The Now card estimates the time to half and to the brim from
  the running shell and the pour advice (`Session.fillPlan`); it uses the
  cycle time measured between taps, or the fill time when there is none.
  The drawing is a setting: *pour animation* off keeps the clock, the bar and
  the alarm.
- A **Settings** tab on the page collects every number the check uses: the
  tank record and priors (correctable after the first level), the noise and
  the datum, and the timers, alarm and device settings. The noise card is
  also the draft for the next campaign. `Session.setCampaign` refits the
  running shell on the accepted levels; a changed σ moves the z of every new
  check (§9.1) and restarts the noise scale, so an old z is not counted twice.
  The repeat limit follows σ unless it was set by hand. The timers and the
  noise fields left the Live and setup cards.
- The page shows four charts on the **Log & charts** tab: Miss, Slope profile,
  Drift with its ±3σ√n band, and z-score alarm (§6.6). A row of buttons or a
  swipe changes the chart. `Session.series()` in `site_core.js` supplies the
  data.
- The **Levels** table on the **Log & charts** tab edits the note of any level:
  *Edit* opens the note, *Save* keeps it and *Cancel* leaves it. The note goes
  into the raw CSV with its level. The site's own markers, such as *pour edited
  on site*, stay apart from the note and an edit cannot erase them.
- The Now card previews the level that the pour now in the pour panel must
  give, with its ±2σ band, the rise, the litres and whether one reading will
  do (`Session.preview`). The line follows the can tally and the litres field,
  and it hides while a level waits for its dip. It shows the expected level
  before the dip, which weakens the blind repeat (§10a.6): the page hides the
  check's prediction, not a number already read.
- The page is also published as a Cloudflare Worker with static assets
  (`wrangler.jsonc`, `make deploy`). The addresses are kept in `.env`.

### Fixed

- The live check's noise scale no longer counts the level under test. Its
  own first-dip miss inflated the scale that then judged its second reading:
  with few scored levels the median sat on the anomaly itself, and a
  confirmed miss shrank below the action bar (in a noiseless synthetic
  campaign, z = −26 became −2.4 and an ALARM turned into a WATCH). The
  scale is now set by decided levels only, as "earlier one-step misses"
  always said. The detection-rate table in `docs/site.md` was re-run with
  the fix: small shifts only (a 3 mm slip in a fill 89 → 92 % caught, in a
  drain 93 → 91 %, false alarms down in both).
- Workbook charts use bare `RRGGBB` in `a:srgbClr`. The matplotlib constants
  carry a leading `#`, which OOXML rejects; Excel then repaired the file by
  removing the drawing part ("Removed Part: /xl/drawings/drawing1.xml").
- Closure and QA agreement count the first row's pour. Without it the books
  were short by exactly that pour: the demo closure read −46 L (z = −3.7) and
  passed only because the limit is `3σ√n`. An unknown first pour enters at the
  back-predicted `F(H₀)`.
- The interval drift and the chart drift are one quantity again (§2). They
  differed by the first pour and by every unknown pour — 632 L at the demo
  overflow row. Unknown pours now keep the drift flat in both.
- Acceptance check 2 is falsifiable: it verifies that the shipped register
  carries every pair and every single-sided event, instead of comparing a set
  with a subset of itself. The dead `in_bands` term is gone (band-touching
  intervals are never candidates).
- The workbook certificate states the gate result of the shipped file. The
  workbook is gated, rebuilt with the result, and gated again; a failing gate
  now fails `calib fit` with exit code 2.
- `calib joint` no longer crashes on a campaign with an untrusted interval: it
  fits the trusted subset it already computed. It also refines the brim from a
  free fit, so it trusts the same intervals as `calib fit`.
- `calib field` prints the full session summary, survives a malformed entry
  instead of ending the session, and counts the starting volume in the closure.
- A pour recorded without a height is an error, not a silently renumbered row.
  `Row.line` is the file line, so corrections and exclusions keep their target
  when a blank line is skipped.
- The Huber scale is the median over trusted residuals only.
- The battery's `f_scale` no longer turns a missing median into `nan`.
- `Shell.flat` treats a numerically zero tilt as flat, so a fit that returns
  `eps ≈ 1e-18` does not silently switch to the numeric derivative.

### Added

- `calib init` writes a campaign JSON from the raw CSV. It infers the tank
  name, pour unit, overflow pour and heel hint, asks only for the tank record,
  and validates the file with the loader before writing it.
- `calib check` preflights a campaign JSON without a fit: resolved settings,
  the trusted and untrusted intervals with the reason, correction targets and
  unknown pours.
- Workbook Diagnostics: the sensitivity battery's r and L spread, and the
  measured `σh` beside the configured one.
- Anomaly register: an overflow interval whose pour *can* fill the gap is
  recorded, not dropped.
- `books_start` in `calib.data`: one definition of the books' opening balance.

## [1.0.0] - 2026-11-10

### Added

- Difference fit with multi-start, Huber comparison, brim and neck constraints.
- Profiles, lock cost, tilt test, parametric bootstrap and GLS.
- Anomaly register, pair rule, single-sided rule, object bookkeeping and closure.
- Interval blocking, unknown-pour back-prediction and quantized-pour search.
- Field protocol for per-pour validation against an adopted shell.
- Strapping and commercial tables with a generated certificate header.
- Values-only workbook with live charts and an optional audit sheet.
- Formula gate for every workbook cell.
- The seven diagnostic chart views and their composites.
- `calib` command line: `fit`, `field`, `joint` and `gate`.
- Synthetic demo campaign with a known truth.
