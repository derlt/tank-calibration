# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
