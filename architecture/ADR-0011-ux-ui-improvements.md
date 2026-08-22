---
slug: ux-ui-improvements
status: accepted
date: 2026-08-18
---

# ADR-0011: UX/UI Improvements: Live Status Lines, GUI Editor, task-pipeline Simplification

## Context

Seven UX/UI complaints were collected from the user (agreed in three motivation rounds, see `study.md`
rev. 3 and `proposal.md`):

1. The study.md text is truncated at the motivation gate — the engine hard-cuts gate-shown files at 200
   lines while the gate message itself is unlimited.
2. feedback.md opens in nano (the environment sets `EDITOR=/usr/bin/nano`) — a preinstalled GUI editor in
   a separate window is needed. Target platforms: Fedora Workstation (default editor — GNOME Text
   Editor, shipped as the Flatpak `org.gnome.TextEditor`; it has no `--wait` flag) and macOS (TextEdit,
   always preinstalled; `open -a TextEdit -W` blocks until the app closes).
3. The proposal approval gate duplicates the motivation approval — it must be removed (only the gate;
   research and proposal.md remain).
4. Logs are polluted by the model's reasoning text. Instead — live status lines with cumulative tokens.
   The agent log's step-finish events already carry cumulative token usage (input, output, reasoning,
   cache) and cost.
5. The latency table lacks percentages and shows durations in `HH:MM:SS` — percentages of the total wall
   time and the `Xm` format are needed.
6. Step progress is invisible — an N/M indicator is needed.
7. The motivation clarification round limit must disappear; the engine sets a fallback of 10 on an
   invalid `max_iterations` and there is no "infinity". The user chose a cap of 100.

Verified locally against the installed specify-cli 0.16.3 and real agent `.jsonl` logs.

## Decision

1. **Full study.md text at the gate.** The motivation gate shows the full study text via its unlimited
   message instead of the truncated file view; a display step runs before the gate inside the
   motivation loop, so each clarification round shows the current study.md.

2. **GUI editor for feedback gates.** Feedback gates open a native GUI editor in a separate window:
   - macOS: TextEdit launched in blocking mode; after closing, the wrapper answers the gate `continue`.
   - Linux: GNOME Text Editor launched non-blocking via Flatpak (when installed) or the plain
     executable, falling back to the desktop `gio open`/`xdg-open`; in this case the wrapper does not
     answer the gate itself — the gate stays interactive (the user closes the window and presses
     `continue`).
   - Fallback without a GUI (nothing found / no TTY): the terminal chain `$VISUAL → $EDITOR → nano → vi`,
     the gate interactive.
   `modus-operandi edit` continues to use the terminal chain — for it nothing changes.

3. **Remove the proposal gate.** The proposal approval gate is removed from the pipeline (research and
   proposal.md remain, and research proceeds straight to the ADR step); the revision loop and its
   configuration are dropped; the research prompt no longer says the document is shown to the human for
   approval.

4. **Live token status lines.** Reasoning text events are no longer printed. Instead, one live line per
   active process (role; per fork with parallel review forks) shows cumulative per-role token sums
   (cache read, reasoning, input, output) and the accumulated price, with thousands separators; the
   current step is taken from the pipeline state. The line updates in place without scrolling, and when
   a step completes the line is pinned into the terminal as history and a new live line opens for the
   next step of the same role. On non-TTY/redirected output: no ANSI, one ordinary line per step-finish
   event. Live lines respect the existing buffering policy: while a gate menu is open they are buffered,
   after closing they flush.

5. **Latency table.** Stage durations are printed in whole minutes with the `m` suffix, and a percentage
   column is added — each stage's share of the total wall time, formatted with one decimal place; the
   fan-out details show each check's percentage and the fan-out wall percentage of the same total.
   `wall time` in the run statistics block stays `HH:MM:SS`.

6. **N/M progress.** The step marker prints as `--- step <id> (completed) [<N>/<M>]`, where N is the
   current step index + 1 and M is the number of top-level steps of the installed workflow; live lines
   show the step as `[<step> <N>/<M>]`. Progress is omitted gracefully (no crash) when the workflow file
   cannot be read.

7. **Unlimited motivation.** The motivation loop gets the literal `max_iterations: 100`; the config key
   that previously overrode it is removed from defaults, validation, and `config.example.yml`, so the
   literal survives and the loop becomes practically unbounded.

## Alternatives

- **Keep the terminal editor (as is).** Rejected: the user wants a GUI window; `EDITOR=nano` in the
  environment still overrides the variables.
- **Detect window closing on Fedora (polling the process/window).** Rejected: fragile (Flatpak sandbox,
  one process for several windows); the user explicitly chose the manual mode.
- **A summary instead of the full text at the gate.** Rejected: the full text is needed; the message
  bypass is unlimited and verified against the engine's sources.
- **The rich/tqdm library for live lines.** Rejected: an extra dependency; in-place cursor ANSI control
  is enough.
- **Remove `max_iterations` entirely.** Rejected: the engine silently sets the fallback 10 — the loop
  would become shorter, not longer.
- **Percentages without fan-out details.** Rejected: the feedback asked for percentages for fan-out
  details too.

## Consequences

- Positive: the terminal shows a compact status (N/M progress, cumulative tokens and cost), reasoning no
  longer pollutes the screen, and step history remains; the motivation study is visible in full.
- Positive: one approval stop instead of two; motivation is clarified without a practical limit (until
  `clear`).
- Positive: a native GUI editor on both platforms without new dependencies.
- Negative: ANSI output complicates the wrapper (careful degradation for non-TTY is needed); on Fedora
  the feedback gate is semi-manual (closed the window → you press `continue` yourself).
- Negative: nobody reads proposal.md before the ADR anymore; with poor research, problems surface at
  implementation/review.
- Negative: `max_iterations: 100` is technically not infinity (practically unreachable).

## Acceptance Criteria

- The full study text is visible at the motivation gate.
- Feedback files open in a native GUI editor where available, with a terminal fallback.
- The proposal approval gate is removed.
- Terminal output shows live status with cumulative tokens, N/M step progress, and a latency table with
  percentages.
- The motivation clarification loop is practically unbounded.
