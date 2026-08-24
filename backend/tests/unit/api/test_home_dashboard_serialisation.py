"""Unit tests for the home dashboard's JSON:API document.

Asserted off the pure renderer rather than through a request, the way
``to_upcoming_tasks_response`` is, so the document's shape is pinned without a
database or a client.

The shape follows the specification deliberately in three places, and each is
tested here because later phases inherit it:

- **A degraded section is part of ``data``, not ``errors``.** The specification
  forbids ``data`` and ``errors`` in the same document, so "three sections and a
  failure in the fourth" has no representation as an error document — it is a
  successful response whose fourth section says it is unavailable.
- **The anchor travels in ``meta``**, which is where information about how the
  answer was computed belongs, matching the upcoming-tasks listing's window.
- **The resource carries a ``self`` link**, as the specification recommends.
"""

import datetime

import pytest

from app.api.home_dashboard.schemas import (
    HOME_DASHBOARD_RESOURCE_TYPE,
    DashboardSectionSchema,
    SummarySectionSchema,
    to_home_dashboard_response,
)
from app.core.dashboard.models.sections import (
    AgendaSectionData,
    DashboardSection,
    DashboardSummaryState,
    HomeDashboard,
    SummarySectionData,
    TasksSectionData,
    UpcomingDatesSectionData,
)

pytestmark = pytest.mark.unit

USER_ID = "test-user-123"
ANCHOR = datetime.date(2026, 7, 31)
BASE_URL = "http://testserver"

GENERATED_SUMMARY = SummarySectionData(
    state=DashboardSummaryState.GENERATED,
    summary_text="A long day of climbing and two good conversations.",
    journal_count=4,
    event_count=2,
    contact_count=3,
    mood_average=7.5,
)

# The sections Phases 5-6, 11 and 13 have yet to fill. Named rather than
# repeated so a phase filling one has a single place to stop excluding it.
STILL_EMPTY = ("agenda", "tasks", "upcoming_dates")


def dashboard(**overrides: object) -> HomeDashboard:
    """A dashboard with every section ready, as the service builds one."""
    sections: dict[str, object] = {
        "summary": DashboardSection.ready(GENERATED_SUMMARY),
        "agenda": DashboardSection.ready(AgendaSectionData()),
        "tasks": DashboardSection.ready(TasksSectionData()),
        "upcoming_dates": DashboardSection.ready(UpcomingDatesSectionData()),
    }
    sections.update(overrides)
    return HomeDashboard(
        user_id=USER_ID,
        anchor_date=ANCHOR,
        timezone="Australia/Sydney",
        **sections,  # type: ignore[arg-type]
    )


class TestTheSingletonResource:
    def test_is_keyed_by_the_user_it_belongs_to(self) -> None:
        """No dashboard row exists, so the user's id is the resource's id."""
        response = to_home_dashboard_response(dashboard())

        assert response.data.type == HOME_DASHBOARD_RESOURCE_TYPE == "home-dashboards"
        assert response.data.id == USER_ID

    def test_carries_an_absolute_self_link(self) -> None:
        response = to_home_dashboard_response(dashboard(), BASE_URL)

        assert response.data.links is not None
        assert response.data.links.self == f"{BASE_URL}/api/home-dashboard"


class TestTheAnchorInMeta:
    def test_names_the_day_and_zone_the_sections_were_read_for(self) -> None:
        response = to_home_dashboard_response(dashboard())

        assert response.meta.anchor.date == ANCHOR
        assert response.meta.anchor.timezone == "Australia/Sydney"

    def test_is_present_however_little_the_sections_hold(self) -> None:
        """A client renders "Today, 31 July" whatever else it does or does not."""
        document = to_home_dashboard_response(dashboard()).model_dump(mode="json")

        assert document["meta"]["anchor"] == {
            "date": "2026-07-31",
            "timezone": "Australia/Sydney",
        }

    def test_does_not_sit_in_attributes(self) -> None:
        """How the answer was computed is meta, not a field of the resource."""
        document = to_home_dashboard_response(dashboard()).model_dump(mode="json")

        assert "anchor" not in document["data"]["attributes"]
        assert "timezone" not in document["data"]["attributes"]


class TestTheFourSections:
    def test_all_four_are_declared_in_attributes(self) -> None:
        document = to_home_dashboard_response(dashboard()).model_dump(mode="json")

        assert set(document["data"]["attributes"]) == {
            "summary",
            "agenda",
            "tasks",
            "upcoming_dates",
        }

    def test_a_ready_section_carries_a_payload_object(self) -> None:
        """Present whether or not the phase that fills it has landed yet.

        The three unfilled sections serialise as ``{}`` — "ready and holding
        nothing", which is a real answer rather than an absence — while the
        summary carries the fields this phase gave it.
        """
        document = to_home_dashboard_response(dashboard()).model_dump(mode="json")

        for name, section in document["data"]["attributes"].items():
            assert section["status"] == "ready", name
            assert section["data"] is not None, name
        for name in STILL_EMPTY:
            assert document["data"]["attributes"][name]["data"] == {}, name

    def test_an_unavailable_section_carries_null_data(self) -> None:
        document = to_home_dashboard_response(
            dashboard(agenda=DashboardSection.unavailable())
        ).model_dump(mode="json")

        assert document["data"]["attributes"]["agenda"] == {
            "status": "unavailable",
            "data": None,
        }

    def test_the_other_sections_are_unaffected(self) -> None:
        document = to_home_dashboard_response(
            dashboard(agenda=DashboardSection.unavailable())
        ).model_dump(mode="json")

        for name in ("summary", "tasks", "upcoming_dates"):
            assert document["data"]["attributes"][name]["status"] == "ready", name


class TestADegradedDocumentIsStillASuccessfulOne:
    def test_a_failed_section_never_becomes_a_top_level_errors_member(self) -> None:
        """``data`` and ``errors`` may not coexist, so the failure lives in data."""
        document = to_home_dashboard_response(
            dashboard(
                summary=DashboardSection.unavailable(),
                tasks=DashboardSection.unavailable(),
            )
        ).model_dump(mode="json")

        assert set(document) == {"data", "meta"}
        assert "errors" not in document
        assert document["data"]["attributes"]["summary"]["status"] == "unavailable"

    def test_every_section_can_be_unavailable_at_once(self) -> None:
        """Even then the document is a dashboard, with its anchor, not an error."""
        document = to_home_dashboard_response(
            dashboard(
                summary=DashboardSection.unavailable(),
                agenda=DashboardSection.unavailable(),
                tasks=DashboardSection.unavailable(),
                upcoming_dates=DashboardSection.unavailable(),
            )
        ).model_dump(mode="json")

        statuses = {
            section["status"] for section in document["data"]["attributes"].values()
        }
        assert statuses == {"unavailable"}
        assert document["meta"]["anchor"]["date"] == "2026-07-31"


class TestTheSummarySection:
    """The one section with a payload of its own, as of this phase.

    Two of the wireframe's three declared states live in ``data.state``; the
    third is the envelope's ``unavailable``, which is why there is no
    ``"unavailable"`` member of the state vocabulary to serialise.
    """

    def test_serialises_every_field_the_card_renders(self) -> None:
        document = to_home_dashboard_response(dashboard()).model_dump(mode="json")

        assert document["data"]["attributes"]["summary"] == {
            "status": "ready",
            "data": {
                "state": "generated",
                "summary_text": "A long day of climbing and two good conversations.",
                "journal_count": 4,
                "event_count": 2,
                "contact_count": 3,
                "mood_average": 7.5,
            },
        }

    def test_a_generating_summary_carries_no_prose(self) -> None:
        """W8 replaces the body with one muted line, so there is nothing to send."""
        document = to_home_dashboard_response(
            dashboard(
                summary=DashboardSection.ready(
                    SummarySectionData(
                        state=DashboardSummaryState.GENERATING,
                        journal_count=1,
                    )
                )
            )
        ).model_dump(mode="json")

        payload = document["data"]["attributes"]["summary"]["data"]
        assert payload["state"] == "generating"
        assert payload["summary_text"] is None

    def test_absent_values_serialise_as_null_rather_than_vanishing(self) -> None:
        """A key that disappears reads to a client as a schema change.

        ``mood_average`` is null on any day nobody rated their mood, which is
        most days, so the field has to be reliably present for W10 to decide
        whether to draw its fourth stat.
        """
        document = to_home_dashboard_response(
            dashboard(
                summary=DashboardSection.ready(
                    SummarySectionData(state=DashboardSummaryState.GENERATED)
                )
            )
        ).model_dump(mode="json")

        payload = document["data"]["attributes"]["summary"]["data"]
        assert payload["summary_text"] is None
        assert payload["mood_average"] is None
        assert payload["journal_count"] == 0

    def test_an_unavailable_summary_takes_nothing_else_down(self) -> None:
        """The specification's ruling, now that the section has real content."""
        document = to_home_dashboard_response(
            dashboard(summary=DashboardSection.unavailable())
        ).model_dump(mode="json")

        assert set(document) == {"data", "meta"}
        assert document["data"]["attributes"]["summary"] == {
            "status": "unavailable",
            "data": None,
        }
        for name in STILL_EMPTY:
            assert document["data"]["attributes"][name]["status"] == "ready", name

    def test_the_page_can_still_name_its_day_without_a_summary(self) -> None:
        """W6's Regenerate control persists in the unavailable state.

        It posts to the daily-summary endpoint for a date, and the only date
        left in the document is the anchor — so that is where a client takes it
        from, and it must survive the section it belongs to going missing.
        """
        document = to_home_dashboard_response(
            dashboard(summary=DashboardSection.unavailable())
        ).model_dump(mode="json")

        assert document["meta"]["anchor"]["date"] == "2026-07-31"

    def test_exposes_no_mutation_affordance(self) -> None:
        """Read-only: regeneration stays on the existing daily-summary endpoint."""
        payload = to_home_dashboard_response(dashboard()).model_dump(mode="json")[
            "data"
        ]["attributes"]["summary"]["data"]

        assert set(payload) == {
            "state",
            "summary_text",
            "journal_count",
            "event_count",
            "contact_count",
            "mood_average",
        }


class TestTheStatusIsDocumentedAsItBehaves:
    """The generated schema is the contract a client author actually reads.

    Phase 2 widened *unavailable* from "could not be read" to "has nothing for
    you", and the domain docstrings were updated with it — but the OpenAPI
    description was not, so clients generated from this endpoint were told the
    summary section's ordinary state meant something had gone wrong. Pinned here
    because prose is exactly the part of a schema no other test touches.
    """

    def test_does_not_describe_unavailable_as_a_failure(self) -> None:
        described = (
            DashboardSectionSchema[SummarySectionSchema]
            .model_fields["status"]
            .description
        )

        assert described is not None
        assert "could not be read or because there is nothing to report" in described

    def test_says_a_ready_section_may_still_be_empty(self) -> None:
        """The other half of the pair, and the one W29's empty lines rest on."""
        described = (
            DashboardSectionSchema[SummarySectionSchema]
            .model_fields["status"]
            .description
        )

        assert described is not None
        assert "empty payload is then a real answer" in described
