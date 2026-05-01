"""Integration tests for SqlActivityTemplateRepository."""

import pytest
import pytest_asyncio
from core_shared.models.journals import ActivityTemplate
from core_shared.models.journals.template_pitch import TemplatePitch
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.activity_template_repository import (
    SqlActivityTemplateRepository,
)

TEST_USER_ID = "test-user-templates"
OTHER_USER_ID = "test-user-other"


@pytest_asyncio.fixture
async def template_repository(
    async_connection: AsyncConnection,
) -> SqlActivityTemplateRepository:
    """Create an activity template repository for testing."""
    return SqlActivityTemplateRepository(async_connection)


@pytest.mark.integration
class TestActivityTemplateRepositorySave:
    """Test activity template save operations."""

    async def test_save_creates_canyoning_template(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test creating a canyoning template with all fields and pitches."""
        pitches = [
            TemplatePitch(
                template_id="00000000-0000-0000-0000-000000000000",
                pitch_number=1,
                height=20,
                anchor_location="TR",
                anchor_type="chains",
                did_rescue=False,
                did_setup=True,
            ),
            TemplatePitch(
                template_id="00000000-0000-0000-0000-000000000000",
                pitch_number=2,
                height=30,
                anchor_location="Centre",
                anchor_type="double bolt",
            ),
        ]
        template = ActivityTemplate(
            name="Empress Canyon",
            template_type="canyoning",
            user_id=TEST_USER_ID,
            region="Blue Mountains",
            description="Classic Blue Mountains canyon",
            french_grade="v4a3II",
            canyon_type="mixed",
            water_gauge_name="Kedumba",
            pitches=pitches,
        )

        saved = await template_repository.save(template)

        assert saved.id is not None
        assert saved.name == "Empress Canyon"
        assert saved.template_type == "canyoning"
        assert saved.user_id == TEST_USER_ID
        assert saved.region == "Blue Mountains"
        assert saved.description == "Classic Blue Mountains canyon"
        assert saved.french_grade == "v4a3II"
        assert saved.canyon_type == "mixed"
        assert saved.water_gauge_name == "Kedumba"
        assert saved.created_at is not None
        assert saved.updated_at is not None
        # Verify pitches
        assert len(saved.pitches) == 2
        assert saved.pitches[0].pitch_number == 1
        assert saved.pitches[0].height == 20
        assert saved.pitches[0].anchor_location == "TR"
        assert saved.pitches[0].did_setup is True
        assert saved.pitches[1].pitch_number == 2
        assert saved.pitches[1].height == 30

    async def test_save_creates_caving_template(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test creating a caving template with caving-specific fields."""
        template = ActivityTemplate(
            name="Jenolan Imperial Cave",
            template_type="caving",
            user_id=TEST_USER_ID,
            is_vertical=True,
            is_horizontal=False,
        )

        saved = await template_repository.save(template)

        assert saved.template_type == "caving"
        assert saved.is_vertical is True
        assert saved.is_horizontal is False

    async def test_save_creates_climbing_template(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test creating a climbing template with climbing-specific fields."""
        template = ActivityTemplate(
            name="Crust - Point Perpendicular",
            template_type="climbing",
            user_id=TEST_USER_ID,
            climbing_type="sport",
            grade=22,
            length=25,
        )

        saved = await template_repository.save(template)

        assert saved.template_type == "climbing"
        assert saved.climbing_type == "sport"
        assert saved.grade == 22
        assert saved.length == 25

    async def test_save_creates_minimal_template(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test creating a template with only required fields."""
        template = ActivityTemplate(
            name="Basic Canyon",
            template_type="canyoning",
            user_id=TEST_USER_ID,
        )

        saved = await template_repository.save(template)

        assert saved.id is not None
        assert saved.name == "Basic Canyon"
        assert saved.region is None
        assert saved.description is None
        assert saved.french_grade is None
        assert saved.pitches == []

    async def test_save_upsert_updates_existing_template(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test that saving a template with same ID updates it."""
        template = ActivityTemplate(
            name="Original Name",
            template_type="canyoning",
            user_id=TEST_USER_ID,
            region="Blue Mountains",
        )
        first_save = await template_repository.save(template)

        updated = ActivityTemplate(
            id=first_save.id,
            name="Updated Name",
            template_type="canyoning",
            user_id=TEST_USER_ID,
            region="Kanangra-Boyd",
            french_grade="v3a2",
        )
        second_save = await template_repository.save(updated)

        assert second_save.id == first_save.id
        assert second_save.name == "Updated Name"
        assert second_save.region == "Kanangra-Boyd"
        assert second_save.french_grade == "v3a2"

    async def test_save_upsert_replaces_pitches(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test that updating a template replaces its pitches."""
        template = ActivityTemplate(
            name="Pitch Replace Test",
            template_type="canyoning",
            user_id=TEST_USER_ID,
            pitches=[
                TemplatePitch(
                    template_id="11111111-1111-1111-1111-111111111111",
                    pitch_number=1,
                    height=10,
                ),
                TemplatePitch(
                    template_id="11111111-1111-1111-1111-111111111111",
                    pitch_number=2,
                    height=20,
                ),
            ],
        )
        first_save = await template_repository.save(template)
        assert len(first_save.pitches) == 2

        # Update with different pitches
        updated = ActivityTemplate(
            id=first_save.id,
            name="Pitch Replace Test",
            template_type="canyoning",
            user_id=TEST_USER_ID,
            pitches=[
                TemplatePitch(
                    template_id="11111111-1111-1111-1111-111111111111",
                    pitch_number=1,
                    height=50,
                ),
            ],
        )
        second_save = await template_repository.save(updated)

        assert len(second_save.pitches) == 1
        assert second_save.pitches[0].height == 50

        # Verify via find_by_id
        found = await template_repository.find_by_id(first_save.id)  # type: ignore[arg-type]
        assert found is not None
        assert len(found.pitches) == 1


@pytest.mark.integration
class TestActivityTemplateRepositoryFind:
    """Test activity template find operations."""

    async def test_find_by_id_returns_template_with_pitches(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test that find_by_id returns a template with its pitches."""
        template = ActivityTemplate(
            name="Find Test Canyon",
            template_type="canyoning",
            user_id=TEST_USER_ID,
            pitches=[
                TemplatePitch(
                    template_id="11111111-1111-1111-1111-111111111111",
                    pitch_number=1,
                    height=15,
                ),
                TemplatePitch(
                    template_id="11111111-1111-1111-1111-111111111111",
                    pitch_number=2,
                    height=25,
                ),
            ],
        )
        saved = await template_repository.save(template)

        found = await template_repository.find_by_id(saved.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.id == saved.id
        assert found.name == "Find Test Canyon"
        assert len(found.pitches) == 2
        assert found.pitches[0].pitch_number == 1
        assert found.pitches[1].pitch_number == 2

    async def test_find_by_id_returns_none_for_nonexistent(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test that find_by_id returns None for non-existent ID."""
        found = await template_repository.find_by_id(
            "00000000-0000-0000-0000-000000000000"
        )

        assert found is None

    async def test_find_by_user_returns_all_user_templates(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test that find_by_user returns all templates for a user."""
        for name in ["Alpha Canyon", "Beta Cave", "Charlie Climb"]:
            t_type = (
                "canyoning"
                if "Canyon" in name
                else ("caving" if "Cave" in name else "climbing")
            )
            await template_repository.save(
                ActivityTemplate(name=name, template_type=t_type, user_id=TEST_USER_ID)
            )
        # Another user's template - should not be returned
        await template_repository.save(
            ActivityTemplate(
                name="Other User Canyon",
                template_type="canyoning",
                user_id=OTHER_USER_ID,
            )
        )

        templates = await template_repository.find_by_user(TEST_USER_ID)

        assert len(templates) == 3
        # Ordered by name ASC
        assert templates[0].name == "Alpha Canyon"
        assert templates[1].name == "Beta Cave"
        assert templates[2].name == "Charlie Climb"

    async def test_find_by_user_with_type_filter(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test that find_by_user filters by template_type."""
        await template_repository.save(
            ActivityTemplate(
                name="Canyon 1", template_type="canyoning", user_id=TEST_USER_ID
            )
        )
        await template_repository.save(
            ActivityTemplate(
                name="Cave 1", template_type="caving", user_id=TEST_USER_ID
            )
        )
        await template_repository.save(
            ActivityTemplate(
                name="Canyon 2", template_type="canyoning", user_id=TEST_USER_ID
            )
        )

        templates = await template_repository.find_by_user(
            TEST_USER_ID, template_type="canyoning"
        )

        assert len(templates) == 2
        assert all(t.template_type == "canyoning" for t in templates)

    async def test_find_by_user_returns_empty_for_no_templates(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test that find_by_user returns empty for user with no templates."""
        templates = await template_repository.find_by_user("nonexistent-user")

        assert templates == []


@pytest.mark.integration
class TestActivityTemplateRepositorySearch:
    """Test activity template search operations."""

    async def test_search_by_name_partial_match(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test that search_by_name matches partial names (ILIKE)."""
        await template_repository.save(
            ActivityTemplate(
                name="Empress Canyon", template_type="canyoning", user_id=TEST_USER_ID
            )
        )
        await template_repository.save(
            ActivityTemplate(
                name="Grand Canyon", template_type="canyoning", user_id=TEST_USER_ID
            )
        )
        await template_repository.save(
            ActivityTemplate(
                name="Blue Cave", template_type="caving", user_id=TEST_USER_ID
            )
        )

        results = await template_repository.search_by_name(TEST_USER_ID, "canyon")

        assert len(results) == 2
        assert results[0].name == "Empress Canyon"
        assert results[1].name == "Grand Canyon"

    async def test_search_by_name_case_insensitive(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test that search is case-insensitive."""
        await template_repository.save(
            ActivityTemplate(
                name="Empress Canyon", template_type="canyoning", user_id=TEST_USER_ID
            )
        )

        results = await template_repository.search_by_name(TEST_USER_ID, "EMPRESS")

        assert len(results) == 1
        assert results[0].name == "Empress Canyon"

    async def test_search_by_name_with_type_filter(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test search with template_type filter."""
        await template_repository.save(
            ActivityTemplate(
                name="Test Route 1", template_type="canyoning", user_id=TEST_USER_ID
            )
        )
        await template_repository.save(
            ActivityTemplate(
                name="Test Route 2", template_type="climbing", user_id=TEST_USER_ID
            )
        )

        results = await template_repository.search_by_name(
            TEST_USER_ID, "Test Route", template_type="climbing"
        )

        assert len(results) == 1
        assert results[0].template_type == "climbing"

    async def test_search_by_name_returns_empty_for_no_match(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test that search returns empty for no match."""
        await template_repository.save(
            ActivityTemplate(
                name="Empress Canyon", template_type="canyoning", user_id=TEST_USER_ID
            )
        )

        results = await template_repository.search_by_name(TEST_USER_ID, "nonexistent")

        assert results == []


@pytest.mark.integration
class TestActivityTemplateRepositoryDelete:
    """Test activity template delete operations."""

    async def test_delete_removes_template_and_pitches(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test that deleting a template also cascade-deletes its pitches."""
        template = ActivityTemplate(
            name="Delete Test",
            template_type="canyoning",
            user_id=TEST_USER_ID,
            pitches=[
                TemplatePitch(
                    template_id="11111111-1111-1111-1111-111111111111",
                    pitch_number=1,
                    height=20,
                ),
                TemplatePitch(
                    template_id="11111111-1111-1111-1111-111111111111",
                    pitch_number=2,
                    height=30,
                ),
            ],
        )
        saved = await template_repository.save(template)

        await template_repository.delete(saved.id)  # type: ignore[arg-type]

        found = await template_repository.find_by_id(saved.id)  # type: ignore[arg-type]
        assert found is None

    async def test_delete_nonexistent_template_does_not_error(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test that deleting a non-existent template doesn't raise an error."""
        await template_repository.delete("00000000-0000-0000-0000-000000000000")
        # No exception = pass


@pytest.mark.integration
class TestActivityTemplateRepositoryPitchOperations:
    """Test activity template pitch lifecycle operations."""

    async def test_pitches_saved_and_retrieved_in_order(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test that pitches are stored and retrieved ordered by pitch_number."""
        template = ActivityTemplate(
            name="Ordered Pitches Test",
            template_type="canyoning",
            user_id=TEST_USER_ID,
            pitches=[
                TemplatePitch(
                    template_id="11111111-1111-1111-1111-111111111111",
                    pitch_number=3,
                    height=30,
                ),
                TemplatePitch(
                    template_id="11111111-1111-1111-1111-111111111111",
                    pitch_number=1,
                    height=10,
                ),
                TemplatePitch(
                    template_id="11111111-1111-1111-1111-111111111111",
                    pitch_number=2,
                    height=20,
                ),
            ],
        )
        saved = await template_repository.save(template)

        found = await template_repository.find_by_id(saved.id)  # type: ignore[arg-type]

        assert found is not None
        assert len(found.pitches) == 3
        assert found.pitches[0].pitch_number == 1
        assert found.pitches[0].height == 10
        assert found.pitches[1].pitch_number == 2
        assert found.pitches[1].height == 20
        assert found.pitches[2].pitch_number == 3
        assert found.pitches[2].height == 30

    async def test_pitch_fields_fully_persisted(
        self,
        template_repository: SqlActivityTemplateRepository,
    ):
        """Test that all pitch fields are correctly persisted and retrieved."""
        template = ActivityTemplate(
            name="Full Pitch Test",
            template_type="canyoning",
            user_id=TEST_USER_ID,
            pitches=[
                TemplatePitch(
                    template_id="11111111-1111-1111-1111-111111111111",
                    pitch_number=1,
                    height=25,
                    anchor_location="TR",
                    anchor_type="double bolt",
                    did_rescue=True,
                    did_setup=False,
                ),
            ],
        )
        saved = await template_repository.save(template)

        found = await template_repository.find_by_id(saved.id)  # type: ignore[arg-type]

        assert found is not None
        pitch = found.pitches[0]
        assert pitch.height == 25
        assert pitch.anchor_location == "TR"
        assert pitch.anchor_type == "double bolt"
        assert pitch.did_rescue is True
        assert pitch.did_setup is False
        assert pitch.created_at is not None
        assert pitch.updated_at is not None
