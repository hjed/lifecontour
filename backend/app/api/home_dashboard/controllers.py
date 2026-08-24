"""REST controller for the home dashboard.

Deliberately thin: the projection, its day and its per-section resilience all
live in ``HomeDashboardService``, so this module makes one service call and one
render call. It opens **no** transaction — the whole path is read-only — and
catches nothing: a section that cannot be read is already reported inside the
payload by the time the controller sees it.
"""

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Request

from app.api.common.schemas import get_request_base_url
from app.api.home_dashboard.schemas import (
    HomeDashboardResponse,
    to_home_dashboard_response,
)
from app.core.dashboard.services.home_dashboard_service import HomeDashboardService
from app.infrastructure.auth.models import SessionUser

router = APIRouter()


@router.get("/home-dashboard")
@inject
async def get_home_dashboard(
    request: Request,
    dashboard_service: FromDishka[HomeDashboardService],
    user: FromDishka[SessionUser],
) -> HomeDashboardResponse:
    """The home page in one call: summary, agenda, tasks and upcoming dates.

    A read-only singleton projection whose id is your user id. It takes **no date
    parameters**: every window is anchored server-side on today in your
    configured timezone (UTC when unset), and `meta.anchor` says which day and
    which zone that was, so a surface can label the page without re-deriving the
    date in the browser's zone.

    **Sections are independent.** Each one reports `ready` — where an empty
    payload is a real answer — or `unavailable`, meaning it has nothing for you,
    whether because it could not be read or because there is none to report. A
    day with no summary reports `unavailable` for that reason, so read it as
    "nothing to show here" rather than as an error. One section failing never
    fails the request or the others, so this endpoint answers 200 with the
    sections it has.

    There is deliberately no equivalent MCP tool: an agent composes the same view
    from the daily summary, journal browsing, the task listing tools and the
    contacts tools, so nothing here is UI-only.
    """
    dashboard = await dashboard_service.dashboard(user.id)
    return to_home_dashboard_response(dashboard, get_request_base_url(request))
