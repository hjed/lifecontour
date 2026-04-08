"""Tag service for managing tag lifecycle and emitting events."""

from typing import Any

from core_shared.models.contacts.entities import Tag
from core_shared.models.contacts.value_objects import TagName
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.events import TagDeleted, TagUpdated
from app.core.contacts.models.exceptions import TagNotFoundError
from app.core.contacts.models.repositories import ContactEventPublisher, TagRepository
from app.core.contacts.services.tag_hierarchy_service import TagHierarchyService


def _compute_path_string(path_tags: list[Tag], fallback_tag: Tag) -> str:
    """Build a slash-delimited path string from a list of ancestor tags."""
    if path_tags:
        return "/".join(str(t.name) for t in path_tags)
    return str(fallback_tag.name)


class TagService:
    """
    Service for tag mutations and event publishing.

    Operations on tags that change their data or life cycle use this service
    so DomainEvents (like TagUpdated and TagDeleted) are correctly emitted for
    downstream integrations (such as Google Contacts sync).
    """

    def __init__(
        self,
        tag_repo: TagRepository,
        tag_hierarchy_service: TagHierarchyService,
        event_publisher: ContactEventPublisher,
    ):
        self.tag_repo = tag_repo
        self.tag_hierarchy_service = tag_hierarchy_service
        self.event_publisher = event_publisher

    async def update_tag(
        self,
        tag_id: int,
        transaction: AsyncConnection,
        name: str | None = None,
        color: str | None = None,
        description: str | None = None,
        parent_id: int | None = None,
        set_parent_null: bool = False,
    ) -> Tag:
        """
        Update a tag and publish a TagUpdated event.

        Args:
            tag_id: ID of the tag to update
            transaction: Active database transaction
            name: New name (if updating)
            color: New color as hex string (if updating)
            description: New description (if updating)
            parent_id: New parent tag ID (if updating)
            set_parent_null: Set to True to move the tag to the root (clear parent_id)
        """
        tag = await self.tag_repo.find_by_id(tag_id)
        if not tag:
            raise TagNotFoundError(tag_id)

        old_path_tags = await self.tag_hierarchy_service.get_tag_path(tag_id)
        old_path_str = _compute_path_string(old_path_tags, tag)

        changed_fields: dict[str, Any] = {}

        if name is not None:
            await self._apply_name_change(
                tag, tag_id, name, transaction, changed_fields
            )

        if color is not None:
            self._apply_color_change(tag, color, changed_fields)

        if description is not None and tag.description != description:
            changed_fields["description"] = (tag.description, description)
            tag.description = description

        await self._apply_parent_change(
            tag, tag_id, parent_id, set_parent_null, transaction, changed_fields
        )

        if changed_fields:
            # Re-trigger domain validation
            tag.__post_init__()
            tag = await self.tag_repo.save(tag)

        new_path_tags = await self.tag_hierarchy_service.get_tag_path(tag_id)
        new_path_str = _compute_path_string(new_path_tags, tag)

        if old_path_str != new_path_str:
            changed_fields["full_path"] = (old_path_str, new_path_str)

        if changed_fields:
            event = TagUpdated(
                tag_id=tag_id,
                tag_name=new_path_str,
                changed_fields=changed_fields,
                transaction=transaction,
            )
            await self.event_publisher.publish(event)

        return tag

    async def _apply_name_change(
        self,
        tag: Tag,
        tag_id: int,
        name: str,
        transaction: AsyncConnection,
        changed_fields: dict[str, Any],
    ) -> None:
        """Validate and apply a tag name change."""
        if str(tag.name) == name:
            return
        await self.tag_hierarchy_service.validate_tag_name_uniqueness(
            name, transaction, exclude_tag_id=tag_id
        )
        old_name = str(tag.name)
        tag.name = TagName(name)
        changed_fields["name"] = (old_name, name)

    @staticmethod
    def _apply_color_change(
        tag: Tag,
        color: str,
        changed_fields: dict[str, Any],
    ) -> None:
        """Apply a tag color change if different."""
        old_color = str(tag.color) if tag.color else None
        if old_color != color:
            tag.color = color
            changed_fields["color"] = (old_color, color)

    async def _apply_parent_change(
        self,
        tag: Tag,
        tag_id: int,
        parent_id: int | None,
        set_parent_null: bool,
        transaction: AsyncConnection,
        changed_fields: dict[str, Any],
    ) -> None:
        """Validate and apply a parent_id change, or clear it if requested."""
        if parent_id is not None and tag.parent_id != parent_id:
            await self.tag_hierarchy_service.validate_parent_child_relationship(
                parent_id=parent_id, child_id=tag_id, transaction=transaction
            )
            parent_tag = await self.tag_repo.find_by_id(parent_id)
            if not parent_tag:
                raise TagNotFoundError(parent_id)
            old_parent = tag.parent_id
            tag.parent_id = parent_id
            changed_fields["parent_id"] = (old_parent, parent_id)
        elif set_parent_null and tag.parent_id is not None:
            old_parent = tag.parent_id
            tag.parent_id = None
            changed_fields["parent_id"] = (old_parent, None)

    async def delete_tag(self, tag_id: int, transaction: AsyncConnection) -> None:
        """
        Delete a tag cascade removing it from contacts, and publish TagDeleted event.
        """
        tag = await self.tag_repo.find_by_id(tag_id)
        if not tag:
            raise TagNotFoundError(tag_id)

        path_tags = await self.tag_hierarchy_service.get_tag_path(tag_id)
        path_str = _compute_path_string(path_tags, tag)

        await self.tag_repo.delete(tag_id)

        event = TagDeleted(
            tag_id=tag_id,
            tag_name=path_str,
            transaction=transaction,
        )
        await self.event_publisher.publish(event)
