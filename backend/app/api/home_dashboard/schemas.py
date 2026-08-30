"""JSON:API schemas for the home dashboard singleton.

Two shapes here are the specification's rulings rather than this API's taste, and
every later phase inherits them. Both are documented in full in
*API Design — Home Dashboard Endpoint*; the short version:

- **A degraded section is part of ``data``.** A document's top level may not hold
  ``data`` and ``errors`` together, so "three sections and a failure in the
  fourth" has no representation as an error document. Each section travels in a
  :class:`DashboardSectionSchema` that can say ``unavailable`` on its own, the
  response stays 200, and the distinction the page depends on — a payload versus
  none — is a field rather than a status code.
- **The anchor travels in ``meta``**, because which day was read and in whose
  zone is information about how the answer was computed rather than a field of
  the resource. ``UpcomingTasksMeta`` made the same call for the upcoming-tasks
  window, and this uses a purpose-built meta model for the same reason: the
  shared ``JsonApiMeta``'s fields are the pagination ones a singleton lacks.

Compound documents (``relationships`` + ``included``) were considered and
declined — a relationship carries resource identifiers, with nowhere to put a
section's status — so later phases embed denormalised refs in section attributes,
as ``TaskReadAttributes`` already does.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date as date_type
from datetime import datetime as datetime_type
from datetime import time as time_type
from typing import Literal

from pydantic import BaseModel, Field

from app.api.common.schemas import JsonApiLinks
from app.core.dashboard.models.sections import (
    AgendaEntry,
    AgendaSectionData,
    DashboardSection,
    DashboardSummaryState,
    HomeDashboard,
    SectionStatus,
    SummarySectionData,
)

RESOURCE_TYPE_DESC = "Resource type"
HOME_DASHBOARD_RESOURCE_TYPE: Literal["home-dashboards"] = "home-dashboards"
HOME_DASHBOARD_PATH = "/api/home-dashboard"

_STATUS_DESC = (
    "Whether this section has anything for you. `ready` means it does, and an "
    "empty payload is then a real answer — nothing scheduled, nothing due. "
    "`unavailable` means it does not, and `data` is null so the two can never "
    "be confused. A section reports `unavailable` either because it could not "
    "be read or because there is nothing to report: the summary uses it for a "
    "day with no summary, since a summary is not a list and so has no empty "
    "form. Which of the two it was is deliberately not on the wire — both are "
    "rendered the same way — so treat it as 'nothing to show here', not as an "
    "error."
)


class DashboardSectionSchema[T](BaseModel):
    """One dashboard section: whether it has a payload, and what is in it."""

    status: SectionStatus = Field(..., description=_STATUS_DESC)
    data: T | None = Field(
        default=None,
        description="The section's payload, or null when it is unavailable",
    )


class SummarySectionSchema(BaseModel):
    """Today's daily summary — the same entity the journals view shows.

    Read-only. There is no regenerate link or action field here: regeneration is
    `POST /api/journals/daily-summary/{date}/regenerate`, and the date it needs
    is `meta.anchor.date`, which is present whether or not this section is.
    """

    state: DashboardSummaryState = Field(
        ...,
        description=(
            "`generated` when the summary is written and `summary_text` holds "
            "it; `generating` while it is queued or being produced, when there "
            "is nothing to read yet. There is no third value: a day with no "
            "summary makes the whole section `unavailable`."
        ),
    )
    summary_text: str | None = Field(
        default=None,
        description=(
            "The summary in full, or null while generating. Null rather than "
            "stale: a summary invalidated by a change to the day keeps its old "
            "text in storage, and this never returns it."
        ),
    )
    journal_count: int = Field(
        ..., description="Journals on this day — the first of the four key stats"
    )
    event_count: int = Field(..., description="Events on this day")
    contact_count: int = Field(..., description="Contacts seen or mentioned")
    mood_average: float | None = Field(
        default=None,
        description=(
            "Average mood for the day out of ten, or null when nothing was "
            "rated — which is most days, so surfaces must handle the null."
        ),
    )


class AgendaTagSchema(BaseModel):
    """One of an entry's tags, with the colour the badge is drawn in."""

    id: str = Field(..., description="The tag's id")
    name: str = Field(..., description="The tag's name, as the badge's label")
    color: str | None = Field(
        default=None,
        description=(
            "The tag's own colour as a hex string, or null when it has none. A "
            "surface must not rely on it alone to convey anything: the name is "
            "the label, and the colour is decoration on top of it. Spelled "
            "`color` to match the tags API and the column, not this document's "
            "usual Australian English."
        ),
    )


class AgendaParticipantSchema(BaseModel):
    """Somebody at the event, for the entry's avatar stack."""

    contact_id: int = Field(..., description="The contact's id, for linking")
    name: str = Field(
        ...,
        description=(
            "The contact's display name. Sent whole rather than as parts so a "
            "surface showing initials has a readable label behind them."
        ),
    )


class AgendaEntrySchema(BaseModel):
    """One event journal on the agenda.

    Deliberately **data rather than finished strings**: all-day and cancelled are
    booleans, tags carry a name beside their colour, and participants carry
    names. A payload of pre-formatted text would take the accessible rendering
    decisions away from the surface that has to make them.
    """

    journal_id: int = Field(..., description="The journal, for linking to it")
    title: str = Field(..., description="The journal's title")
    is_all_day: bool = Field(
        ...,
        description=(
            "Whether the event covers the whole day. All-day entries are listed "
            "above timed ones and carry no clock times."
        ),
    )
    starts_at: datetime_type = Field(
        ...,
        description=(
            "The instant the event begins, from the journal's event date range. "
            "This is what the list is ordered by and the only way to tell that "
            "an entry began before today — a multi-day event on today's agenda "
            "can start well before it."
        ),
    )
    ends_at: datetime_type = Field(
        ..., description="The instant the event ends, from the same range"
    )
    start_time: time_type | None = Field(
        default=None,
        description=(
            "The event's own start time as a clock value — what to render as "
            "`HH:MM`. Null for an all-day event, and null for a timed one whose "
            "times were never filled in."
        ),
    )
    end_time: time_type | None = Field(
        default=None, description="The event's end time as a clock value, or null"
    )
    timezone: str | None = Field(
        default=None,
        description=(
            "The IANA zone `start_time` and `end_time` are expressed in — the "
            "**event's** zone, not yours. An event in another zone keeps its own "
            "wall time here, so render the clock values against this rather than "
            "against the dashboard's anchor zone. Null when the event has none, "
            "in which case they are UTC. `starts_at` is the unambiguous instant "
            "if you would rather compute the time yourself."
        ),
    )
    location: str | None = Field(
        default=None, description="Where it is, when the event says"
    )
    calendar_color: str | None = Field(
        default=None,
        description=(
            "The colour of the calendar this event belongs to, as a hex string "
            "— what a surface keys the row's accent to. Null when the calendar "
            "has none, so a surface needs its own fallback. Like a tag's "
            "colour, it is decoration: it must not be the only thing carrying "
            "meaning in the row."
        ),
    )
    is_cancelled: bool = Field(
        ...,
        description=(
            "Whether the event has been cancelled. Cancelled events are returned "
            "**flagged rather than omitted**, so a surface can show them clearly "
            "marked — but a surface must never present one as still happening."
        ),
    )
    tags: list[AgendaTagSchema] = Field(
        default_factory=list, description="The journal's tags"
    )
    participants: list[AgendaParticipantSchema] = Field(
        default_factory=list,
        description=(
            "Who is at the event — contacts linked to the journal as attendees "
            "(participants and invitees). People merely mentioned in it are not "
            "here, because they were never claimed to be there."
        ),
    )


class AgendaSectionSchema(BaseModel):
    """Today's event journals, in the order they should be rendered.

    Tomorrow's entries and their count join this payload in a later phase.
    """

    entries: list[AgendaEntrySchema] = Field(
        default_factory=list,
        description=(
            "Today's events: every all-day entry first, then the timed ones "
            "ascending by start. An **empty list is a real answer** — nothing is "
            "scheduled today — and is not the same as the section being "
            "unavailable, where `data` is null instead."
        ),
    )


class TasksSectionSchema(BaseModel):
    """Not-done tasks due in the next seven days. Fields land in Phase 13."""


class UpcomingDatesSectionSchema(BaseModel):
    """Important contact dates in the next seven days. Fields land in Phase 11."""


class HomeDashboardAttributes(BaseModel):
    """The four sections of the dashboard, each independently available."""

    summary: DashboardSectionSchema[SummarySectionSchema] = Field(
        ..., description="Today's daily summary — the page's headline"
    )
    agenda: DashboardSectionSchema[AgendaSectionSchema] = Field(
        ..., description="What is scheduled today, and tomorrow"
    )
    tasks: DashboardSectionSchema[TasksSectionSchema] = Field(
        ..., description="Not-done tasks due between today and seven days ahead"
    )
    upcoming_dates: DashboardSectionSchema[UpcomingDatesSectionSchema] = Field(
        ..., description="Important contact dates falling in the same seven days"
    )


class HomeDashboardResource(BaseModel):
    """The home dashboard as a JSON:API resource.

    A singleton projection whose id is the user's id — one dashboard per user,
    computed rather than stored, following the outdoor dashboard and daily
    summary. The specification has no singleton concept and requires an ``id`` on
    every resource object, so the user's is the only honest one available.
    """

    type: str = Field(
        default=HOME_DASHBOARD_RESOURCE_TYPE, description=RESOURCE_TYPE_DESC
    )
    id: str = Field(..., description="User ID the dashboard belongs to")
    attributes: HomeDashboardAttributes = Field(..., description="The four sections")
    links: JsonApiLinks | None = Field(default=None, description="Resource links")


class HomeDashboardAnchorSchema(BaseModel):
    """The day every section was read for, and the zone that decided it."""

    date: date_type = Field(
        ...,
        description=(
            "Today in your configured timezone. Every section's window is "
            "anchored on it, and a surface labelling the page should use it "
            "rather than the browser's idea of today, which can differ."
        ),
    )
    timezone: str = Field(
        ...,
        description=(
            "The IANA zone the anchor was resolved in — the stored setting, or "
            "UTC when it is unset or unrecognised. Echoed rather than assumed "
            "so a surface never labels UTC dates with a zone that was ignored."
        ),
    )


class HomeDashboardMeta(BaseModel):
    """The dashboard's metadata: which day it is about.

    A model of its own rather than the shared ``JsonApiMeta``, whose fields are
    the pagination ones — this projection is a singleton, so borrowing that model
    would advertise page controls that do not exist. The same reason
    ``UpcomingTasksMeta`` exists.
    """

    anchor: HomeDashboardAnchorSchema = Field(
        ..., description="The day the dashboard is about"
    )


class HomeDashboardResponse(BaseModel):
    """Response model for the home dashboard.

    ``meta`` is required rather than optional: the anchor is how a client knows
    which day it is rendering, and that is true even when every section is empty.
    """

    data: HomeDashboardResource = Field(..., description="The dashboard resource")
    meta: HomeDashboardMeta = Field(..., description="The day it is about")


def home_dashboard_self_link(base_url: str = "") -> str:
    """The canonical URL of the dashboard resource.

    ``base_url`` is a parameter with an empty default rather than something read
    from a request, so the renderers below stay pure functions of their arguments
    — the shape ``task_self_link`` and ``ContactConverter.to_resource`` use.
    """
    return f"{base_url}{HOME_DASHBOARD_PATH}"


def _rendered[T, P: BaseModel](
    section: DashboardSection[T],
    envelope: type[DashboardSectionSchema[P]],
    render: Callable[[T], P],
) -> DashboardSectionSchema[P]:
    """One section, rendered into its envelope.

    The status is derived from whether a payload was read rather than copied
    across, so ``data: null`` and ``status: "unavailable"`` cannot drift apart on
    the wire whatever the domain object holds.

    ``envelope`` is passed because a Pydantic generic must be parametrised to be
    constructed, and ``render`` is where each later phase maps its own section's
    domain payload to its schema — the seam Phases 2, 5–6, 11 and 13 fill.
    """
    if section.data is None:
        return envelope(status=SectionStatus.UNAVAILABLE)
    return envelope(status=SectionStatus.READY, data=render(section.data))


def _agenda_entry(entry: AgendaEntry) -> AgendaEntrySchema:
    """One entry on the wire — a transcription, with no rules of its own.

    Which entries are on the agenda and what order they are in were both settled
    before this is reached, so nothing here re-sorts or re-filters: a renderer
    that did would be a second copy of a rule that already has a home.
    """
    return AgendaEntrySchema(
        journal_id=entry.journal_id,
        title=entry.title,
        is_all_day=entry.is_all_day,
        starts_at=entry.starts_at,
        ends_at=entry.ends_at,
        start_time=entry.start_time,
        end_time=entry.end_time,
        timezone=entry.timezone,
        location=entry.location,
        calendar_color=entry.calendar_color,
        is_cancelled=entry.is_cancelled,
        tags=[
            AgendaTagSchema(id=tag.id, name=tag.name, color=tag.color)
            for tag in entry.tags
        ],
        participants=[
            AgendaParticipantSchema(contact_id=person.contact_id, name=person.name)
            for person in entry.participants
        ],
    )


def _agenda(data: AgendaSectionData) -> AgendaSectionSchema:
    """The agenda payload, preserving the order the service settled on."""
    return AgendaSectionSchema(entries=[_agenda_entry(entry) for entry in data.entries])


def _summary(data: SummarySectionData) -> SummarySectionSchema:
    """The summary payload on the wire — a field-for-field copy.

    Nothing is decided here: which statuses are showable and whether the prose
    may be sent were settled in ``summary_section_for``, so this stays a
    transcription and the rules have one home.
    """
    return SummarySectionSchema(
        state=data.state,
        summary_text=data.summary_text,
        journal_count=data.journal_count,
        event_count=data.event_count,
        contact_count=data.contact_count,
        mood_average=data.mood_average,
    )


def to_home_dashboard_response(
    dashboard: HomeDashboard, base_url: str = ""
) -> HomeDashboardResponse:
    """Render an assembled dashboard as its JSON:API document.

    Pure — no request, no connection, no service — so the document's shape can be
    asserted directly by a unit test, like ``to_upcoming_tasks_response``.

    Args:
        dashboard: The assembled projection.
        base_url: Prefix for the ``self`` link, so it is absolute like every
            other resource's. The controller supplies it from the request.

    Returns:
        The document: the four sections in ``data``, the anchor in ``meta``.
    """
    return HomeDashboardResponse(
        data=HomeDashboardResource(
            id=dashboard.user_id,
            attributes=HomeDashboardAttributes(
                summary=_rendered(
                    dashboard.summary,
                    DashboardSectionSchema[SummarySectionSchema],
                    _summary,
                ),
                agenda=_rendered(
                    dashboard.agenda,
                    DashboardSectionSchema[AgendaSectionSchema],
                    _agenda,
                ),
                tasks=_rendered(
                    dashboard.tasks,
                    DashboardSectionSchema[TasksSectionSchema],
                    lambda _data: TasksSectionSchema(),
                ),
                upcoming_dates=_rendered(
                    dashboard.upcoming_dates,
                    DashboardSectionSchema[UpcomingDatesSectionSchema],
                    lambda _data: UpcomingDatesSectionSchema(),
                ),
            ),
            links=JsonApiLinks(self=home_dashboard_self_link(base_url)),
        ),
        meta=HomeDashboardMeta(
            anchor=HomeDashboardAnchorSchema(
                date=dashboard.anchor_date, timezone=dashboard.timezone
            )
        ),
    )
