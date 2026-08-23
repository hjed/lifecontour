"""Unit tests for the shared MCP tool-annotation vocabulary."""

from __future__ import annotations

import pytest

from app.mcp.shared.annotations import (
    ADDITIVE_WRITE,
    DESTRUCTIVE_WRITE,
    EXTERNAL_ADDITIVE_WRITE,
    IDEMPOTENT_WRITE,
    READ_ONLY,
    READ_ONLY_EXTERNAL,
    mcp_tool_annotations,
)

ALL_PRESETS = {
    "READ_ONLY": READ_ONLY,
    "READ_ONLY_EXTERNAL": READ_ONLY_EXTERNAL,
    "ADDITIVE_WRITE": ADDITIVE_WRITE,
    "IDEMPOTENT_WRITE": IDEMPOTENT_WRITE,
    "DESTRUCTIVE_WRITE": DESTRUCTIVE_WRITE,
    "EXTERNAL_ADDITIVE_WRITE": EXTERNAL_ADDITIVE_WRITE,
}


def test_builds_all_four_hints() -> None:
    """The factory sets every hint, so none is left to default to unset."""
    annotations = mcp_tool_annotations(
        read_only=False,
        destructive=True,
        idempotent=True,
        open_world=False,
    )

    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is True
    assert annotations.idempotentHint is True
    assert annotations.openWorldHint is False


def test_rejects_destructive_read_only_tool() -> None:
    """A tool that changes nothing has nothing to destroy."""
    with pytest.raises(ValueError, match="read-only tool cannot be destructive"):
        mcp_tool_annotations(
            read_only=True,
            destructive=True,
            idempotent=True,
            open_world=False,
        )


def test_rejects_non_idempotent_read_only_tool() -> None:
    """Reading twice cannot leave a different state than reading once."""
    with pytest.raises(ValueError, match="read-only tool is always idempotent"):
        mcp_tool_annotations(
            read_only=True,
            destructive=False,
            idempotent=False,
            open_world=False,
        )


@pytest.mark.parametrize("name", sorted(ALL_PRESETS))
def test_every_preset_is_complete(name: str) -> None:
    """A preset with a hint missing would silently under-declare its tools."""
    annotations = ALL_PRESETS[name]

    for hint in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
        assert getattr(annotations, hint) is not None, f"{name} leaves {hint} unset"


def test_presets_are_distinct() -> None:
    """Two presets sharing all four values would be one preset with two names."""
    shapes = {
        (
            preset.readOnlyHint,
            preset.destructiveHint,
            preset.idempotentHint,
            preset.openWorldHint,
        )
        for preset in ALL_PRESETS.values()
    }

    assert len(shapes) == len(ALL_PRESETS)


def test_external_presets_declare_an_open_world() -> None:
    """The distinguishing feature of the external presets is the one that matters."""
    for name, preset in ALL_PRESETS.items():
        assert preset.openWorldHint is name.startswith(
            ("READ_ONLY_EXTERNAL", "EXTERNAL")
        )
