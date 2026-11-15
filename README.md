# grok-effort

Hermes plugin that sets `reasoning.effort` for Grok models that accept the parameter, regardless of the global `agent.reasoning_effort`.

Default is **medium**. Override with env `GROK_EFFORT` (`low` | `medium` | `high` | `xhigh`).

`grok-4.7` accepts those values but is missing from Hermes' stock effort allowlist, so a config override is resolved and then dropped. This plugin adds that prefix so the level reaches the wire. Models that reject the field are left unchanged, so they do not 400.

## How it works

Two module-level mutations, both re-read by upstream at call time — no transport patching:

1. **`agent.model_metadata._GROK_EFFORT_CAPABLE_PREFIXES`** — widened with `grok-4.7`. This is the gate the xAI branch of `_reasoning_fields` checks before emitting `reasoning.effort`.
2. **`hermes_constants.resolve_reasoning_config`** — overridden so allowlisted Grok models always resolve to `GROK_EFFORT`, ignoring `agent.reasoning_effort`. This is the single chokepoint every surface uses (CLI, gateway, TUI, cron, `/model`).

Version 1.1.0 also monkeypatched `agent.transports.codex._reasoning_fields`. That wrapper hardcoded the then-current signature and broke **every** xAI request with `TypeError: got an unexpected keyword argument 'profile_reasoning'` once upstream added that parameter — the failure happened before the request was sent, and Hermes misreported it as an auth rejection. The wrapper was pure duplication (the upstream xAI branch already re-checks the allowlist and reads `effort` from the `reasoning_config` this plugin controls), so 1.2.0 removes it.

## Install

Copy this directory to `~/.hermes/plugins/grok-effort/` and enable it:

```bash
hermes plugins enable grok-effort
```

Confirm the log contains `grok-effort: effort-capable Grok models forced to medium` (or the `GROK_EFFORT` you set).

## Upgrading from 1.1.0

A running gateway keeps the 1.1.0 monkeypatched function in memory — `plugins enable/disable` only loads or unloads modules and does **not** restore patched callables. After upgrading, restart the gateway:

```bash
hermes gateway restart
```

## Verify

```bash
~/.hermes/hermes-agent/venv/bin/python scripts/verify.py
```

Drives the real `ResponsesApiTransport.build_kwargs()` path, asserts the transport carries no monkeypatch, and checks that a non-Grok model is left untouched. Exits non-zero on any regression.
