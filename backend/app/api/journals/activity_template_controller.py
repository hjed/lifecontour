"""
Activity Template REST API controller.
"""

from core_shared.models.journals.activity_template import ActivityTemplate
from core_shared.models.journals.template_pitch import TemplatePitch
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Query, status

from app.api.journals.converters import ActivityTemplateConverter
from app.api.journals.schemas import (
    ActivityTemplateCreateRequest,
    ActivityTemplateListResponse,
    ActivityTemplateResponse,
    ActivityTemplateUpdateRequest,
)
from app.core.journal.models.repositories import ActivityTemplateRepository
from app.infrastructure.auth.models import SessionUser

router = APIRouter(prefix="/templates", tags=["Templates"])


@router.post("", response_model=ActivityTemplateResponse, status_code=201)
@inject
async def create_template(
    request: ActivityTemplateCreateRequest,
    repo: FromDishka[ActivityTemplateRepository],
    user: FromDishka[SessionUser],
) -> ActivityTemplateResponse:
    """Create a new activity template."""
    attrs = request.data.attributes
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
                )
            )
        template.pitches = pitches

    created = await repo.save(template)
    resource = ActivityTemplateConverter.to_resource(created)
    return ActivityTemplateResponse(data=resource)


@router.get("", response_model=ActivityTemplateListResponse)
@inject
async def get_templates(
    repo: FromDishka[ActivityTemplateRepository],
    user: FromDishka[SessionUser],
    name: str | None = Query(None, description="Filter by name"),
    template_type: str | None = Query(None, description="Filter by template type"),
) -> ActivityTemplateListResponse:
    """Get list of activity templates."""
    templates = await repo.find_by_user(user_id=user.id, template_type=template_type)
    if name:
        templates = [t for t in templates if name.lower() in t.name.lower()]

    resources = [ActivityTemplateConverter.to_resource(t) for t in templates]
    return ActivityTemplateListResponse(data=resources)


@router.get("/{template_id}", response_model=ActivityTemplateResponse)
@inject
async def get_template(
    template_id: str,
    repo: FromDishka[ActivityTemplateRepository],
    user: FromDishka[SessionUser],
) -> ActivityTemplateResponse:
    """Get a specific activity template."""
    template = await repo.find_by_id(template_id)
    if not template or template.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="ActivityTemplate not found"
        )

    resource = ActivityTemplateConverter.to_resource(template)
    return ActivityTemplateResponse(data=resource)


@router.put("/{template_id}", response_model=ActivityTemplateResponse)
@inject
async def update_template(
    template_id: str,
    request: ActivityTemplateUpdateRequest,
    repo: FromDishka[ActivityTemplateRepository],
    user: FromDishka[SessionUser],
) -> ActivityTemplateResponse:
    """Update a specific activity template."""
    template = await repo.find_by_id(template_id)
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

    if attrs.pitches is not None:
        pitches = []
        for p in attrs.pitches:
            pitches.append(
                TemplatePitch(
                    template_id=template_id,
                    pitch_number=p.pitch_number,
                    height=p.height,
                    anchor_location=p.anchor_location,
                    anchor_type=p.anchor_type,
                    did_rescue=p.did_rescue,
                    did_setup=p.did_setup,
                )
            )
        template.pitches = pitches

    updated = await repo.save(template)
    resource = ActivityTemplateConverter.to_resource(updated)
    return ActivityTemplateResponse(data=resource)


@router.delete("/{template_id}", status_code=204)
@inject
async def delete_template(
    template_id: str,
    repo: FromDishka[ActivityTemplateRepository],
    user: FromDishka[SessionUser],
) -> None:
    """Delete a specific activity template."""
    template = await repo.find_by_id(template_id)
    if not template or template.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="ActivityTemplate not found"
        )

    await repo.delete(template_id)
