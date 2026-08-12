"""JSON:API schemas for the home dashboard singleton.

Two shapes here are the specification's rulings rather than this API's taste, and
every later phase inherits them. Both are documented in full in
*API Design — Home Dashboard Endpoint*; the short version:

- **A degraded section is part of ``data``.** A document's top level may not hold
  ``data`` and ``errors`` together, so "three sections and a failure in the
  fourth" has no representation as an error document. Each section travels in a
  :class:`DashboardSectionSchema` that can say ``unavailable`` on its own, the
  response stays 200, and the distinction the page depends on — nothing to show
  versus could not be read — is a field rather than a status code.
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
from typing import Literal

from pydantic import BaseModel, Field

from app.api.common.schemas import JsonApiLinks
from app.core.dashboard.models.sections import (
    DashboardSection,
    HomeDashboard,
    SectionStatus,
)

RESOURCE_TYPE_DESC = "Resource type"
HOME_DASHBOARD_RESOURCE_TYPE: Literal["home-dashboards"] = "home-dashboards"
HOME_DASHBOARD_PATH = "/api/home-dashboard"

_STATUS_DESC = (
    "Whether this section could be read. `ready` means it was, and an empty "
    "payload is then a real answer — nothing scheduled, nothing due. "
    "`unavailable` means it could not be, and `data` is null so the two can "
    "never be confused."
)


class DashboardSectionSchema[T](BaseModel):
    """One dashboard section: whether it could be read, and what it holds."""

    status: SectionStatus = Field(..., description=_STATUS_DESC)
    data: T | None = Field(
        default=None,
        description="The section's payload, or null when it is unavailable",
    )


class SummarySectionSchema(BaseModel):
    """Today's daily summary. Fields land in Phase 2."""


class AgendaSectionSchema(BaseModel):
    """Today's event journals, and tomorrow's. Fields land in Phases 5 and 6."""


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
                    lambda _data: SummarySectionSchema(),
                ),
                agenda=_rendered(
                    dashboard.agenda,
                    DashboardSectionSchema[AgendaSectionSchema],
                    lambda _data: AgendaSectionSchema(),
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
