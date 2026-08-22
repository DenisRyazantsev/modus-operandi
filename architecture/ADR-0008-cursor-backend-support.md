---
slug: cursor-backend-support
status: accepted
date: 2026-08-16
---

# Supporting Cursor as a Second Backend for the Planner → Executor Pipeline

## Context

The project runs stably on opencode: two warm sessions (planner on a strong LLM, executor on a cheap one) are kept, roles are defined by per-backend agent files (frontmatter with provider/model/reasoning plus the system-prompt body), and the session layer stores session ids per task and resumes sessions between steps so the executor does not re-read the project from scratch. The same scenario — two hot sessions, one strong LLM and one cheap one — needs to be available for Cursor. Research of the official Cursor CLI documentation showed:

- The CLI is invoked as `cursor-agent` with a non-interactive print mode (`-p/--print`) and JSON output.
- The model is chosen per invocation via `--model`, because Cursor has no `--agent` equivalent; sessions resume via `--resume <chatId>`, and `agent create-chat` creates an empty chat and prints its id.
- Headless auto-approval is achieved with `--force`/`--trust` flags.
- **Critical:** the CLI has no session-id flag — it returns the session id in its own JSON output, and passing a made-up id to `--resume` silently opens a fresh chat, i.e. context is silently lost. The id must therefore always be taken from Cursor itself, never synthesized.
- There is no separate flag for the system prompt or reasoning effort: the role must be given as text in the prompt, and high-effort model variants are encoded in the model slug.

## Decision

Introduce the backend choice at the pipeline level and mirror the opencode logic for Cursor through the same session layer. The config gains separate sections per backend, each with two model slots (planner and executor, configured independently), and a top-level `backend` key selects the active one (`opencode` by default). The existing shared models section is folded into the opencode section on load so existing configs keep working; validation requires both model slots for cursor, symmetric to the required opencode fields. For the MVP a single available model may fill both slots — that is a config value, not a structural constraint.

A global `--backend` flag (`modus-operandi --backend cursor`) overrides the config for one run; the effective backend (flag over config over default) is exported to the steps' environment (`MO_BACKEND` plus the selected backend's models for the roles), so the workflow itself does not change. Call dispatch branches by the effective backend: opencode runs as before; cursor invokes `cursor-agent` in print/JSON mode with force/trust, the workspace, `--model` with the role's model, and `--resume` when a chat already exists. On first run, a chat is minted via `agent create-chat` before the prompt runs. Warm sessions reuse the same per-task session store keyed by role, now holding the cursor chat id; the id is always taken from Cursor itself (`agent create-chat` output or the `session_id` field of the JSON result), never synthesized, and `--reset` deletes the saved id so the next run mints a fresh chat.

Since Cursor has no agent or system-prompt flag, the role body is prefixed to only the first message of a session (when the chat was just created); on repeated `--resume` calls the bare prompt is sent, because the session is hot and the LLM already remembers its role. The role body is kept in a single source of truth read at dispatch time. Slug generation for cursor uses the CLI's text-output mode instead of JSON-stream parsing. Stale-process cleanup checks the process name corresponding to the active backend, and prerequisites validation matches the selected backend — opencode is not required when cursor is selected and vice versa. Callers that go through the dispatch layer need no changes.

## Alternatives

- **Roles via Cursor rules / AGENTS.md instead of an inline prefix on the first message** — rejected: always-applied rules load into every request and would pollute the user's interactive sessions; the inline prefix is isolated to the backend, works in any project, and being sent once is cheap.
- **A separate script per backend instead of a branch in the session layer** — rejected: duplicates session/pid/log handling and would require touching every caller; a backend branch is a single point of edit.
- **`--continue` instead of named sessions** — rejected: it resumes "the last" session globally and cannot distinguish roles or tasks; exactly two warm sessions are needed, one per role, addressed explicitly by chat id.
- **Synthesized session ids for `--resume`** — rejected: Cursor ignores foreign ids and silently loses context (see Context).
- **A shared models section with a backend flag instead of separate per-backend sections** — rejected: the backends have different setting sets (provider/reasoning vs a single slug); a shared section creates dead fields and confusion.
- **One shared cursor model for both roles** — rejected: the structure must stay symmetric to opencode — two independent slots — so planner and executor can later be split into strong/cheap without reworking config and logic.
- **Backend only via config, without a CLI flag** — rejected: selecting the backend per run without editing the config is convenient; the config remains the default.
- **Support Claude Code instead of or in addition to Cursor** — rejected: the task is formulated specifically for Cursor, and its CLI covers the needed scenario (headless, resume, per-model); another backend can be added later with the same technique.

## Consequences

- The same two-warm-sessions, strong-plus-cheap architecture works on Cursor without rewriting pipeline callers or workflow steps.
- A single source of truth for roles across both backends; the role is sent once, so input tokens on repeated calls do not inflate.
- Session ids are always native to Cursor, so silent context reset is excluded.
- Separate config sections with two model slots per backend stay symmetric to opencode — migration and later splitting of models require no structural change.
- `cursor-agent` is in beta; flags may change between releases.
- Cursor requires an active subscription/login (or an API key for CI); model names do not match across backends, so each backend has its own config.
- On the free tier a single model fills both slots — no strong/cheap savings in the MVP — though the structure allows it later.

## Acceptance Criteria

- The config supports two independent backends with two model slots each and a top-level selection; legacy shared-model configs keep working.
- The CLI flag overrides the backend per run; without it, the config value (default `opencode`) is used.
- The chosen backend's CLI is invoked with the role's model — planner and executor each get their own slot.
- Warm sessions are reused per role, with ids always taken from the backend itself; reset clears the saved id and the next run creates a new chat.
- Prerequisites validation matches the selected backend.
