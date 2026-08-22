---
slug: aligned-log-output
status: accepted
date: 2026-08-22
---

# ADR-0016: One aligned table for the log output with role, step and token columns

## Context

The wrapper's streaming log is noisy and ragged: step-completion markers
duplicate the pinned live rows, captured step stdout (`SESSION:`, `saved
adr:`, `implementation check:`) is printed with indentation tails, two
formats (the wrapper's and the engine's) are mixed in one log, and every
line element starts at a random position. Human requirements: every log
line originates from exactly one actor — planner, executor or harness —
and everything currently printed "by the engine" is converted into
`[harness]` rows; lines are aligned into a table with invisible columns,
where the widths of the static content are determined before the run
starts, and the numeric token columns adapt during the run to the largest
number seen in the run's history. Research confirms this is the
established model: the write-filter pattern (column width = content
maximum, numbers right-aligned), no tabs and no truncation to terminal
width in non-TTY output, measuring width in terminal cells rather than
codepoints.

## Decision

1. **One table row for the whole streaming log**: `[hh:mm:ss] [<role>]
   <spin> [<step> N/M] <tokens>` with the columns: timestamp, role,
   spinner, step, token section (the cache, reasoning, input, output,
   price sub-columns).
2. **Exactly one signature per row.** Each row carries one of the
   `[planner]`, `[executor]`, `[harness]` signatures (plus
   `[planner#<kind>]` for the parallel review checks). Step-completion
   markers disappear together with the statuses: completed is implied,
   failures are visible through the step's stderr rows and the final
   run-completion row. The captured stdout/stderr of steps and engine
   diagnostics become `[harness]` rows of the same table; service lines
   with a recoverable id (`SESSION:`) are dropped from the output
   entirely.
3. **Column widths.** The static columns (role — sized to the longest
   possible label including the forks; step — sized to the longest step
   name with an allowance for the widest `N/M` form) are measured once
   before the run starts. The dynamic token sub-columns right-align and
   grow to the largest value seen during the run; already-printed history
   rows are never re-rendered. A runtime step-name lengthening (loop
   iteration suffixes, fan-out indices) beyond the static width widens
   the column for the rest of the run.
4. **The same format on a non-TTY** (without the spinner), with no line
   truncation to terminal width — no data is lost in a redirected log.
5. The run-completion rows (`run failed`, `resume with:`) get the
   `[harness]` signature; the `=== run statistics ===` block and the
   latency table keep their form. Out of scope: spinner cadence,
   heartbeat policy, gate-open buffering, the gate menus themselves.

## Alternatives

- **Table libraries (tabulate, rich.Table/Live).** Rejected: an extra
  dependency (rich was already dropped in ADR-0011/0012), tabulate needs
  the whole table in memory and cannot stream, rich.Live conflicts with
  the project's own block and gate-buffering mechanics.
- **Buffering the whole history and reprinting the table when the width
  grows** (Flush tabwriter/tabulate semantics). Rejected: the live status
  needs immediate rows, terminal history is immutable, and reprinting on
  every tick is the same noise we are moving away from.
- **Tab separators and tab padding.** Rejected: tab width depends on the
  terminal; alignment drifts in files.
- **Arbitrary fixed column minimums.** Rejected based on the docker stats
  experience (an over-generous min-width drew complaints about extra
  width and wrapping).
- **Alignment at the decimal point / centered.** Rejected: tokens are
  integers with space thousands separators, price is a fixed `$X.XX`;
  right alignment is enough.
- **Truncating rows to terminal width in non-TTY.** Rejected: silent data
  loss (a documented rich trap in non-TTY).

## Consequences

- Positive: a scannable table, one row per step, no duplicate markers;
  failure visibility is preserved through stderr rows and the final row.
- Positive: one format for TTY and redirected logs, one actor signature
  per row — the "our format only" requirement (ADR-0013) is carried
  through to the end.
- Positive: no new dependencies; the existing block-redraw and gate
  buffering mechanics do not change.
- Negative: growing numbers shift the live row on redraw (accepted); the
  block can grow up to the terminal width.
- Negative: non-ASCII content in captured output requires measuring width
  in cells, otherwise the columns drift.
- Negative: the completion status is no longer visible per line — a
  failure is recognized by the step's error rows and the final row, not
  by a `(failed)` label on the step.
- Partly builds on ADR-0011/0012 (live-line format), ADR-0013 (strict log
  format), ADR-0002 (failure visibility).

## Acceptance Criteria

- Every streaming-log line has the form `[hh:mm:ss] [<role>] …` with a
  role from planner/executor/harness (plus the forks), and the role and
  step columns are aligned to the width of the longest label determined
  before the run starts; token numbers are right-aligned and adapt to the
  maximum seen during the run.
- The log contains no step-completion markers or statuses; `SESSION:`
  rows are absent; captured step output and engine diagnostics appear as
  `[harness]` rows.
- A runtime step-name lengthening widens the column for the rest of the
  run; printed rows are never re-rendered.
- Non-TTY output uses the same alignment without the spinner and without
  line truncation.
- The final completion/resume rows carry the `[harness]` signature; the
  statistics block and the latency table are unchanged.
- Spinner cadence, heartbeat, gate buffering and gate-menu rendering are
  unchanged.
