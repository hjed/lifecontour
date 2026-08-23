"""Tag service for managing tag lifecycle and emitting events."""

from typing import Any

from core_shared.models.contacts.entities import Tag
from core_shared.models.contacts.value_objects import TagName
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_touch import touch_contacts_holding_tag
from app.core.contacts.models.events import TagDeleted, TagUpdated
from app.core.contacts.models.exceptions import DuplicateTagNameError, TagNotFoundError
from app.core.contacts.models.repositories import ContactEventPublisher, TagRepository
from app.core.contacts.services.tag_hierarchy_service import TagHierarchyService
from app.infrastructure.unit_of_work import savepoint, transactional


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

    @transactional
    async def create_tag(
        self,
        name: str,
        transaction: AsyncConnection,
        color: str | None = None,
        description: str | None = None,
        parent_id: int | None = None,
    ) -> Tag:
        """
        Create a tag (or return the existing one of the same name) as a
        committed unit of work.

        Tag names are unique. To stay safe under a concurrent duplicate-name
        race (e.g. two requests that both look up a tag by name, find nothing,
        and try to create it), the insert is guarded by a SAVEPOINT: if it
        violates the unique-name constraint, the SAVEPOINT rolls back just that
        failed insert (without poisoning the surrounding unit of work) and the
        already-existing tag is fetched and returned — a race-safe
        create-or-get.

        Args:
            name: Tag name.
            transaction: Request connection; the write commits before the response.
            color: Optional color as hex string.
            description: Optional description.
            parent_id: Optional parent tag ID. When provided, the parent must
                already exist.

        Raises:
            TagNotFoundError: ``parent_id`` was provided but no such tag exists.
        """
        if parent_id is not None:
            parent_tag = await self.tag_repo.find_by_id(parent_id)
            if not parent_tag:
                raise TagNotFoundError(parent_id)

        tag = Tag(
            name=TagName(name),
            color=color,
            description=description,
            parent_id=parent_id,
        )
        try:
            async with savepoint(transaction):
                return await self.tag_repo.save(tag)
        except DuplicateTagNameError:
            # Lost a create-or-get race: another writer already created this
            # name. The SAVEPOINT rolled the failed insert back, so the
            # connection is still usable — return the winner's tag.
            existing = await self.tag_repo.find_by_name(name)
            if existing is not None:
                return existing
            # No row found despite the unique violation (e.g. the other writer
            # rolled back). Surface the conflict rather than silently swallow it.
            raise

    @transactional
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
        # An explicit parent wins over set_parent_null. The "no change needed"
        # case is nested rather than flat so that supplying a parent_id equal to
        # the current parent does not fall through and clear it instead.
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

    @transactional
    async def delete_tag(self, tag_id: int, transaction: AsyncConnection) -> None:
        """
        Delete a tag cascade removing it from contacts, and publish TagDeleted event.
        """
        tag = await self.tag_repo.find_by_id(tag_id)
        if not tag:
            raise TagNotFoundError(tag_id)

        path_tags = await self.tag_hierarchy_service.get_tag_path(tag_id)
        path_str = _compute_path_string(path_tags, tag)

        # The assignment rows go with it via cascade, which no application code
        # sees — so the contacts losing the tag are marked as changed here,
        # before the rows naming them are gone.
        await touch_contacts_holding_tag(transaction, tag_id)

        await self.tag_repo.delete(tag_id)

        event = TagDeleted(
            tag_id=tag_id,
            tag_name=path_str,
            transaction=transaction,
        )
        await self.event_publisher.publish(event)

    @transactional
    async def merge_tags(
        self, source_id: int, target_id: int, transaction: AsyncConnection
    ) -> None:
        """
        Merge source tag into target tag.

        This will:
        1. Reassign all contacts from source to target (handling uniqueness conflicts).
        2. Delete the source tag.
        3. Publish TagDeleted event for the source tag.
        """
        if source_id == target_id:
            raise ValueError("Source and target tags must be different")

        source_tag = await self.tag_repo.find_by_id(source_id)
        target_tag = await self.tag_repo.find_by_id(target_id)

        if not source_tag:
            raise TagNotFoundError(source_id)
        if not target_tag:
            raise TagNotFoundError(target_id)

        # Prevent merging into descendant to avoid cycle
        current: Tag | None = target_tag
        while current and current.parent_id:
            if current.parent_id == source_id:
                raise ValueError("Cannot merge a tag into its own descendant")
            current = await self.tag_repo.find_by_id(current.parent_id)

        from sqlalchemy import text

        # 0. Every contact carrying the source tag ends up with a different tag
        #    set, so they are marked while the assignments still name them —
        #    which also takes their locks ahead of the rewrites below.
        await touch_contacts_holding_tag(transaction, source_id)

        # 1. First, delete contact_tags for source_id if the contact already has target_id
        delete_duplicates_query = text(
            """
            DELETE FROM contact_tags ct
            WHERE ct.tag_id = :source_id
            AND EXISTS (
                SELECT 1 FROM contact_tags ct2
                WHERE ct2.contact_id = ct.contact_id
                AND ct2.tag_id = :target_id
            )
            """
        )
        await transaction.execute(
            delete_duplicates_query, {"source_id": source_id, "target_id": target_id}
        )

        # 2. Update remaining contact_tags to point to target_id instead of source_id
        update_query = text(
            """
            UPDATE contact_tags
            SET tag_id = :target_id
            WHERE tag_id = :source_id
            """
        )
        await transaction.execute(
            update_query, {"source_id": source_id, "target_id": target_id}
        )

        # 3. Re-parent any child tags of source_id to target_id
        reparent_query = text(
            "UPDATE tags SET parent_id = :target_id WHERE parent_id = :source_id"
        )
        await transaction.execute(
            reparent_query, {"source_id": source_id, "target_id": target_id}
        )

        # 4. Delete the source tag itself (this will publish the event)
        await self.delete_tag(source_id, transaction)
