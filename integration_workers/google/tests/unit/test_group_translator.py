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


def test_translate_uses_raw_id_fallback() -> None:
    """Test that translate strips contactGroups/ and tries raw ID if exact match fails."""
    # Mapping might only have the raw hash ID because of API response quirks in _build_contact_group_mapping
    mapping = {
        "123abc456": "New Friends",
    }
    translator = GoogleGroupNameTranslator(reserved_group_ids=[], group_mapping=mapping)

    # resource_name is fully qualified, but it should still match the raw ID mapping
    assert translator.translate("contactGroups/123abc456") == "New Friends"


def test_translate_uses_fallback_name_as_mapping_key() -> None:
    """Test that if resource_name is missing/unmatched, fallback_name is used as a lookup key."""
    mapping = {
        "789xyz": "Old Coworkers",
    }
    translator = GoogleGroupNameTranslator(reserved_group_ids=[], group_mapping=mapping)

    # Ensure it works when resource_name is completely missing (falling back to lookup via fallback_name)
    assert translator.translate(None, fallback_name="789xyz") == "Old Coworkers"

    # Ensure it works when resource_name is present but unmatched
    assert (
        translator.translate("contactGroups/unmatched", fallback_name="789xyz")
        == "Old Coworkers"
    )


def test_translate_prevents_hex_id_fallback() -> None:
    """Test that a raw hex ID (15+ chars) is not returned as a fallback name if unmatched."""
    translator = GoogleGroupNameTranslator(reserved_group_ids=[], group_mapping={})

    # 14 chars -> still allowed as a name
    assert (
        translator.translate(None, fallback_name="1234567890abcd") == "1234567890abcd"
    )

    # 15 chars -> blocked (returns None)
    assert translator.translate(None, fallback_name="1234567890abcde") is None

    # Typical Google ID format
    assert (
        translator.translate(
            "contactGroups/839c81a0f6f88d5", fallback_name="839c81a0f6f88d5"
        )
        is None
    )
