---
slug: config-edit-command
status: accepted
date: 2026-08-15
---

# ADR-0005: `modus-operandi edit` Command (Config Editing and Application) and Removal of the Obsolete `--register`

## Context

Changing settings (models, iteration limits, state directory, etc.) requires the user to locate the installed config
file, edit it by hand, and then re-run the installer before changes take effect. The config path is documented, but the
user must remember or search for it, and every config change requires a separate manual reinstall. The user requirement
is a command "from the binary itself": type `modus-operandi edit` so the config opens in a terminal editor, and have the
edit take effect immediately — the next `modus-operandi` invocation must already work with the updated settings, without a
separate manual reinstall step.

In addition, with launching now happening only through the global `modus-operandi` binary, the per-project registration mode
(installing workflows by id into a specific project) became unused: it survives only as dead code, documentation, and
tests, which the user asked to clean up.

After adoption, a review reworked how the `edit` subcommand is wired internally: editor resolution and launching moved
out of the pure command-mapping function into the execution path, so "subcommand → execution path" lives in one place.
The observed behavior is unchanged; only the internal split of responsibilities was adjusted.

## Decision

Add a new `modus-operandi edit` subcommand that opens the installed config in a terminal editor and, after the editor exits,
applies the config so the next `modus-operandi` invocation already works with the updated settings. The config path is baked
in at install time, so the user never passes or searches for it. The editor is resolved from the environment
(`$VISUAL`, then `$EDITOR`, both allowed to contain arguments) with `nano`/`vi` as fallback, and is launched as a child
process inheriting the terminal; if it cannot be launched, the command errors out with a non-zero exit code.

Applying the config revalidates it and regenerates all rendered artifacts through a lightweight `--apply` mode of the
installer that skips prerequisite and dependency checks and next-steps hints — a full re-install is unnecessary when
only the config changed. An invalid config is never silently applied: validation errors surface and the command exits
with a non-zero code.

Remove the obsolete per-project registration mode (`--register`) entirely — code, documentation, and tests — since
launching happens only through the global `modus-operandi` binary.

## Alternatives

- **Leave as is: document the config path and edit manually.** Rejected: the path is already documented, but the user
  explicitly asks for a command that opens the file from the binary without making them search for it.
- **Make `edit` a flag of the installer or a separate script.** Rejected: the user wants a command in the global
  `modus-operandi` binary, which is already on PATH and callable from any project.
- **Hardcode opening the config in `vi`/`nano`, ignoring environment variables.** Rejected: does not respect user
  editor preferences; standard resolution from `$EDITOR`/`$VISUAL` is the expected behavior.
- **Only open the file, leaving config application manual.** Rejected: the user explicitly requires that the next
  `modus-operandi` call works with the updated config; a manual step breaks this.
- **Apply the config with a full re-run of the installer.** Rejected: noisy and repeats prerequisite and dependency
  checks that do not change the result on apply; the lightweight `--apply` mode was chosen.
- **Apply the config by embedding the re-render in the launcher itself.** Rejected: would duplicate templates and
  render logic outside the source; calling the installer matches the baked-in-paths model already in use.
- **Make `edit` a full config manager (validation, interactive option selection, application).** Rejected: beyond the
  scope of the request — the user asks to open the file in an editor and have edits applied.
- **Keep `--register` as a fallback launch mode.** Rejected: it is a dead path that would need maintaining and
  documenting; the user works only through the binary, so per-project registration is not needed.
- **Remove only the `--register` documentation, keeping the code.** Rejected: leaves dead code and tests without a
  user — exactly what was asked to be removed.

## Consequences

- Positive: editing and applying the config is now one command, `modus-operandi edit`, runnable from any directory, and the
  next `modus-operandi` invocation immediately works with the updated settings.
- Positive: an invalid config surfaces right at application time, not at the next pipeline run.
- Positive: the change is additive — workflows, agents, and pipeline steps are untouched — and the user's editor is
  respected (`$VISUAL`/`$EDITOR`) with a sensible fallback.
- Negative: `edit` depends on the repository still being present (the installer path is baked in at install time); if
  the clone is moved or deleted, the editor will open but application will fail until the next install.
- Negative: applying after every `edit` regenerates artifacts and runs verification, adding delay after exiting the
  editor.
- Negative: a config edited into an invalid state is not applied and stays "as written" until fixed via another
  `modus-operandi edit`.
- Positive (cleanup): removing `--register` reduces code, documentation, and tests, and the installer surface reduces
  to a single launch method — the global `modus-operandi`.
- Negative (cleanup): breaking change — `--register` and running workflows by id are no longer supported; users with
  per-project registrations must switch to `modus-operandi`.

## Acceptance Criteria

- `modus-operandi edit` opens the installed config in the user's editor and applies it on exit so the next run uses the
  updated settings.
- An invalid config fails loudly without silent application.
- The obsolete per-project registration mode no longer exists.
