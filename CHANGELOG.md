# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

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
