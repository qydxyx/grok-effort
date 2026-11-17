# grok-effort

Hermes plugin that sets `reasoning.effort` for Grok models that accept the parameter, regardless of the global `agent.reasoning_effort`.

Default is **low**. Override with env `GROK_EFFORT` (`low` | `medium` | `high` | `xhigh`), read per request.

`grok-4.7` accepts the field but is missing from Hermes' stock effort allowlist, so a config override is resolved and then dropped. This plugin adds that prefix so the level reaches the wire. Models that reject the field are left unchanged, so they do not 400.

## How it works

Three module-level mutations, all re-read by upstream at call time — no transport patching:

1. **`agent.model_metadata._GROK_EFFORT_CAPABLE_PREFIXES`** — widened with `grok-4.7`. This is the gate the xAI branch of `_reasoning_fields` checks before emitting `reasoning.effort`.
2. **`agent.model_metadata.is_grok_46_family`** — widened to the 4.7 family. This predicate picks the xAI effort ladder in `codex._resolve_reasoning`: the 4.6 family gets `low/medium/high/xhigh`, everything else is clamped to the legacy `low/medium/high`. Stock only knows `grok-4.6`, so `GROK_EFFORT=xhigh` used to be silently clamped to `high` on grok-4.7 even though `api.x.ai` accepts it (verified live). The plugin widens the predicate and leaves upstream's clamp in charge.
3. **`hermes_constants.resolve_reasoning_config`** — overridden so allowlisted Grok models always resolve to `GROK_EFFORT`, ignoring `agent.reasoning_effort`. This is the single chokepoint every surface uses (CLI, gateway, TUI, cron, `/model`).

Version 1.1.0 also monkeypatched `agent.transports.codex._reasoning_fields`. That wrapper hardcoded the then-current signature and broke **every** xAI request with `TypeError: got an unexpected keyword argument 'profile_reasoning'` once upstream added that parameter — the failure happened before the request was sent, and Hermes misreported it as an auth rejection. The wrapper was pure duplication (the upstream xAI branch already re-checks the allowlist and reads `effort` from the `reasoning_config` this plugin controls), so 1.2.0 removed it.

## Install

```bash
hermes plugins install qydxyx/grok-effort
```

or copy this directory to `~/.hermes/plugins/grok-effort/` and run `hermes plugins enable grok-effort`.

Confirm the log contains `grok-effort: effort-capable Grok models forced to low` (or the `GROK_EFFORT` you set).

## Upgrading from 1.1.0 / 1.2.0

A running gateway keeps monkeypatched callables in memory; `plugins enable/disable` only loads or unloads modules and does **not** restore them. 1.3.0 therefore drops the leftover itself at register time, logging:

```
grok-effort: dropped a stale _reasoning_fields wrapper left by an earlier version
```

No gateway restart is required — a plain `hermes plugins update grok-effort` (or disable/enable) heals an in-place upgrade.

## Verify

```bash
python3 scripts/verify.py
```

Drives the real `ResponsesApiTransport.build_kwargs()` path, then checks:

- `grok-4.7` is allowlisted and on the `xhigh` ladder, `grok-4.5` stays on the legacy ladder, `grok-2` is untouched;
- default effort is `low` and the env override wins over `agent.reasoning_effort`;
- `GROK_EFFORT=xhigh` reaches the wire for 4.6/4.7 and is clamped to `high` for 4.5;
- the transport carries no monkeypatch;
- a simulated 1.1.0 wrapper left in the process is dropped by `register()`.

Exits non-zero on any regression.

## Wire notes (verified against `api.x.ai/v1/responses`)

| model | low | medium | high | xhigh |
| --- | --- | --- | --- | --- |
| grok-4.6 | 200 | 200 | 200 | 200 |
| grok-4.7 | – | 200 | – | 200 |
| grok-4.5 | – | – | 200 | 200 (clamped to high by Hermes) |

`grok-4.5` answers 200 to `xhigh` too, but it stays on the legacy ladder until xAI documents the level for that family.
