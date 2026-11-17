"""Force ``reasoning.effort`` for effort-capable Grok models.

Three module-level hooks, no transport patching. Each one is a knob upstream
re-reads at call time, so nothing drifts out of date with the wire builder:

1. ``agent.model_metadata._GROK_EFFORT_CAPABLE_PREFIXES`` gates whether the xAI
   branch of ``_reasoning_fields`` emits ``reasoning.effort`` at all. grok-4.7
   accepts the field but is absent from the stock allowlist, so we extend the
   prefix tuple.

2. ``agent.model_metadata.is_grok_46_family`` selects the xAI effort ladder read by
   ``codex._resolve_reasoning``: the 4.6 family gets low/medium/high/xhigh, every
   other Grok is clamped to the legacy low/medium/high. It only knows
   ``grok-4.6``, so ``GROK_EFFORT=xhigh`` was silently clamped to ``high`` on
   grok-4.7 — even though api.x.ai accepts xhigh there. Widening the predicate
   hands 4.7 the wide ladder and leaves upstream's clamp in charge.

3. ``hermes_constants.resolve_reasoning_config`` is the single chokepoint that
   turns config into ``reasoning_config`` for every surface (CLI, gateway, TUI,
   cron, ``/model``). We override it so allowlisted Grok models always resolve to
   ``GROK_EFFORT`` regardless of the global ``agent.reasoning_effort``.

1.1.0 additionally monkeypatched ``agent.transports.codex._reasoning_fields``;
that wrapper hardcoded the then-current signature and broke every xAI request
with ``TypeError: got an unexpected keyword argument 'profile_reasoning'`` once
upstream grew the parameter. ``enable``/``disable`` reload plugins inside the live
gateway process and do not restore patched callables, so the broken wrapper
outlived its fix — ``register`` therefore drops such a leftover itself (see
``_drop_stale_wrapper``), which is why upgrading no longer needs a gateway
restart.

Effort is adjustable: env ``GROK_EFFORT`` (low|medium|high|xhigh), default
``low``, read per request rather than captured at register time.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Families upstream does not know about yet. grok-4.6 is already stock-allowlisted.
_EXTRA_PREFIXES = ("grok-4.7",)
# Families whose ladder includes ``xhigh`` (upstream only knows grok-4.6).
_EXTRA_XHIGH_FAMILIES = ("grok-4.7",)
_VALID_EFFORTS = ("low", "medium", "high", "xhigh")
_DEFAULT_EFFORT = "low"


def _effort() -> str:
    raw = (os.environ.get("GROK_EFFORT") or "").strip().lower()
    if raw in _VALID_EFFORTS:
        return raw
    if raw:
        logger.warning("grok-effort: invalid GROK_EFFORT=%r, using %s", raw, _DEFAULT_EFFORT)
    return _DEFAULT_EFFORT


def _family_match(model: str, families) -> bool:
    """Prefix match on the bare model id (``xai-oauth/``-style prefixes stripped)."""
    name = (model or "").strip().lower().replace("_", "-").rsplit("/", 1)[-1]
    return bool(name) and any(
        name == family or name.startswith(family + "-") for family in families
    )


def _is_our_code(code) -> bool:
    """True when *code* was compiled from this plugin (any version)."""
    filename = getattr(code, "co_filename", "") or ""
    plugins_dir = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
    return (
        os.path.basename(os.path.dirname(filename)) == plugins_dir
        and filename.endswith("__init__.py")
    )


def _drop_stale_wrapper(host_module: Any, attr: str) -> Callable[..., Any]:
    """Return *attr* from *host_module*, unwrapping a leftover patch from an older version.

    ``hermes plugins enable`` reloads plugins inside the live gateway process instead
    of restarting it, so a wrapper installed by a previous version keeps intercepting
    requests forever — that is exactly how 1.1.0's ``_reasoning_fields`` TypeError
    outlived its fix. Such a wrapper is recognisable: our own bytecode, a closure
    holding the function it wrapped, and no current-version marker on it.
    """
    fn: Any = getattr(host_module, attr, None)
    code = getattr(fn, "__code__", None)
    if code is None or getattr(fn, "_grok_effort_wrapped", False) or not _is_our_code(code):
        return fn
    for cell in getattr(fn, "__closure__", None) or ():
        try:
            inner = cell.cell_contents
        except ValueError:
            continue
        inner_code = getattr(inner, "__code__", None)
        if (
            callable(inner)
            and getattr(inner, "__name__", "") == attr
            and inner_code is not None
            and inner_code is not code
        ):
            setattr(host_module, attr, inner)
            logger.warning("grok-effort: dropped a stale %s wrapper left by an earlier version", attr)
            return inner
    return fn


def register(ctx) -> None:
    del ctx
    try:
        import hermes_constants
        from agent import model_metadata
        from agent.transports import codex as codex_mod
    except Exception:
        logger.exception("grok-effort: could not import reasoning helpers")
        return

    # 1. allowlist: the xAI branch only emits `reasoning` for allowlisted models.
    prefixes = tuple(dict.fromkeys((*model_metadata._GROK_EFFORT_CAPABLE_PREFIXES, *_EXTRA_PREFIXES)))
    model_metadata._GROK_EFFORT_CAPABLE_PREFIXES = prefixes

    # 2. ladder: let the 4.7 family reach xhigh through upstream's own clamp.
    stock_family = _drop_stale_wrapper(model_metadata, "is_grok_46_family")
    if not getattr(stock_family, "_grok_effort_widened", False):

        def is_grok_46_family(model: str = "") -> bool:
            if stock_family(model):
                return True
            return _family_match(model, _EXTRA_XHIGH_FAMILIES)

        is_grok_46_family._grok_effort_widened = True  # type: ignore[attr-defined]
        model_metadata.is_grok_46_family = is_grok_46_family

    # 3. clear wrappers a previous version left behind in this (long-lived) process.
    _drop_stale_wrapper(codex_mod, "_reasoning_fields")
    stock_resolve = _drop_stale_wrapper(hermes_constants, "resolve_reasoning_config")

    # 4. force the effort on the config chokepoint every surface goes through.
    if not getattr(stock_resolve, "_grok_effort_wrapped", False):

        def resolve_reasoning_config(cfg, model=""):
            # ``grok_supports_reasoning_effort`` reads the prefix tuple widened in
            # step 1, so grok-4.7 is covered without a separate branch.
            if model and model_metadata.grok_supports_reasoning_effort(model):
                return {"enabled": True, "effort": _effort()}
            return stock_resolve(cfg, model)

        resolve_reasoning_config._grok_effort_wrapped = True  # type: ignore[attr-defined]
        hermes_constants.resolve_reasoning_config = resolve_reasoning_config

    logger.info(
        "grok-effort: effort-capable Grok models forced to %s; allowlist=%s",
        _effort(),
        ",".join(prefixes),
    )
