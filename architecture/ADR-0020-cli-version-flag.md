---
slug: cli-version-flag
status: accepted
date: 2026-08-26
---

# ADR-0020: Version Flag for the modus-operandi Launcher

## Context

The `modus-operandi` CLI is a hand-rolled dispatcher without a CLI framework, and it gives the user no way to learn the installed version — even though the version string already exists in the runtime, where the installation bootstrap uses it as the install marker and in the "updated to …" message. The tool is distributed through PyPI and updated via `pip install -U`, so users need a version check for bug reports, update verification and scripted checks; the ecosystem treats `--version` as a standard contract (GNU Coding Standards, clig.dev, argparse/click defaults, AuditBuffet). The launcher already has the exact behavioural pattern for a side-effect-free flag: `--help`/`-h` is dispatched as a pure signal that prints to stdout and exits 0 without bootstrapping the installation.

## Decision

Add global `--version`/`-V` flags to the launcher, recognized only in the main-command position (`modus-operandi --version`, including after the `--backend` global flag) and never after a subcommand.

- **Output**: `modus-operandi <version>` on stdout, exit 0 — the parseable "program name + version" line (name as a constant, version from the running code).
- **Behaviour**: exactly like `--help` — a pure dispatch signal that prints and exits 0 without bootstrapping the installation and without any side effects (no install artifacts are created).
- **Version source**: the package's `__version__` declaration — the single source already mirrored in `pyproject.toml` and stamped from the git tag by CI (ADR-0018) — not a runtime metadata lookup.
- **Combination with `--help`**: when both flags are passed, the first one in the main-command position wins (`--version --help` prints the version, `--help --version` prints the help).

The decision follows the ecosystem convention: `--version` printing "<program> <version>" to stdout and exiting 0 matches the defaults of argparse (`%(prog)s <version>`) and the GNU standard, and `-V` is the established short form that avoids the `-v`/verbose clash (clig.dev, kubectl). The version source is deliberately the existing `__version__`: it works identically from the checkout-based dev launcher and from an installed package with no possibility of drift, whereas installed-distribution metadata would report a stale version (or fail) when the command runs from a checkout. The no-bootstrap behaviour mirrors `--help` and keeps the version probe usable on a fresh or broken installation, where rendering would fail.

## Alternatives

- **`-v` as the short form** — rejected: `-v` conventionally means verbose; `-V` is the established version short form.
- **Bare version output** (the version number only) — rejected by the user: the convention is "program name + version".
- **`importlib.metadata.version()` as the source** — rejected: in the dev flow (launcher running from a checkout) it would report the version of the installed pip distribution — stale or absent — instead of the running code; `__version__` is already single-sourced and CI-stamped.
- **A `version` subcommand** (kubectl-style, with formats/JSON) — rejected: the need is a simple version check; a subcommand is justified for complex queries that were not requested.
- **Rich output** (git hash, Python version, build metadata) — rejected: not requested; the user asked for the current version.
- **Recognizing the flag after a subcommand** (`modus-operandi task --version`) — rejected by the user: only the main-command position, matching the pip precedent of not accepting `--version` in subcommands.
- **Migrating the CLI to a framework** (argparse/click) to get the flag for free — rejected: a parser rewrite is out of scope for a flag; the existing signal pattern already covers the behaviour.
- **Printing to stderr or exiting nonzero** — rejected: contradicts the convention (stdout, exit 0) that scripts rely on.

## Consequences

- Positive: users and scripts can check the installed version, consistent with ecosystem conventions (name + version on stdout, exit 0).
- Positive: no new version source — the flag shows exactly the version the running code declares, from a checkout or an installed package alike.
- Positive: cheap to build — the flag reuses the established signal pattern of `--help`, with no bootstrap side effects.
- Negative: a second dispatch signal alongside the help signal duplicates a small amount of dispatching logic.
- Negative: the output format (`modus-operandi 0.0.0.dev0`) differs from click's default (`prog, version 1.2.3`); it matches the argparse/GNU convention instead.
- Negative: `--version` after a subcommand is not reported as a version request and falls into the subcommand's ordinary argument handling (for `task`, it becomes task text) rather than producing an error.

## Acceptance Criteria

- `modus-operandi --version` and `modus-operandi -V` print `modus-operandi <version>` (the current package version) to stdout and exit 0.
- The flag works in the main-command position after `--backend`: `modus-operandi --backend cursor --version` prints the version and exits 0.
- The version flag causes no bootstrap: no install artifacts are created by it.
- `modus-operandi task --version` is not treated as a version request — the flag is recognized only in the main-command position.
- Passing `--version` together with `--help` resolves by position: the first flag in the main-command position wins.
- The usage/help text documents the new flag.
