"""
Unit tests for GoogleGroupNameTranslator.
"""

from group_translator import GoogleGroupNameTranslator


def test_is_reserved_identifies_reserved_groups() -> None:
    """Test that is_reserved correctly identifies reserved group IDs."""
    translator = GoogleGroupNameTranslator(
        reserved_group_ids=["myContacts", "chatBuddies"], group_mapping={}
    )

    assert translator.is_reserved("myContacts") is True
    assert translator.is_reserved("chatBuddies") is True
    # 'starred' is always considered reserved for tag purposes, it maps to favourite instead
    assert translator.is_reserved("starred") is True
    assert translator.is_reserved("family") is False
    assert translator.is_reserved(None) is False


def test_translate_uses_mapping() -> None:
    """Test that translate uses the provided mapping."""
    mapping = {"contactGroups/123": "Friends", "contactGroups/456": "Coworkers"}
    translator = GoogleGroupNameTranslator(
        reserved_group_ids=["myContacts"], group_mapping=mapping
    )

    assert translator.translate("contactGroups/123") == "Friends"
    assert translator.translate("contactGroups/456") == "Coworkers"


def test_translate_unmapped_returns_default() -> None:
    """Test that translate falls back if the resource is not in mapping."""
    mapping = {
        "contactGroups/123": "Friends",
    }
    translator = GoogleGroupNameTranslator(reserved_group_ids=[], group_mapping=mapping)

    assert (
        translator.translate("contactGroups/999", fallback_name="Default") == "Default"
    )
    assert translator.translate("contactGroups/999", fallback_name=None) is None
    assert translator.translate(None, fallback_name="Fallback") == "Fallback"
