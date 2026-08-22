---
slug: global-cli-binary
status: accepted
date: 2026-08-14
---

# ADR-0004: Global CLI Command `modus-operandi` for Running adr-pipeline and review-pipeline from Any Project

## Context

Currently, the pipeline is launched in one of two ways, and both are inconvenient: either a long command with a full
path to the workflow file, or — after per-project registration (`specify init` plus a registration step in each
project) — a short workflow id. The user wants to get rid of this per-project registration and have a globally
installed command: they type a short command (`modus-operandi`) from any project, pass the feature description as an
argument, and the right pipeline runs.

Verified facts about the current implementation:

- The wrapper (the one providing timestamps, live step output, token/time statistics, and sound) already accepts the
  full path to the workflow file as its first argument and forwards the remaining arguments to the run command.
- `specify workflow run <full-path-to-yml>` works in any project without `.specify/` and without `specify init` — this
  is already documented in the README ("In any project (no `specify init` required)").
- Both workflows are installed centrally: `adr-pipeline` requires the `feature` input (`task_id` is optional);
  `review-pipeline` optionally accepts a branch-diff flag.
- The installer renders all installed files with absolute-path substitution at install time; there is no separate
  directory for a global binary yet.

## Decision

Add a thin global launcher command `modus-operandi`, installed once and callable from any project; it does not "register"
anything itself and does not require `specify init` in the project:

1. **Launcher as a global binary.** The installer renders an executable `modus-operandi` with absolute paths to the
   installed wrapper and both workflow files baked in at install time, and places it in the standard per-user bin
   directory (created if needed, made executable). Uninstallation removes it.
2. **Command surface.** The first argument is a subcommand selecting the pipeline. The launcher delegates to the
   already-installed wrapper, passing the full workflow path (not a short id that would require registration), so
   timestamps, live log, statistics, and sound are preserved:
   - `modus-operandi adr "<feature description>"` runs `adr-pipeline` with the feature input; all non-flag arguments after
     `adr` are joined into a single feature string.
   - `modus-operandi review` runs `review-pipeline` with the default input (the whole project code);
     `modus-operandi review --branch-diff` passes the branch-diff flag.
   - Other `-i key=value` arguments (e.g. `-i task_id=my-feature`) are forwarded unchanged.
   - `modus-operandi --help` (or `-h`) prints usage (list of subcommands and examples) and exits with code 0; `modus-operandi`
     without arguments and `modus-operandi <unknown-subcommand>` print usage and exit with a non-zero code.
3. **PATH.** The installer does not edit shell configs; after installation it checks that the per-user bin directory
   is present in `$PATH`, and if not — prints a warning with instructions (add the directory to PATH or invoke by full
   path). The installation does not fail.
4. **Do not change anything in the pipelines.** The workflows, run scripts, sessions, and the step contract are
   untouched; the launcher is only a new entry point on top of the existing wrapper.

## Alternatives

- **Leave as is: full path or per-project registration.** Rejected: the user explicitly wants "installed once — and
  the command is callable from anywhere", and registration requires `specify init` and repeating it in every project.
- **Document a shell alias/function in dotfiles.** Rejected: it is not a real installed binary, breaks on shell/config
  change, and is not "installed once"; does not solve the request.
- **Package it as a real Python package with a console script, installed via a package tool.** Considered and
  deferred: it is the "more proper" global binary and automatically puts the script on PATH, but it changes the
  installation model (currently — a simple installer copying rendered files, without packaging) and would require deep
  refactoring. The rendered launcher matches the current model; packaging can be revisited separately.
- **Put the launcher in a shared scripts directory and add that directory to PATH by editing shell-rc.** Rejected:
  silently editing user rc files is invasive; the standard per-user bin directory is cleaner and more predictable.

## Consequences

- Positive: install once — then `modus-operandi adr "<feature>"` and `modus-operandi review` from any project without `specify
  init`, registration, or a long path; matches the user's "ideal".
- Positive: the launcher inherits all wrapper capabilities (timestamps, live log, statistics, sound, resume hint)
  without duplicating logic.
- Positive: changes are additive and localized (a new launcher template, a new entry in the paths module, and a PATH
  check); workflows, agents, and sessions are unchanged.
- Negative: the `modus-operandi` command resolves only if the per-user bin directory is on `$PATH`; on systems where it is
  not, the directory must be added to PATH once (the installer warns about this).
- Negative: the launcher bakes in absolute install paths at install time; moving the installation would break it until
  the next install.
- Negative: one more command name to remember and document (though shorter than the old incantation).

## Acceptance Criteria

- One install produces a global command callable from any project.
- The subcommands launch the corresponding pipelines with the given inputs: `modus-operandi adr "<feature>"` starts
  `adr-pipeline` with the feature input, `modus-operandi review` starts `review-pipeline` with the default input, and
  `--branch-diff` / forwarded `-i key=value` arguments are passed through — all without project initialization or
  registration.
- Help exits 0, unknown usage exits non-zero: `modus-operandi --help` (and `-h`) prints usage and exits 0; no arguments or
  an unknown subcommand print usage and exit non-zero.
- Launched runs go through the wrapper: timestamps and the statistics block are present in the output, as with a
  direct wrapper invocation.
- If the per-user bin directory is absent from `$PATH`, the installer prints a warning with instructions but does not
  fail and does not edit shell configs; uninstallation removes the command.
