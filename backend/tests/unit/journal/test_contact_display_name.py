"""The one rule for how a contact's name reads on a journal or a task."""

import pytest

from app.core.journal.services.journal_enrichment_service import (
    contact_display_name,
)


@pytest.mark.parametrize(
    ("first_name", "last_name", "expected"),
    [
        ("Jane", "Citizen", "Jane Citizen"),
        ("Jane", None, "Jane"),
        (None, "Citizen", "Citizen"),
        ("", None, "Contact 7"),
        (None, None, "Contact 7"),
    ],
)
def test_contact_display_name_skips_missing_parts(
    first_name: str | None, last_name: str | None, expected: str
) -> None:
    assert contact_display_name(first_name, last_name, 7) == expected
