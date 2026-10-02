# grok-effort-low

Hermes plugin that forces `reasoning.effort=low` for Grok models that accept the parameter, regardless of the global `agent.reasoning_effort`.

`grok-4.7` accepts `low` / `medium` / `high` / `xhigh` but is missing from Hermes' effort allowlist, so a config override is resolved and then dropped. This plugin adds that prefix and overwrites the outgoing effort. Models that reject the field are left unchanged, so they do not 400.

## Install

Copy this directory to `~/.hermes/plugins/grok-effort-low/` and enable it:

```bash
hermes plugins enable grok-effort-low
```

Confirm the gateway log contains `grok-effort-low: effort-capable Grok models forced to low`.
