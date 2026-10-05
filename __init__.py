"""Set reasoning.effort for effort-capable Grok models.

Config overrides are exact model names, and the xAI wire drops ``reasoning.effort``
unless ``grok_supports_reasoning_effort`` is true. grok-4.7 accepts low/medium/high/xhigh
but is missing from the stock allowlist, so an override never leaves the process.
This plugin adds grok-4.7 and overwrites the outgoing effort for every allowlisted
Grok model. Models that 400 on the parameter are left alone.

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
        from agent import model_metadata
        from agent.transports import codex as codex_mod
        from hermes_constants import resolve_reasoning_config as _resolve_reasoning_config
        import hermes_constants
    except Exception:
        logger.exception("grok-effort: could not import reasoning helpers")
        return

    prefixes = tuple(dict.fromkeys((*model_metadata._GROK_EFFORT_CAPABLE_PREFIXES, *_EXTRA_PREFIXES)))
    model_metadata._GROK_EFFORT_CAPABLE_PREFIXES = prefixes
    effort = _effort()

    def resolve_reasoning_config(cfg, model=""):
        if model and model_metadata.grok_supports_reasoning_effort(model):
            return {"enabled": True, "effort": effort}
        return _resolve_reasoning_config(cfg, model)

    hermes_constants.resolve_reasoning_config = resolve_reasoning_config

    original_fields = codex_mod._reasoning_fields

    def _reasoning_fields(
        model, params, *, effort, enabled, replay_encrypted_reasoning,
        is_xai_responses, is_github_responses,
    ):
        if is_xai_responses and model_metadata.grok_supports_reasoning_effort(model):
            effort = _effort()
            enabled = True
        return original_fields(
            model, params, effort=effort, enabled=enabled,
            replay_encrypted_reasoning=replay_encrypted_reasoning,
            is_xai_responses=is_xai_responses, is_github_responses=is_github_responses,
        )

    codex_mod._reasoning_fields = _reasoning_fields
    logger.info(
        "grok-effort: effort-capable Grok models forced to %s; allowlist=%s",
        effort,
        ",".join(prefixes),
    )
