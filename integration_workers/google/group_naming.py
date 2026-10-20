"""
The local tag names a Google Contact Group's display name becomes.

Inbound sync turns a group into tags through these functions, and the push
matches tags back to groups through them, so a group whose name does not
survive sanitising ("Family Friends" → ``Family-Friends``) still finds its tag.
"""

import re

_MAX_SEGMENT_LENGTH = 100


def sanitize_tag_segment(name: str) -> str | None:
    """
    Sanitize one hierarchy segment to make it valid for TagName.

    TagName only allows alphanumeric, hyphens, underscores, and ampersands.
    The '/' character should be split before this function is called.
    """
    if not name or not name.strip():
        return None

    sanitized = re.sub(r"[^a-zA-Z0-9_&-]", "-", name.strip())
    sanitized = re.sub(r"-+", "-", sanitized)
    sanitized = sanitized.strip("-")

    if not sanitized or len(sanitized) > _MAX_SEGMENT_LENGTH:
        return None

    return sanitized


def group_tag_segments(display_name: str) -> list[str]:
    """The tag names a group becomes, root first: '/' splits it into a hierarchy.

    Segments that sanitise to nothing are dropped, so their neighbours join up.
    """
    segments = (sanitize_tag_segment(segment) for segment in display_name.split("/"))
    return [segment for segment in segments if segment]


def group_tag_path(display_name: str) -> str | None:
    """The local tag path a group's display name becomes, or None if no tag."""
    return "/".join(group_tag_segments(display_name)) or None
