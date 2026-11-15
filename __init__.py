"""Force ``reasoning.effort`` for effort-capable Grok models.

Two things keep a Grok effort setting from reaching the xAI wire, and this plugin
fixes exactly those two — no transport patching:

1. ``agent.model_metadata._GROK_EFFORT_CAPABLE_PREFIXES`` gates whether the xAI
   branch of ``_reasoning_fields`` emits ``reasoning.effort`` at all. grok-4.7
   accepts the field but is absent from the stock allowlist, so we extend the
   prefix tuple.

2. ``hermes_constants.resolve_reasoning_config`` is the single chokepoint that
   turns config into ``reasoning_config`` for every surface (CLI, gateway, TUI,
   cron, ``/model``). We override it so allowlisted Grok models always resolve to
   ``GROK_EFFORT`` (default ``medium``) regardless of the global
   ``agent.reasoning_effort``.

Both patches mutate module state that upstream re-reads at call time, so nothing
else needs wrapping. An earlier revision also monkeypatched
``agent.transports.codex._reasoning_fields``; that wrapper hardcoded the old
signature and broke every xAI request with ``TypeError: got an unexpected keyword
argument 'profile_reasoning'`` once upstream grew that parameter. It was pure
duplication — the upstream xAI branch already re-checks the allowlist and reads
``effort`` from the ``reasoning_config`` we control — so it is gone.

Effort is adjustable: env ``GROK_EFFORT`` (low|medium|high|xhigh), default medium.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_EXTRA_PREFIXES = ("grok-4.7",)
_VALID_EFFORTS = ("low", "medium", "high", "xhigh")
_DEFAULT_EFFORT = "medium"


def _effort() -> str:
    raw = (os.environ.get("GROK_EFFORT") or "").strip().lower()
    if raw in _VALID_EFFORTS:
        return raw
    if raw:
        logger.warning("grok-effort: invalid GROK_EFFORT=%r, using %s", raw, _DEFAULT_EFFORT)
    return _DEFAULT_EFFORT


def register(ctx) -> None:
    del ctx
    try:
        import hermes_constants
        from agent import model_metadata
        from hermes_constants import resolve_reasoning_config as _stock_resolve
    except Exception:
        logger.exception("grok-effort: could not import reasoning helpers")
        return

    prefixes = tuple(dict.fromkeys((*model_metadata._GROK_EFFORT_CAPABLE_PREFIXES, *_EXTRA_PREFIXES)))
    model_metadata._GROK_EFFORT_CAPABLE_PREFIXES = prefixes
    effort = _effort()

    def resolve_reasoning_config(cfg, model=""):
        # ``grok_supports_reasoning_effort`` reads the prefix tuple we just widened,
        # so grok-4.7 is covered here without a separate branch.
        if model and model_metadata.grok_supports_reasoning_effort(model):
            return {"enabled": True, "effort": effort}
        return _stock_resolve(cfg, model)

    hermes_constants.resolve_reasoning_config = resolve_reasoning_config

    logger.info(
        "grok-effort: effort-capable Grok models forced to %s; allowlist=%s",
        effort,
        ",".join(prefixes),
    )
