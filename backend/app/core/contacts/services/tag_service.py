"""Tag service for managing tag lifecycle and emitting events."""

from typing import Any

from core_shared.models.contacts.entities import Tag
from core_shared.models.contacts.value_objects import TagName
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.events import TagDeleted, TagUpdated
from app.core.contacts.models.exceptions import TagNotFoundError
from app.core.contacts.models.repositories import ContactEventPublisher, TagRepository
from app.core.contacts.services.tag_hierarchy_service import TagHierarchyService


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

        # Calculate old path for sync events
        old_path_tags = await self.tag_hierarchy_service.get_tag_path(tag_id)
        old_path_str = (
            "/".join([str(t.name) for t in old_path_tags])
            if old_path_tags
            else str(tag.name)
        )

        changed_fields: dict[str, Any] = {}

        if name is not None and str(tag.name) != name:
            await self.tag_hierarchy_service.validate_tag_name_uniqueness(
                name, transaction, exclude_tag_id=tag_id
            )
            old_name = str(tag.name)
            tag.name = TagName(name)
            changed_fields["name"] = (old_name, name)

        if color is not None:
            old_color = str(tag.color) if tag.color else None
            if old_color != color:
                tag.color = color
                changed_fields["color"] = (old_color, color)

        if description is not None and tag.description != description:
            old_desc = tag.description
            tag.description = description
            changed_fields["description"] = (old_desc, description)

        if parent_id is not None:
            if tag.parent_id != parent_id:
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

        tag = await self.tag_repo.save(tag)

        # Calculate new path for sync events
        new_path_tags = await self.tag_hierarchy_service.get_tag_path(tag_id)
        new_path_str = (
            "/".join([str(t.name) for t in new_path_tags])
            if new_path_tags
            else str(tag.name)
        )

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

    async def delete_tag(self, tag_id: int, transaction: AsyncConnection) -> None:
        """
        Delete a tag cascade removing it from contacts, and publish TagDeleted event.
        """
        tag = await self.tag_repo.find_by_id(tag_id)
        if not tag:
            raise TagNotFoundError(tag_id)

        # Calculate old path for sync events
        path_tags = await self.tag_hierarchy_service.get_tag_path(tag_id)
        path_str = (
            "/".join([str(t.name) for t in path_tags]) if path_tags else str(tag.name)
        )

        await self.tag_repo.delete(tag_id)

        event = TagDeleted(
            tag_id=tag_id,
            tag_name=path_str,
            transaction=transaction,
        )
        await self.event_publisher.publish(event)
