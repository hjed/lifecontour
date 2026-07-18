"""
Activity Template REST API controller.
"""

import uuid
from typing import Annotated

from core_shared.models.journals.activity_template import ActivityTemplate
from core_shared.models.journals.template_pitch import TemplatePitch
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.journals.converters import ActivityTemplateConverter
from app.api.journals.schemas import (
    ActivityTemplateCreateRequest,
    ActivityTemplateListResponse,
    ActivityTemplateResponse,
    ActivityTemplateUpdateRequest,
)
from app.core.journal.models.repositories import ActivityTemplateRepository
from app.core.journal.services.activity_template_service import ActivityTemplateService
from app.infrastructure.auth.models import SessionUser

router = APIRouter(prefix="/templates", tags=["Templates"])


@router.post("", status_code=201)
@inject
async def create_template(
    request: ActivityTemplateCreateRequest,
    service: FromDishka[ActivityTemplateService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
    req: Request,
) -> ActivityTemplateResponse:
    """Create a new activity template."""
    attrs = request.data.attributes
    try:
        template = ActivityTemplate(
            user_id=user.id,
            name=attrs.name,
            template_type=attrs.template_type,
            region=attrs.region,
            description=attrs.description,
            french_grade=attrs.french_grade,
            canyon_type=attrs.canyon_type,
            water_gauge_name=attrs.water_gauge_name,
            is_vertical=attrs.is_vertical,
            is_horizontal=attrs.is_horizontal,
            climbing_type=attrs.climbing_type,
            grade=attrs.grade,
            length=attrs.length,
        )
        if attrs.pitches:
            pitches = []
            for p in attrs.pitches:
                pitches.append(
                    TemplatePitch(
                        template_id=str(template.id),
                        pitch_number=p.pitch_number,
                        height=p.height,
                        anchor_location=p.anchor_location,
                        anchor_type=p.anchor_type,
                        did_rescue=p.did_rescue,
                        did_setup=p.did_setup,
                        notes=p.notes,
                    )
                )
            template.pitches = pitches
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    created = await service.create(template, transaction=connection)
    resource = ActivityTemplateConverter.to_resource(
        created, base_url=str(req.base_url)
    )
    return ActivityTemplateResponse(data=resource)


@router.get("")
@inject
async def get_templates(
    repo: FromDishka[ActivityTemplateRepository],
    user: FromDishka[SessionUser],
    req: Request,
    name: Annotated[str | None, Query(description="Filter by name")] = None,
    template_type: Annotated[
        str | None, Query(description="Filter by template type")
    ] = None,
) -> ActivityTemplateListResponse:
    """Get list of activity templates."""
    templates = await repo.find_by_user(user_id=user.id, template_type=template_type)
    if name:
        templates = [t for t in templates if name.lower() in t.name.lower()]

    resources = [
        ActivityTemplateConverter.to_resource(t, base_url=str(req.base_url))
        for t in templates
    ]
    return ActivityTemplateListResponse(data=resources)


@router.get("/{template_id}")
@inject
async def get_template(
    template_id: uuid.UUID,
    repo: FromDishka[ActivityTemplateRepository],
    user: FromDishka[SessionUser],
    req: Request,
) -> ActivityTemplateResponse:
    """Get a specific activity template."""
    template = await repo.find_by_id(str(template_id))
    if not template or template.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="ActivityTemplate not found"
        )

    resource = ActivityTemplateConverter.to_resource(
        template, base_url=str(req.base_url)
    )
    return ActivityTemplateResponse(data=resource)


@router.put("/{template_id}")
@inject
async def update_template(
    template_id: uuid.UUID,
    request: ActivityTemplateUpdateRequest,
    repo: FromDishka[ActivityTemplateRepository],
    service: FromDishka[ActivityTemplateService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
    req: Request,
) -> ActivityTemplateResponse:
    """Update a specific activity template."""
    template_id_str = str(template_id)
    if request.data.id != template_id_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL ID does not match request body ID",
        )

    template = await repo.find_by_id(template_id_str)
    if not template or template.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="ActivityTemplate not found"
        )

    attrs = request.data.attributes
    if attrs.name is not None:
        template.name = attrs.name
    if attrs.template_type is not None:
        template.template_type = attrs.template_type
    if attrs.region is not None:
        template.region = attrs.region
    if attrs.description is not None:
        template.description = attrs.description

    if attrs.french_grade is not None:
        template.french_grade = attrs.french_grade
    if attrs.canyon_type is not None:
        template.canyon_type = attrs.canyon_type
    if attrs.water_gauge_name is not None:
        template.water_gauge_name = attrs.water_gauge_name

    if attrs.is_vertical is not None:
        template.is_vertical = attrs.is_vertical
    if attrs.is_horizontal is not None:
        template.is_horizontal = attrs.is_horizontal

    if attrs.climbing_type is not None:
        template.climbing_type = attrs.climbing_type
    if attrs.grade is not None:
        template.grade = attrs.grade
    if attrs.length is not None:
        template.length = attrs.length

    try:
        if attrs.pitches is not None:
            pitches = []
            for p in attrs.pitches:
                pitches.append(
                    TemplatePitch(
                        template_id=template_id_str,
                        pitch_number=p.pitch_number,
                        height=p.height,
                        anchor_location=p.anchor_location,
                        anchor_type=p.anchor_type,
                        did_rescue=p.did_rescue,
                        did_setup=p.did_setup,
                        notes=p.notes,
                    )
                )
            template.pitches = pitches

        template.__post_init__()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    updated = await service.update(template, transaction=connection)
    resource = ActivityTemplateConverter.to_resource(
        updated, base_url=str(req.base_url)
    )
    return ActivityTemplateResponse(data=resource)


@router.delete("/{template_id}", status_code=204)
@inject
async def delete_template(
    template_id: uuid.UUID,
    repo: FromDishka[ActivityTemplateRepository],
    service: FromDishka[ActivityTemplateService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> None:
    """Delete a specific activity template."""
    template = await repo.find_by_id(str(template_id))
    if not template or template.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="ActivityTemplate not found"
        )

    await service.delete(str(template_id), transaction=connection)
