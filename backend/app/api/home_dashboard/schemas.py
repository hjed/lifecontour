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

# A second alias for the same type, for the one model that also has a field
# **named** ``date_type``: a field name shadows a module-level alias inside a
# class body, and the annotation would resolve to the field rather than to
# ``datetime.date``.
from datetime import date as calendar_date
from datetime import date as date_type
from datetime import datetime as datetime_type
from datetime import time as time_type
from typing import Literal

from core_shared.models.contacts.important_date_types import ImportantDateType
from pydantic import BaseModel, Field

from app.api.common.schemas import JsonApiLinks
from app.core.contacts.models.upcoming_dates import UpcomingContactDate
from app.core.dashboard.models.sections import (
    AgendaDay,
    AgendaSectionData,
    DashboardSection,
    DashboardSummaryState,
    HomeDashboard,
    SectionStatus,
    SummarySectionData,
    UpcomingDatesSectionData,
)
from app.core.journal.models.agenda import AgendaEntry

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


class AgendaDaySchema(BaseModel):
    """One day's event journals — the shape tomorrow arrives in.

    A *day* rather than a bare list, so the disclosure that renders it can label
    itself with the date the entries were actually windowed on instead of one
    the browser works out in its own zone.
    """

    date: date_type = Field(
        ...,
        description=(
            "The local day these entries were windowed on, as `YYYY-MM-DD` in "
            "`meta.anchor.timezone`. Label the disclosure from this rather than "
            "from the browser's clock, which can be on a different day."
        ),
    )
    entries: list[AgendaEntrySchema] = Field(
        default_factory=list,
        description=(
            "The day's events, in the same form and the same order as today's: "
            "every all-day entry first, then the timed ones ascending by start. "
            "The collapsed label's count is this list's length — it is not "
            "capped, so no separate count is sent. An empty list is a real "
            "answer: nothing is scheduled that day."
        ),
    )


class AgendaSectionSchema(BaseModel):
    """Today's event journals in the order they should be rendered, then tomorrow's."""

    entries: list[AgendaEntrySchema] = Field(
        default_factory=list,
        description=(
            "Today's events: every all-day entry first, then the timed ones "
            "ascending by start. An **empty list is a real answer** — nothing is "
            "scheduled today — and is not the same as the section being "
            "unavailable, where `data` is null instead."
        ),
    )
    tomorrow: AgendaDaySchema = Field(
        ...,
        description=(
            "Tomorrow's events, in the same form, for the collapsed disclosure "
            "beneath today's list. Always present on a ready agenda — it rides "
            "in this payload so the page stays one round trip — and its "
            "`entries` may be empty."
        ),
    )


class TasksSectionSchema(BaseModel):
    """Not-done tasks due in the next seven days. Fields land in Phase 13."""


class UpcomingDateSchema(BaseModel):
    """One important date coming up, as a row renders it (**W31**)."""

    contact_id: int = Field(..., description="The contact, for linking to them")
    contact_name: str = Field(
        ...,
        description=(
            "The name to show — their nickname where they have one, by the same "
            "rule the rest of the app displays a contact under."
        ),
    )
    photo_url: str | None = Field(
        default=None, description="Their avatar, or null when they have none"
    )
    date_type: ImportantDateType = Field(
        ...,
        description=(
            "What kind of date it is. Every type participates: `year` precision "
            "is what decides a date has no occurrence, not the type, so a "
            "`first_met` recorded to the day is here as a real anniversary."
        ),
    )
    custom_date_type_name: str | None = Field(
        default=None,
        description=(
            "What the user called this kind of date, present only when "
            "`date_type` is `custom`. Show this rather than the word "
            '"custom", which means nothing to the person who named it.'
        ),
    )
    occurs_on: calendar_date = Field(
        ...,
        description=(
            "The day it falls on **this time round**, as `YYYY-MM-DD` in "
            "`meta.anchor.timezone`. A recurring date is already resolved into "
            "the window, so this is a real day in it and not the year it was "
            "first recorded."
        ),
    )
    days_away: int = Field(
        ...,
        description=(
            "How many days from the window's first day — `0` means today. Sent "
            "rather than left to be derived, because subtracting two dates in "
            "the browser's zone can disagree with the day the server windowed "
            "on."
        ),
    )
    years: int | None = Field(
        default=None,
        description=(
            "How many years this occurrence makes — an age for a birthday, a "
            "count for an anniversary. **Null where there is no answer**: the "
            "date was recorded without a year, or with one after the "
            "occurrence. Render the bare type in that case rather than "
            "inventing a number. `0` is a real count, not a missing one."
        ),
    )
    observed_for_leap_day: bool = Field(
        ...,
        description=(
            "Whether `occurs_on` is a stand-in — true only for a 29 February "
            "date in a year that has no 29th, which is observed on the 28th. "
            "Sent so the substitution is visible rather than looking like a "
            "quietly different date."
        ),
    )


class UpcomingDatesWindowSchema(BaseModel):
    """The span the dates were read for, in the acting user's timezone."""

    start_date: date_type = Field(
        ..., description="Today in your timezone — the window includes it"
    )
    end_date: date_type = Field(
        ..., description="The last day in the window, which is also included"
    )
    days_ahead: int = Field(
        ...,
        description=(
            "How far ahead this section looked. Echoed rather than left to be "
            "derived by subtracting the two dates, so a surface can label "
            "itself without doing calendar arithmetic."
        ),
    )


class UpcomingDatesSectionSchema(BaseModel):
    """Important contact dates falling in the same seven days the tasks cover."""

    window: UpcomingDatesWindowSchema = Field(
        ...,
        description=(
            "The span these dates were read for. Present even when `dates` is "
            "empty, which is the case a section cannot describe without it."
        ),
    )
    total: int = Field(
        ...,
        description=(
            "How many dates fall in the window. The same as `dates.length`, "
            "because the window is **not capped** — the whole of it travels so "
            "a show-more costs no second request — and named because that is "
            "the number a truncated list's show-more displays."
        ),
    )
    dates: list[UpcomingDateSchema] = Field(
        default_factory=list,
        description=(
            "The occurrences, ordered by date ascending and, within a day, by "
            "how much the contact matters to you. That ranking is **inferred** "
            "from favourite status and recent activity and is deliberately not "
            "published here: there is no importance field for a user to set, "
            "and none for a surface to show. An **empty list is a real "
            "answer** — nothing is coming up — and is not the same as the "
            "section being unavailable, where `data` is null instead."
        ),
    )


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


def _agenda_day(day: AgendaDay) -> AgendaDaySchema:
    """One day on the wire, through the same entry renderer as today's list."""
    return AgendaDaySchema(
        date=day.date, entries=[_agenda_entry(entry) for entry in day.entries]
    )


def _agenda(data: AgendaSectionData) -> AgendaSectionSchema:
    """The agenda payload, preserving the order the service settled on."""
    return AgendaSectionSchema(
        entries=[_agenda_entry(entry) for entry in data.entries],
        tomorrow=_agenda_day(data.tomorrow),
    )


def _upcoming_date(date: UpcomingContactDate) -> UpcomingDateSchema:
    """One occurrence on the wire — a transcription, deciding nothing.

    The recurrence was resolved and the row was ranked before this is reached,
    so neither is recomputed here. The importance the row was ranked *by* is
    deliberately dropped: it is a ranking input, not something the page shows.
    """
    return UpcomingDateSchema(
        contact_id=date.contact.id,
        contact_name=date.contact.display_name,
        photo_url=date.contact.photo_url,
        date_type=date.occurrence.important_date.date_type,
        custom_date_type_name=date.occurrence.important_date.custom_date_type_name,
        occurs_on=date.occurrence.occurs_on,
        days_away=date.occurrence.days_away,
        years=date.occurrence.years,
        observed_for_leap_day=date.occurrence.observed_for_leap_day,
    )


def _upcoming_dates(data: UpcomingDatesSectionData) -> UpcomingDatesSectionSchema:
    """The upcoming-dates payload, preserving the order the service settled on.

    ``total`` is derived from the same tuple the rows come from, so the count
    and the list cannot drift apart on the wire.
    """
    return UpcomingDatesSectionSchema(
        window=UpcomingDatesWindowSchema(
            start_date=data.window.first_day,
            end_date=data.window.last_day,
            days_ahead=data.window.days_ahead,
        ),
        total=len(data.dates),
        dates=[_upcoming_date(date) for date in data.dates],
    )


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
                    _upcoming_dates,
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
