"""Removing a contact's last email, phone or address must clear it in Google.

Augment review of #1548: ``update_contact`` derives ``updatePersonFields`` from
the payload's keys, and the transform dropped ``emailAddresses``,
``phoneNumbers`` and ``addresses`` whenever they were empty. Deleting a
contact's *last* email therefore produced a payload that never named the field,
so Google kept the stale value — and the next inbound pull, seeing a changed
etag, re-imported the deleted email. #1548 routes ``ContactMethodDeleted`` and
``ContactAddressDeleted``, which made this path live.

Presence of the source key (loaded by ``_load_full_contact`` on both push paths)
is what decides inclusion — the same rule the transform already applies to
important dates.
"""

from typing import Any

import pytest


def _contact(**fields: Any) -> dict[str, Any]:
    """A minimal contact dict as the push paths build it."""
    return {"first_name": "Ada", "last_name": "Lovelace", **fields}


class TestEmptyMethodListsClearGoogle:
    """An empty ``methods`` list is sent as empty email and phone fields."""

    def test_no_methods_left_clears_emails_and_phones(self) -> None:
        """Both fields are present and empty, so the mask clears them."""
        from worker import _transform_contact_to_google_person

        result = _transform_contact_to_google_person(_contact(methods=[]))

        assert result["emailAddresses"] == []
        assert result["phoneNumbers"] == []

    def test_phone_only_contact_clears_its_emails(self) -> None:
        """Removing the last email while a phone remains still clears emails."""
        from worker import _transform_contact_to_google_person

        result = _transform_contact_to_google_person(
            _contact(
                methods=[
                    {
                        "method_type": "phone",
                        "value": "+61 400 000 000",
                        "label": None,
                        "is_primary": True,
                    }
                ]
            )
        )

        assert result["emailAddresses"] == []
        assert len(result["phoneNumbers"]) == 1

    def test_methods_key_absent_leaves_the_fields_alone(self) -> None:
        """A caller that did not load methods must not wipe them in Google."""
        from worker import _transform_contact_to_google_person

        result = _transform_contact_to_google_person(_contact())

        assert "emailAddresses" not in result
        assert "phoneNumbers" not in result


class TestEmptyAddressListClearsGoogle:
    """An empty ``addresses`` list is sent as an empty addresses field."""

    def test_no_addresses_left_clears_addresses(self) -> None:
        from worker import _transform_contact_to_google_person

        result = _transform_contact_to_google_person(_contact(addresses=[]))

        assert result["addresses"] == []

    def test_addresses_key_absent_leaves_the_field_alone(self) -> None:
        from worker import _transform_contact_to_google_person

        result = _transform_contact_to_google_person(_contact())

        assert "addresses" not in result


class TestNicknameClearsGoogle:
    """A nickname cleared locally is sent empty, so Google drops it too.

    The import owns the nickname, so leaving Google's copy would bring the
    cleared value back on the next pull.
    """

    def test_set_nickname_is_sent(self) -> None:
        from worker import _transform_contact_to_google_person

        result = _transform_contact_to_google_person(_contact(nick_name="Ada"))

        assert result["nicknames"] == [{"value": "Ada"}]

    def test_cleared_nickname_is_sent_empty(self) -> None:
        from worker import _transform_contact_to_google_person

        result = _transform_contact_to_google_person(_contact(nick_name=None))

        assert result["nicknames"] == []

    def test_nickname_key_absent_leaves_the_field_alone(self) -> None:
        from worker import _transform_contact_to_google_person

        result = _transform_contact_to_google_person(_contact())

        assert "nicknames" not in result


class TestCompanyClearsGoogle:
    """A company and job title cleared locally are sent empty (#1822, #1938).

    The push merge decides from the synced base whether Google's company was
    cleared locally or added in Google since, so it must see the field.
    """

    def test_set_company_is_sent(self) -> None:
        from worker import _transform_contact_to_google_person

        result = _transform_contact_to_google_person(
            _contact(company="Engines", job_title=None)
        )

        assert result["organizations"] == [{"current": True, "name": "Engines"}]

    @pytest.mark.parametrize(
        ("company", "job_title"), [(None, None), ("  ", ""), ("", None)]
    )
    def test_cleared_company_is_sent_empty(
        self, company: str | None, job_title: str | None
    ) -> None:
        from worker import _transform_contact_to_google_person

        result = _transform_contact_to_google_person(
            _contact(company=company, job_title=job_title)
        )

        assert result["organizations"] == []

    def test_company_keys_absent_leave_the_field_alone(self) -> None:
        from worker import _transform_contact_to_google_person

        result = _transform_contact_to_google_person(_contact())

        assert "organizations" not in result


class TestNotesClearGoogle:
    """Every note deleted locally is sent as no biographies (#1822, #1938)."""

    def test_no_notes_left_clears_biographies(self) -> None:
        from worker import _transform_contact_to_google_person

        result = _transform_contact_to_google_person(_contact(notes=[]))

        assert result["biographies"] == []

    def test_notes_key_absent_leaves_the_field_alone(self) -> None:
        from worker import _transform_contact_to_google_person

        result = _transform_contact_to_google_person(_contact())

        assert "biographies" not in result
