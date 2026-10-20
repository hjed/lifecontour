"""The tag path a Google contact group's display name becomes (#1821).

Inbound and the push both name a group's tag through ``group_naming``, so a
group whose name does not survive sanitising still matches its tag on the push.
"""

import pytest

from group_naming import group_tag_path, group_tag_segments


@pytest.mark.parametrize(
    ("display_name", "expected"),
    [
        ("Friends", "Friends"),
        ("Family Friends", "Family-Friends"),
        ("Kids & Co.", "Kids-&-Co"),
        ("  Work  ", "Work"),
        ("Family/Extended", "Family/Extended"),
        ("Family Friends/Close Ones", "Family-Friends/Close-Ones"),
        ("Family//Extended", "Family/Extended"),
        ("Family/!!!/Extended", "Family/Extended"),
        (f"Family/{'x' * 101}", "Family"),
        ("!!!", None),
        ("家族", None),
        ("", None),
    ],
)
def test_group_tag_path(display_name: str, expected: str | None) -> None:
    assert group_tag_path(display_name) == expected


def test_segments_are_the_hierarchy_inbound_builds() -> None:
    assert group_tag_segments("Family Friends/Close Ones") == [
        "Family-Friends",
        "Close-Ones",
    ]
