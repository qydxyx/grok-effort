# grok-effort

Hermes plugin that sets `reasoning.effort` for Grok models that accept the parameter, regardless of the global `agent.reasoning_effort`.

Default is **medium**. Override with env `GROK_EFFORT` (`low` | `medium` | `high` | `xhigh`).

`grok-4.7` accepts those values but is missing from Hermes' stock effort allowlist, so a config override is resolved and then dropped. This plugin adds that prefix and overwrites the outgoing effort. Models that reject the field are left unchanged, so they do not 400.

## Install

Copy this directory to `~/.hermes/plugins/grok-effort/` and enable it:

```bash
hermes plugins enable grok-effort
```

Confirm the gateway log contains `grok-effort: effort-capable Grok models forced to medium` (or the `GROK_EFFORT` you set).
