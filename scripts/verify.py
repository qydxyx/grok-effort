#!/usr/bin/env python3
"""Verify grok-effort against the real Hermes transport path.

Run with an interpreter that has the Hermes agent package on its path:

    python3 scripts/verify.py            # Hermes venv python, or any python with
                                         # ~/.hermes/hermes-agent importable

Loads this plugin exactly as the Hermes loader does, then drives the actual
``ResponsesApiTransport.build_kwargs()`` call site — not a hand-built kwargs
dict — so a signature mismatch between the plugin and upstream surfaces the
same way it did in production. Set HERMES_HOME to point at a non-default
Hermes install.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types

HERMES_HOME = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.join(HERMES_HOME, "hermes-agent"))
os.environ.setdefault("HERMES_HOME", HERMES_HOME)
# Unset on purpose: section 3 proves the shipped default (low) is what runs.
os.environ.pop("GROK_EFFORT", None)

try:
    from agent import model_metadata
    from agent.model_metadata import grok_supports_reasoning_effort
    from agent.transports import codex as codex_mod
    from agent.transports.codex import ResponsesApiTransport
    import hermes_constants
except ImportError as exc:
    sys.exit(f"cannot import the Hermes agent package: {exc}\n"
             f"run this with the python that can import {HERMES_HOME}/hermes-agent")

failures: list[str] = []


def check(label: str, actual, expected) -> None:
    ok = actual == expected
    print(f"  [{'ok  ' if ok else 'FAIL'}] {label:50s} {actual!r}")
    if not ok:
        failures.append(f"{label}: got {actual!r}, expected {expected!r}")


def wire(model: str, cfg) -> object:
    """Drive the real transport call site the xAI branch goes through."""
    try:
        kwargs = ResponsesApiTransport().build_kwargs(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            reasoning_config=cfg,
            session_id="verify",
            cache_scope_id="verify",
            base_url="https://api.x.ai/v1",
            max_tokens=64,
            timeout=60,
            request_overrides=None,
            provider="xai-oauth",
            is_codex_backend=False,
            is_xai_responses=True,
            profile_reasoning=None,
            replay_encrypted_reasoning=True,
            context_management=None,
            text_verbosity=None,
        )
    except TypeError as exc:
        failures.append(f"{model} build_kwargs raised TypeError: {exc}")
        return f"TypeError: {exc}"
    return kwargs.get("reasoning")


print("=" * 72)
print("1. Upstream state BEFORE the plugin loads")
check("supports grok-4.6", grok_supports_reasoning_effort("grok-4.6"), True)
check("supports grok-4.7 (stock: absent)", grok_supports_reasoning_effort("grok-4.7"), False)
check("xhigh ladder for grok-4.7 (stock: absent)", model_metadata.is_grok_46_family("grok-4.7"), False)

print()
print("=" * 72)
print("2. Load the plugin the way the Hermes loader does (GROK_EFFORT unset)")
ns = types.ModuleType("hermes_plugins")
ns.__path__ = []
sys.modules["hermes_plugins"] = ns
spec = importlib.util.spec_from_file_location(
    "hermes_plugins.grok_effort",
    os.path.join(PLUGIN_DIR, "__init__.py"),
    submodule_search_locations=[PLUGIN_DIR],
)
if spec is None or spec.loader is None:
    sys.exit(f"cannot build a module spec for {PLUGIN_DIR}/__init__.py")
module = importlib.util.module_from_spec(spec)
sys.modules["hermes_plugins.grok_effort"] = module
spec.loader.exec_module(module)
module.register(None)

# The whole point of 1.2.0: the transport is untouched. A 'register.<locals>'
# qualname means a monkeypatch is installed again and will drift out of date.
qualname = codex_mod._reasoning_fields.__qualname__
print(f"  [{'ok  ' if 'register.<locals>' not in qualname else 'FAIL'}] "
      f"_reasoning_fields is unpatched                         {qualname}")
if "register.<locals>" in qualname:
    failures.append("plugin monkeypatched _reasoning_fields (must not)")

check("supports grok-4.7 (widened)", grok_supports_reasoning_effort("grok-4.7"), True)
check("supports grok-2 (unchanged)", grok_supports_reasoning_effort("grok-2"), False)
check("xhigh ladder for grok-4.7 (widened)", model_metadata.is_grok_46_family("grok-4.7"), True)
check("xhigh ladder for grok-4.5 (unchanged)", model_metadata.is_grok_46_family("grok-4.5"), False)

print()
print("=" * 72)
print("3. Default effort with GROK_EFFORT unset")
cfg_low = {"agent": {"reasoning_effort": "low"}}
cfg_high = {"agent": {"reasoning_effort": "high"}}
check("default effort = low (ignores cfg high)",
      hermes_constants.resolve_reasoning_config(cfg_high, "grok-4.6"),
      {"enabled": True, "effort": "low"})
check("resolve grok-4.7", hermes_constants.resolve_reasoning_config(cfg_high, "grok-4.7"),
      {"enabled": True, "effort": "low"})
check("resolve gpt-5 (left alone)",
      hermes_constants.resolve_reasoning_config(cfg_low, "gpt-5"),
      {"enabled": True, "effort": "low"})

print()
print("=" * 72)
print("4. Effort reaches the wire through build_kwargs()")
check("grok-4.6 default", wire("grok-4.6", hermes_constants.resolve_reasoning_config(cfg_high, "grok-4.6")),
      {"effort": "low"})
os.environ["GROK_EFFORT"] = "xhigh"
check("grok-4.7 keeps xhigh",
      wire("grok-4.7", hermes_constants.resolve_reasoning_config(cfg_low, "grok-4.7")),
      {"effort": "xhigh"})
check("grok-4.6 keeps xhigh",
      wire("grok-4.6", hermes_constants.resolve_reasoning_config(cfg_low, "grok-4.6")),
      {"effort": "xhigh"})
check("grok-4.5 clamped xhigh->high",
      wire("grok-4.5", hermes_constants.resolve_reasoning_config(cfg_low, "grok-4.5")),
      {"effort": "high"})
check("grok-2 receives no reasoning field",
      wire("grok-2", hermes_constants.resolve_reasoning_config(cfg_low, "grok-2")), None)

print()
print("=" * 72)
print("5. In-place upgrade: a wrapper left behind by 1.1.0 is dropped")
original = codex_mod._reasoning_fields


def make_stale_wrapper(inner):
    """Reproduce the 1.1.0 wrapper: nested def in this file, old hardcoded signature."""
    src = (
        "def outer(wrapped):\n"
        "    def _reasoning_fields(model, params, *, effort, enabled, replay_encrypted_reasoning,\n"
        "                          is_xai_responses, is_github_responses):\n"
        "        return wrapped(model, params, effort=effort, enabled=enabled,\n"
        "                       replay_encrypted_reasoning=replay_encrypted_reasoning,\n"
        "                       is_xai_responses=is_xai_responses,\n"
        "                       is_github_responses=is_github_responses)\n"
        "    return _reasoning_fields\n"
    )
    namespace: dict = {}
    exec(compile(src, os.path.join(PLUGIN_DIR, "__init__.py"), "exec"), namespace)
    return namespace["outer"](inner)


codex_mod._reasoning_fields = make_stale_wrapper(original)
check("stale wrapper installed (simulated)", codex_mod._reasoning_fields is not original, True)
module.register(None)
check("stale wrapper dropped by register()", codex_mod._reasoning_fields is original, True)
check("groks still resolve after the heal",
      hermes_constants.resolve_reasoning_config(cfg_low, "grok-4.7"),
      {"enabled": True, "effort": "xhigh"})

print()
print("=" * 72)
if failures:
    print(f"FAILED ({len(failures)}):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("PASS: default low, 4.7 reaches xhigh, transport untouched, effort on the wire.")
