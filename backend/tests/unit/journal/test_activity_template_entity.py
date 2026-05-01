"""Unit tests for ActivityTemplate entity."""

import pytest
from core_shared.models.journals import (
    VALID_CLIMBING_TYPES,
    ActivityTemplateValidationError,
)
from core_shared.models.journals.activity_template import ActivityTemplate
from core_shared.models.journals.constants import (
    MAX_TEMPLATE_NAME_LENGTH,
    VALID_CANYON_TYPES,
    VALID_TEMPLATE_TYPES,
)
from core_shared.models.journals.template_pitch import TemplatePitch


@pytest.mark.unit
class TestActivityTemplateCreation:
    """Test ActivityTemplate entity creation."""

    def test_create_with_required_fields_only(self):
        """Test creating a template with only required fields."""
        template = ActivityTemplate(
            name="Claustral Canyon",
            template_type="canyoning",
            user_id="user-123",
        )

        assert template.name == "Claustral Canyon"
        assert template.template_type == "canyoning"
        assert template.user_id == "user-123"
        assert template.id is not None  # Auto-generated UUID
        assert template.region is None
        assert template.description is None
        assert template.pitches == []
        assert template.french_grade is None
        assert template.canyon_type is None
        assert template.water_gauge_name is None
        assert template.is_vertical is None
        assert template.is_horizontal is None
        assert template.climbing_type is None
        assert template.grade is None
        assert template.length is None
        assert template.created_at is None
        assert template.updated_at is None

    def test_create_canyoning_template_with_all_fields(self):
        """Test creating a canyoning template with all fields populated."""
        pitches = [
            TemplatePitch(template_id="tid", pitch_number=1, height=20),
            TemplatePitch(template_id="tid", pitch_number=2, height=30),
        ]
        template = ActivityTemplate(
            id="my-uuid-123",
            name="Empress Canyon",
            template_type="canyoning",
            user_id="user-123",
            region="Blue Mountains",
            description="Beautiful canyon with multiple drops",
            pitches=pitches,
            french_grade="v4a3II",
            canyon_type="mixed",
            water_gauge_name="Kedumba",
        )

        assert template.id == "my-uuid-123"
        assert template.name == "Empress Canyon"
        assert template.template_type == "canyoning"
        assert template.region == "Blue Mountains"
        assert template.description == "Beautiful canyon with multiple drops"
        assert len(template.pitches) == 2
        assert template.french_grade == "v4a3II"
        assert template.canyon_type == "mixed"
        assert template.water_gauge_name == "Kedumba"

    def test_create_caving_template_with_type_specific_fields(self):
        """Test creating a caving template with is_vertical/is_horizontal."""
        template = ActivityTemplate(
            name="Jenolan Imperial Cave",
            template_type="caving",
            user_id="user-123",
            is_vertical=True,
            is_horizontal=False,
        )

        assert template.template_type == "caving"
        assert template.is_vertical is True
        assert template.is_horizontal is False

    def test_create_climbing_template_with_type_specific_fields(self):
        """Test creating a climbing template with climbing-specific fields."""
        template = ActivityTemplate(
            name="Point Perpendicular - Crust",
            template_type="climbing",
            user_id="user-123",
            climbing_type="sport",
            grade=22,
            length=25,
        )

        assert template.template_type == "climbing"
        assert template.climbing_type == "sport"
        assert template.grade == 22
        assert template.length == 25

    def test_auto_generated_id_is_uuid_format(self):
        """Test that the auto-generated ID is a valid UUID string."""
        template = ActivityTemplate(
            name="Test", template_type="canyoning", user_id="user-123"
        )

        # UUID format: 8-4-4-4-12 hex chars
        assert template.id is not None
        parts = template.id.split("-")
        assert len(parts) == 5
        assert len(parts[0]) == 8
        assert len(parts[1]) == 4

    def test_explicit_id_preserved(self):
        """Test that an explicitly provided ID is preserved, not overwritten."""
        template = ActivityTemplate(
            id="explicit-id",
            name="Test",
            template_type="canyoning",
            user_id="user-123",
        )

        assert template.id == "explicit-id"


@pytest.mark.unit
class TestActivityTemplateNameValidation:
    """Test ActivityTemplate name validation."""

    def test_empty_name_raises_error(self):
        """Test that empty name raises validation error."""
        with pytest.raises(ActivityTemplateValidationError) as exc_info:
            ActivityTemplate(name="", template_type="canyoning", user_id="user-123")

        assert "name" in str(exc_info.value)

    def test_whitespace_only_name_raises_error(self):
        """Test that whitespace-only name raises validation error."""
        with pytest.raises(ActivityTemplateValidationError) as exc_info:
            ActivityTemplate(name="   ", template_type="canyoning", user_id="user-123")

        assert "name" in str(exc_info.value)

    def test_name_too_long_raises_error(self):
        """Test that a name exceeding MAX_TEMPLATE_NAME_LENGTH raises error."""
        long_name = "x" * (MAX_TEMPLATE_NAME_LENGTH + 1)
        with pytest.raises(ActivityTemplateValidationError) as exc_info:
            ActivityTemplate(
                name=long_name, template_type="canyoning", user_id="user-123"
            )

        assert "name" in str(exc_info.value)

    def test_name_at_max_length_is_valid(self):
        """Test that a name at exactly MAX_TEMPLATE_NAME_LENGTH is valid."""
        max_name = "x" * MAX_TEMPLATE_NAME_LENGTH
        template = ActivityTemplate(
            name=max_name, template_type="canyoning", user_id="user-123"
        )
        assert template.name == max_name


@pytest.mark.unit
class TestActivityTemplateTypeValidation:
    """Test ActivityTemplate template_type validation."""

    @pytest.mark.parametrize("template_type", VALID_TEMPLATE_TYPES)
    def test_valid_template_types(self, template_type: str):
        """Test all valid template type values."""
        template = ActivityTemplate(
            name="Test", template_type=template_type, user_id="user-123"
        )
        assert template.template_type == template_type

    def test_invalid_template_type_raises_error(self):
        """Test that an invalid template type raises validation error."""
        with pytest.raises(ActivityTemplateValidationError) as exc_info:
            ActivityTemplate(name="Test", template_type="surfing", user_id="user-123")

        assert "template_type" in str(exc_info.value)

    def test_empty_template_type_raises_error(self):
        """Test that empty template type raises validation error."""
        with pytest.raises(ActivityTemplateValidationError) as exc_info:
            ActivityTemplate(name="Test", template_type="", user_id="user-123")

        assert "template_type" in str(exc_info.value)


@pytest.mark.unit
class TestActivityTemplateUserIdValidation:
    """Test ActivityTemplate user_id validation."""

    def test_empty_user_id_raises_error(self):
        """Test that empty user_id raises validation error."""
        with pytest.raises(ActivityTemplateValidationError) as exc_info:
            ActivityTemplate(name="Test", template_type="canyoning", user_id="")

        assert "user_id" in str(exc_info.value)


@pytest.mark.unit
class TestActivityTemplateCanyonTypeValidation:
    """Test ActivityTemplate canyon_type validation for canyoning templates."""

    @pytest.mark.parametrize("canyon_type", VALID_CANYON_TYPES)
    def test_valid_canyon_types(self, canyon_type: str):
        """Test all valid canyon type values."""
        template = ActivityTemplate(
            name="Test",
            template_type="canyoning",
            user_id="user-123",
            canyon_type=canyon_type,
        )
        assert template.canyon_type == canyon_type

    def test_invalid_canyon_type_raises_error(self):
        """Test that an invalid canyon type raises validation error."""
        with pytest.raises(ActivityTemplateValidationError) as exc_info:
            ActivityTemplate(
                name="Test",
                template_type="canyoning",
                user_id="user-123",
                canyon_type="underground",
            )

        assert "canyon_type" in str(exc_info.value)

    def test_none_canyon_type_valid(self):
        """Test that None canyon type is valid (field is optional)."""
        template = ActivityTemplate(
            name="Test",
            template_type="canyoning",
            user_id="user-123",
            canyon_type=None,
        )
        assert template.canyon_type is None


@pytest.mark.unit
class TestActivityTemplateClimbingTypeValidation:
    """Test ActivityTemplate climbing_type validation for climbing templates."""

    @pytest.mark.parametrize("climbing_type", VALID_CLIMBING_TYPES)
    def test_valid_climbing_types(self, climbing_type: str):
        """Test all valid climbing type values."""
        template = ActivityTemplate(
            name="Test",
            template_type="climbing",
            user_id="user-123",
            climbing_type=climbing_type,
        )
        assert template.climbing_type == climbing_type

    def test_invalid_climbing_type_raises_error(self):
        """Test that an invalid climbing type raises validation error."""
        with pytest.raises(ActivityTemplateValidationError) as exc_info:
            ActivityTemplate(
                name="Test",
                template_type="climbing",
                user_id="user-123",
                climbing_type="free solo",
            )

        assert "climbing_type" in str(exc_info.value)

    def test_none_climbing_type_valid(self):
        """Test that None climbing type is valid (field is optional)."""
        template = ActivityTemplate(
            name="Test",
            template_type="climbing",
            user_id="user-123",
            climbing_type=None,
        )
        assert template.climbing_type is None


@pytest.mark.unit
class TestActivityTemplateOptionalFields:
    """Test ActivityTemplate optional fields."""

    def test_region_optional(self):
        """Test that region is optional."""
        template = ActivityTemplate(
            name="Test",
            template_type="canyoning",
            user_id="user-123",
            region="Blue Mountains",
        )
        assert template.region == "Blue Mountains"

    def test_description_optional(self):
        """Test that description is optional."""
        template = ActivityTemplate(
            name="Test",
            template_type="canyoning",
            user_id="user-123",
            description="A long description about this canyon",
        )
        assert template.description == "A long description about this canyon"

    def test_pitches_default_empty_list(self):
        """Test that pitches defaults to an empty list."""
        template = ActivityTemplate(
            name="Test", template_type="canyoning", user_id="user-123"
        )
        assert template.pitches == []
        assert isinstance(template.pitches, list)

    def test_pitches_not_shared_between_instances(self):
        """Test that the default pitches list is not shared between instances."""
        t1 = ActivityTemplate(
            name="Test1", template_type="canyoning", user_id="user-123"
        )
        t2 = ActivityTemplate(
            name="Test2", template_type="canyoning", user_id="user-123"
        )
        t1.pitches.append(TemplatePitch(template_id="x", pitch_number=1))
        assert len(t2.pitches) == 0

    def test_climbing_grade_and_length_optional(self):
        """Test that climbing grade and length are optional integers."""
        template = ActivityTemplate(
            name="Test",
            template_type="climbing",
            user_id="user-123",
            grade=22,
            length=30,
        )
        assert template.grade == 22
        assert template.length == 30
