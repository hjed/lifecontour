"""Logbook export API controller.

Handles the outdoor logbook PDF export endpoint.
"""

import io
from datetime import datetime

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from app.core.journal.services.logbook_data_service import LogbookDataService
from app.core.journal.services.logbook_pdf_renderer import LogbookPdfRenderer
from app.infrastructure.auth.models import SessionUser

logger = structlog.get_logger()

router = APIRouter(
    prefix="/journals/export",
    tags=["journals"],
)


class LogbookExportRequest(BaseModel):
    """Request body for logbook export."""

    start_date: str | None = None
    end_date: str | None = None
    activity_types: list[str] | None = None

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date(cls, v: str | None) -> str | None:
        if v is not None:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


@router.post("/outdoor-logbook")
@inject
async def export_outdoor_logbook(
    request: LogbookExportRequest,
    user: FromDishka[SessionUser],
    data_service: FromDishka[LogbookDataService],
    renderer: FromDishka[LogbookPdfRenderer],
) -> StreamingResponse:
    """Export outdoor logbook as a downloadable PDF.

    Accepts optional date range and activity type filters.
    Returns a PDF file response with the logbook data.
    """
    logger.info(
        "Generating outdoor logbook PDF export",
        user_id=user.id,
        start_date=request.start_date,
        end_date=request.end_date,
        activity_types=request.activity_types,
    )

    # Gather logbook data with optional filters
    export_data = await data_service.get_logbook_data(
        user_id=user.id,
        start_date=request.start_date,
        end_date=request.end_date,
        activity_types=request.activity_types,
    )

    # Render PDF
    pdf_bytes = renderer.render(export_data)

    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d")
    filename = f"outdoor_logbook_{timestamp}.pdf"

    logger.info(
        "Outdoor logbook PDF export generated",
        user_id=user.id,
        entry_count=len(export_data.entries),
        pdf_size_bytes=len(pdf_bytes),
    )

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
