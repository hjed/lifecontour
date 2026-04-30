"""Daily summary API controllers.

Handles endpoints for on-demand AI daily summary generation and retrieval.
"""

from __future__ import annotations

from datetime import date

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.journal.services.daily_summary_service import DailySummaryService
from app.infrastructure.auth.models import SessionUser

logger = structlog.get_logger()

daily_summary_router = APIRouter(prefix="/journals/daily-summary", tags=["journals"])


class DailySummaryAttributes(BaseModel):
    """Attributes for a daily summary resource."""

    summary_date: str
    summary_text: str | None = None
    journal_count: int = 0
    event_count: int = 0
    contact_count: int = 0
    mood_average: float | None = None
    status: str


class DailySummaryResource(BaseModel):
    """JSON:API resource for a daily summary."""

    type: str = "journal-daily-summaries"
    id: str
    attributes: DailySummaryAttributes


class DailySummaryResponse(BaseModel):
    """JSON:API response for a daily summary."""

    data: DailySummaryResource | None = None


DailySummaryResponse.model_rebuild()


@daily_summary_router.get("/{summary_date}", response_model=DailySummaryResponse)
@inject
async def get_daily_summary(
    summary_date: date,
    daily_summary_service: FromDishka[DailySummaryService],
    _user: FromDishka[SessionUser],
) -> DailySummaryResponse:
    """Get or generate a daily summary for a specific date.

    Returns the cached summary if available, or generates a new one on-demand.
    For dates with fewer than 2 journals, returns a DISABLED summary.
    Returns null data when Gemini is not configured.
    """
    try:
        result = await daily_summary_service.get_or_generate(_user.id, summary_date)
    except Exception as err:
        logger.exception(
            "Failed to get or generate daily summary",
            user_id=_user.id,
            date=summary_date.isoformat(),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate daily summary",
        ) from err

    if result is None:
        return DailySummaryResponse(data=None)

    resource = DailySummaryResource(
        id=f"{_user.id}:{summary_date.isoformat()}",
        attributes=DailySummaryAttributes(
            summary_date=summary_date.isoformat(),
            summary_text=result.get_display_text(),
            journal_count=result.journal_count,
            event_count=result.event_count,
            contact_count=result.contact_count,
            mood_average=result.mood_average,
            status=str(result.status),
        ),
    )
    return DailySummaryResponse(data=resource)


@daily_summary_router.post(
    "/{summary_date}/regenerate", response_model=DailySummaryResponse
)
@inject
async def regenerate_daily_summary(
    summary_date: date,
    daily_summary_service: FromDishka[DailySummaryService],
    _user: FromDishka[SessionUser],
) -> DailySummaryResponse:
    """Force regenerate a daily summary for a specific date.

    Invalidates the existing cache and triggers a fresh AI generation.
    """
    try:
        result = await daily_summary_service.regenerate(_user.id, summary_date)
    except Exception as err:
        logger.exception(
            "Failed to regenerate daily summary",
            user_id=_user.id,
            date=summary_date.isoformat(),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to regenerate daily summary",
        ) from err

    if result is None:
        return DailySummaryResponse(data=None)

    resource = DailySummaryResource(
        id=f"{_user.id}:{summary_date.isoformat()}",
        attributes=DailySummaryAttributes(
            summary_date=summary_date.isoformat(),
            summary_text=result.get_display_text(),
            journal_count=result.journal_count,
            event_count=result.event_count,
            contact_count=result.contact_count,
            mood_average=result.mood_average,
            status=str(result.status),
        ),
    )
    return DailySummaryResponse(data=resource)
