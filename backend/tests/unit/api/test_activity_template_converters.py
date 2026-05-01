"""Unit tests for activity template API converters."""

from datetime import UTC, datetime

from core_shared.models.journals.activity_template import ActivityTemplate
from core_shared.models.journals.template_pitch import TemplatePitch

from app.api.journals.converters import ActivityTemplateConverter


class TestActivityTemplateConverter:
    """Tests for ActivityTemplateConverter."""

    def test_to_resource_canyoning_template(self) -> None:
        created_at = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
        template = ActivityTemplate(
            id="123e4567-e89b-12d3-a456-426614174000",
            name="Test Canyon",
            template_type="canyoning",
            user_id="user-1",
            region="Blue Mountains",
            description="A test canyon",
            french_grade="v3a2IV",
            canyon_type="vertical",
            water_gauge_name="Megalong",
            created_at=created_at,
            updated_at=created_at,
        )

        pitch1 = TemplatePitch(
            id=1,
            template_id=str(template.id),
            pitch_number=1,
            height=15,
            anchor_location="TR",
            anchor_type="double bolt",
        )
        template.pitches = [pitch1]

        resource = ActivityTemplateConverter.to_resource(
            template, base_url="http://test"
        )

        assert resource.id == template.id
        assert resource.type == "activity-templates"
        assert resource.attributes.name == "Test Canyon"
        assert resource.attributes.template_type == "canyoning"
        assert resource.attributes.region == "Blue Mountains"
        assert resource.attributes.description == "A test canyon"
        assert resource.attributes.french_grade == "v3a2IV"
        assert resource.attributes.canyon_type == "vertical"
        assert resource.attributes.water_gauge_name == "Megalong"
        assert resource.attributes.created_at == created_at

        assert len(resource.attributes.pitches) == 1
        assert resource.attributes.pitches[0].pitch_number == 1
        assert resource.attributes.pitches[0].height == 15
        assert resource.attributes.pitches[0].anchor_location == "TR"
        assert resource.attributes.pitches[0].anchor_type == "double bolt"

        assert resource.links is not None
        assert resource.links.self == f"http://test/api/templates/{template.id}"
