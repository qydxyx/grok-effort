#!/usr/bin/env python3
"""Verify grok-effort against the real Hermes transport path.

Run with the Hermes venv (that interpreter has ruamel.yaml and the agent deps):

    ~/.hermes/hermes-agent/venv/bin/python scripts/verify.py

Loads this plugin exactly as the Hermes loader does, then drives the actual
``ResponsesApiTransport.build_kwargs()`` call site — not a hand-built kwargs
dict — so a signature mismatch between the plugin and upstream surfaces the
same way it did in production.

Set HERMES_HOME to point at a non-default Hermes install.
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
# Non-default on purpose: proves the env knob still overrides agent.reasoning_effort.
os.environ["GROK_EFFORT"] = "high"

try:
    from agent.model_metadata import grok_supports_reasoning_effort
    from agent.transports import codex as codex_mod
    from agent.transports.codex import ResponsesApiTransport
    import hermes_constants
except ImportError as exc:
    sys.exit(f"cannot import the Hermes agent package: {exc}\n"
             f"run this with {HERMES_HOME}/hermes-agent/venv/bin/python")

failures: list[str] = []


def check(label: str, actual, expected, note: str = "") -> None:
    ok = actual == expected
    mark = "ok  " if ok else "FAIL"
    print(f"  [{mark}] {label:42s} {actual!r}" + (f"  {note}" if note else ""))
    if not ok:
        failures.append(f"{label}: got {actual!r}, expected {expected!r}")


print("=" * 72)
print("1. Upstream state BEFORE the plugin loads")
check("supports grok-4.6", grok_supports_reasoning_effort("grok-4.6"), True)
check("supports grok-4.7 (stock: absent)", grok_supports_reasoning_effort("grok-4.7"), False)

print()
print("=" * 72)
print("2. Load the plugin the way the Hermes loader does")
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
      f"_reasoning_fields is unpatched                 {qualname}")
if "register.<locals>" in qualname:
    failures.append("plugin monkeypatched _reasoning_fields (must not)")

check("supports grok-4.7 (widened)", grok_supports_reasoning_effort("grok-4.7"), True)
check("supports grok-2 (unchanged)", grok_supports_reasoning_effort("grok-2"), False)

cfg_low = {"agent": {"reasoning_effort": "low"}}
check("resolve grok-4.6 (env wins over cfg low)",
      hermes_constants.resolve_reasoning_config(cfg_low, "grok-4.6"),
      {"enabled": True, "effort": "high"})
check("resolve grok-4.7 (env wins over cfg low)",
      hermes_constants.resolve_reasoning_config(cfg_low, "grok-4.7"),
      {"enabled": True, "effort": "high"})
check("resolve gpt-5 (left alone)",
      hermes_constants.resolve_reasoning_config(cfg_low, "gpt-5"),
      {"enabled": True, "effort": "low"})

print()
print("=" * 72)
print("3. Drive the real ResponsesApiTransport.build_kwargs() call site")
transport = ResponsesApiTransport()
for model, want in (("grok-4.6", {"effort": "high"}),
                    ("grok-4.7", {"effort": "high"}),
                    ("grok-2", None)):
    cfg = hermes_constants.resolve_reasoning_config(cfg_low, model)
    try:
        kwargs = transport.build_kwargs(
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
        print(f"  [FAIL] {model:10s} build_kwargs raised TypeError: {exc}")
        failures.append(f"{model}: {exc}")
        continue
    check(f"{model} build_kwargs reasoning", kwargs.get("reasoning"), want)

print()
print("=" * 72)
if failures:
    print(f"FAILED ({len(failures)}):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("PASS: plugin patches apply, transport untouched, effort reaches the wire.")
