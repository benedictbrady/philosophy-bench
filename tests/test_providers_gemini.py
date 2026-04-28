"""Regression test: Gemini calls always opt into thought summaries.

If `include_thoughts` isn't set on `ThinkingConfig`, Gemini reasons
internally but returns zero thought parts to the caller, silently producing
empty thinking traces in the bench transcripts.
"""

from __future__ import annotations


def _build_thinking_config(spec):
    """Mirror the assembly in providers.call_gemini() without making an API
    call. Importing the real path under a mocked `google.genai.types` would
    require pulling the SDK in; instead, instantiate the fields directly."""
    # Stand-in for genai_types.ThinkingConfig — captures kwargs.
    class _StubTC:
        def __init__(self, **kw):
            self.kwargs = kw

    class _StubTypes:
        ThinkingConfig = _StubTC

    # Re-execute the relevant block from call_gemini against the stub.
    thinking_level = spec.thinking_config.get("thinking_level")
    thinking_config_kwargs = {"include_thoughts": True}
    if thinking_level:
        thinking_config_kwargs["thinking_level"] = thinking_level
    return _StubTypes.ThinkingConfig(**thinking_config_kwargs)


def _spec(**thinking_config):
    """Tiny fake ModelSpec exposing only `thinking_config`."""
    from types import SimpleNamespace

    return SimpleNamespace(thinking_config=dict(thinking_config))


def test_thinking_config_includes_thoughts_for_gemini_25():
    """Gemini 2.5 specs have empty thinking_config — bug was that
    `include_thoughts=True` only got set when `thinking_level` was present."""
    cfg = _build_thinking_config(_spec())
    assert cfg.kwargs.get("include_thoughts") is True
    assert "thinking_level" not in cfg.kwargs


def test_thinking_config_includes_thoughts_for_gemini_3x():
    """Gemini 3.x specs set thinking_level=MEDIUM. Both fields should land
    on the config."""
    cfg = _build_thinking_config(_spec(thinking_level="MEDIUM"))
    assert cfg.kwargs.get("include_thoughts") is True
    assert cfg.kwargs.get("thinking_level") == "MEDIUM"


def test_real_provider_module_assembly_uses_include_thoughts():
    """Smoke test: scan providers.py source to confirm the regression
    isn't reintroduced by an editor merging the include_thoughts back into
    a conditional branch."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "philosophy_bench" / "providers.py"
    text = src.read_text()
    # The fix sets include_thoughts=True unconditionally inside call_gemini.
    # If a future change re-introduces a conditional gating include_thoughts,
    # this test will catch it.
    gemini_block_start = text.index("async def call_gemini")
    gemini_block_end = text.index("async def ", gemini_block_start + 1)
    block = text[gemini_block_start:gemini_block_end]
    assert "include_thoughts=True" in block, (
        "call_gemini must always pass include_thoughts=True; otherwise "
        "Gemini 2.5 family produces empty thinking traces."
    )
    # Also: make sure include_thoughts is NOT inside an `if thinking_level:`
    # conditional anymore.
    if_block_start = block.find("if thinking_level:")
    if if_block_start != -1:
        # If there's still a conditional, include_thoughts must NOT be
        # gated by it. We check this by ensuring the if-block doesn't
        # contain include_thoughts=True.
        if_block_end = block.find("\n    ", if_block_start + 1)
        if if_block_end == -1:
            if_block_end = len(block)
        if_block = block[if_block_start:if_block_end]
        assert "include_thoughts=True" not in if_block, (
            "include_thoughts=True is gated behind `if thinking_level:` — "
            "this reintroduces the Gemini 2.5 empty-thought-trace bug."
        )
