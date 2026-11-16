# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- On-site page: − and + buttons beside the can size step it by the pour
  unit (`−50 L`, `+50 L`); never below one pour unit.
- On-site page: a drain time per can size (Timers, alarm and device): the
  time to empty one can. The time to half and to the brim (or the bottom) is
  the cans left × (fill time + drain time).
- Now card: *Your taps* shows the measured time per can; a button sets the
  drain time from it (tap gap − fill time).
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
