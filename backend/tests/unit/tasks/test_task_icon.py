"""Unit tests for the fixed task icon set.

Lists and tasks may carry an optional icon "chosen from a fixed set". The set is
the published contract: the API and MCP accept only its keys, and the web app
maps each key to an icon component. These tests pin the shape of the keys
rather than the exact membership, which is expected to grow.
"""

import re

import pytest
from core_shared.models import tasks
from core_shared.models.tasks import TaskIcon

_KEBAB_CASE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# Every key ever published. Stored rows hold these strings and are read back
# through ``TaskIcon``, so a key may never leave the enum or change its spelling.
# Append a new icon here when it is added; never edit or delete a line.
_PUBLISHED_KEYS = frozenset(
    {
        "list",
        "clipboard-list",
        "bookmark",
        "star",
        "heart",
        "lightbulb",
        "calendar",
        "house",
        "briefcase",
        "shopping-cart",
        "gift",
        "package",
        "wallet",
        "phone",
        "mail",
        "users",
        "baby",
        "paw-print",
        "party-popper",
        "trophy",
        "plane",
        "luggage",
        "car",
        "bike",
        "map",
        "tent",
        "mountain",
        "leaf",
        "sun",
        "dumbbell",
        "pill",
        "utensils",
        "coffee",
        "shirt",
        "wrench",
        "hammer",
        "book-open",
        "graduation-cap",
        "music",
        "camera",
    }
)


@pytest.mark.unit
class TestTaskIconKeys:
    """Every icon key is a stable, kebab-case string."""

    def test_the_set_is_not_empty(self) -> None:
        assert len(TaskIcon) > 0

    @pytest.mark.parametrize("icon", list(TaskIcon), ids=lambda icon: icon.value)
    def test_every_key_is_lowercase_kebab_case(self, icon: TaskIcon) -> None:
        assert _KEBAB_CASE.fullmatch(icon.value), icon.value

    def test_keys_are_unique(self) -> None:
        values = [icon.value for icon in TaskIcon]

        assert len(values) == len(set(values))

    def test_a_key_round_trips_through_its_value(self) -> None:
        assert TaskIcon("plane") is TaskIcon.PLANE
        assert str(TaskIcon.PLANE) == "plane"

    def test_an_unknown_key_is_refused(self) -> None:
        with pytest.raises(ValueError):
            TaskIcon("not-an-icon")

    def test_flag_is_not_an_icon(self) -> None:
        """The flag is a separate on/off marker on every task, not an icon."""
        assert "flag" not in {icon.value for icon in TaskIcon}


@pytest.mark.unit
class TestTaskIconSetIsAddOnly:
    """The database holds no CHECK on icon values, so this test is the guard.

    A removed or renamed key would leave stored rows that no longer load through
    ``TaskIcon``. New keys are allowed; published ones must all remain.
    """

    def test_every_published_key_is_still_an_icon(self) -> None:
        current = {icon.value for icon in TaskIcon}

        missing = _PUBLISHED_KEYS - current
        assert not missing, (
            f"icon keys {sorted(missing)} were removed or renamed; stored rows "
            "using them could no longer be read. Icon keys are add-only."
        )

    def test_every_icon_is_published(self) -> None:
        """A new key must be appended to ``_PUBLISHED_KEYS`` too, so the
        add-only guard covers it from the moment it exists."""
        current = {icon.value for icon in TaskIcon}

        unlisted = current - _PUBLISHED_KEYS
        assert not unlisted, (
            f"add {sorted(unlisted)} to _PUBLISHED_KEYS so they are protected"
        )


@pytest.mark.unit
class TestTaskIconExport:
    """The set is part of the tasks domain's public surface."""

    def test_exported_from_the_tasks_package(self) -> None:
        assert "TaskIcon" in tasks.__all__
