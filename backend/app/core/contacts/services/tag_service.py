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


def _relative_paths(root_id: int, descendants: list[Tag]) -> list[tuple[int, str]]:
    """Each descendant's id and its path below ``root_id`` (``Child/Grandchild``).

    ``descendants`` may come in any order (the repository sorts by name, not
    depth), so each path is walked up through the others rather than built
    from parents seen earlier.
    """
    by_id = {tag.id: tag for tag in descendants if tag.id is not None}
    paths: list[tuple[int, str]] = []
    for tag_id, tag in by_id.items():
        segments = [str(tag.name)]
        parent_id = tag.parent_id
        while parent_id is not None and parent_id != root_id:
            parent = by_id[parent_id]
            segments.append(str(parent.name))
            parent_id = parent.parent_id
        paths.append((tag_id, "/".join(reversed(segments))))
    return paths


def _join_path(root: str | None, relative: str) -> str:
    """A descendant's full path under ``root``, or ``relative`` itself at the root."""
    return f"{root}/{relative}" if root else relative


class TagService:
    """
    Service for tag mutations and event publishing.

    Operations on tags that change their data or life cycle use this service
    so DomainEvents (like TagUpdated and TagDeleted) are correctly emitted for
    downstream integrations (such as Google Contacts sync).

    Every operation acts for one user (``user_id``) and sees only their tags:
    another user's tag, or a parent or merge target of theirs, is not found.
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
        *,
        user_id: str,
    ) -> Tag:
        """
        Create a tag owned by ``user_id`` (or return the existing one of the same
        name) as a committed unit of work.

        Tag names are unique per owner. To stay safe under a concurrent duplicate-name
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
            parent_tag = await self.tag_repo.find_by_id(parent_id, user_id=user_id)
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
                return await self.tag_repo.save(tag, user_id=user_id)
        except DuplicateTagNameError:
            # Lost a create-or-get race: another writer already created this
            # name. The SAVEPOINT rolled the failed insert back, so the
            # connection is still usable — return the winner's tag.
            existing = await self.tag_repo.find_by_name(name, user_id=user_id)
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
        *,
        user_id: str,
    ) -> Tag:
        """
        Update a tag and publish a TagUpdated event.

        A rename or move changes every descendant's path too, so each descendant
        gets a TagUpdated of its own carrying just that ``full_path`` change.

        Args:
            tag_id: ID of the tag to update
            transaction: Active database transaction
            name: New name (if updating)
            color: New color as hex string (if updating)
            description: New description (if updating)
            parent_id: New parent tag ID (if updating)
            set_parent_null: Set to True to move the tag to the root (clear parent_id)
        """
        tag = await self.tag_repo.find_by_id(tag_id, user_id=user_id)
        if not tag:
            raise TagNotFoundError(tag_id)

        old_path_tags = await self.tag_hierarchy_service.get_tag_path(
            tag_id, user_id=user_id
        )
        old_path_str = _compute_path_string(old_path_tags, tag)

        changed_fields: dict[str, Any] = {}

        if name is not None:
            await self._apply_name_change(
                tag, tag_id, name, transaction, changed_fields, user_id=user_id
            )

        if color is not None:
            self._apply_color_change(tag, color, changed_fields)

        if description is not None and tag.description != description:
            changed_fields["description"] = (tag.description, description)
            tag.description = description

        await self._apply_parent_change(
            tag,
            tag_id,
            parent_id,
            set_parent_null,
            transaction,
            changed_fields,
            user_id=user_id,
        )

        if changed_fields:
            # Re-trigger domain validation
            tag.__post_init__()
            tag = await self.tag_repo.save(tag, user_id=user_id)

        new_path_tags = await self.tag_hierarchy_service.get_tag_path(
            tag_id, user_id=user_id
        )
        new_path_str = _compute_path_string(new_path_tags, tag)

        if old_path_str != new_path_str:
            changed_fields["full_path"] = (old_path_str, new_path_str)

        if changed_fields:
            event = TagUpdated(
                tag_id=tag_id,
                tag_name=new_path_str,
                changed_fields=changed_fields,
                transaction=transaction,
                user_id=user_id,
            )
            await self.event_publisher.publish(event)

        if old_path_str != new_path_str:
            await self._publish_descendant_path_changes(
                await self._relative_descendant_paths(tag_id, user_id=user_id),
                old_root=old_path_str,
                new_root=new_path_str,
                transaction=transaction,
                user_id=user_id,
            )

        return tag

    async def _relative_descendant_paths(
        self, tag_id: int, *, user_id: str
    ) -> list[tuple[int, str]]:
        """The tag's descendants, as ids and paths relative to it."""
        descendants = await self.tag_hierarchy_service.get_all_descendants_bulk(
            [tag_id], user_id=user_id
        )
        return _relative_paths(tag_id, descendants)

    async def _publish_descendant_path_changes(
        self,
        descendants: list[tuple[int, str]],
        *,
        old_root: str,
        new_root: str | None,
        transaction: AsyncConnection,
        user_id: str,
    ) -> None:
        """Publish a ``full_path`` TagUpdated for each descendant that moved.

        No other event says a descendant's path changed, and the Google worker
        renames a tag's contact group by its old path (#1836). ``new_root`` is
        None when the descendants became roots, as when their ancestor is deleted.
        """
        for descendant_id, relative in descendants:
            old_path = _join_path(old_root, relative)
            new_path = _join_path(new_root, relative)
            if old_path == new_path:
                continue
            await self.event_publisher.publish(
                TagUpdated(
                    tag_id=descendant_id,
                    tag_name=new_path,
                    changed_fields={"full_path": (old_path, new_path)},
                    transaction=transaction,
                    user_id=user_id,
                )
            )

    async def _apply_name_change(
        self,
        tag: Tag,
        tag_id: int,
        name: str,
        transaction: AsyncConnection,
        changed_fields: dict[str, Any],
        *,
        user_id: str,
    ) -> None:
        """Validate and apply a tag name change."""
        if str(tag.name) == name:
            return
        await self.tag_hierarchy_service.validate_tag_name_uniqueness(
            name, transaction, exclude_tag_id=tag_id, user_id=user_id
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
        *,
        user_id: str,
    ) -> None:
        """Validate and apply a parent_id change, or clear it if requested.

        The parent must be one of ``user_id``'s tags; another user's is not found.
        """
        # An explicit parent wins over set_parent_null. The "no change needed"
        # case is nested rather than flat so that supplying a parent_id equal to
        # the current parent does not fall through and clear it instead.
        if parent_id is not None:
            if tag.parent_id != parent_id:
                await self.tag_hierarchy_service.validate_parent_child_relationship(
                    parent_id=parent_id,
                    child_id=tag_id,
                    transaction=transaction,
                    user_id=user_id,
                )
                parent_tag = await self.tag_repo.find_by_id(parent_id, user_id=user_id)
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
    async def delete_tag(
        self, tag_id: int, transaction: AsyncConnection, *, user_id: str
    ) -> None:
        """
        Delete a tag cascade removing it from contacts, and publish TagDeleted event.

        Its children become roots (``ON DELETE SET NULL``), so each descendant
        also gets a TagUpdated for its shortened ``full_path``.
        """
        tag = await self.tag_repo.find_by_id(tag_id, user_id=user_id)
        if not tag:
            raise TagNotFoundError(tag_id)

        path_tags = await self.tag_hierarchy_service.get_tag_path(
            tag_id, user_id=user_id
        )
        path_str = _compute_path_string(path_tags, tag)
        # Read while they are still descendants: the delete cuts them loose.
        descendants = await self._relative_descendant_paths(tag_id, user_id=user_id)

        # The assignment rows go with it via cascade, which no application code
        # sees — so the contacts losing the tag are marked as changed here,
        # before the rows naming them are gone.
        await touch_contacts_holding_tag(transaction, tag_id)

        # A tag gone between the lookup and the write raises, so the unit of
        # work rolls back instead of committing an event for no deletion.
        if not await self.tag_repo.delete(tag_id, user_id=user_id):
            raise TagNotFoundError(tag_id)

        event = TagDeleted(
            tag_id=tag_id,
            tag_name=path_str,
            transaction=transaction,
            user_id=user_id,
        )
        await self.event_publisher.publish(event)
        await self._publish_descendant_path_changes(
            descendants,
            old_root=path_str,
            new_root=None,
            transaction=transaction,
            user_id=user_id,
        )

    @transactional
    async def merge_tags(
        self,
        source_id: int,
        target_id: int,
        transaction: AsyncConnection,
        *,
        user_id: str,
    ) -> None:
        """
        Merge source tag into target tag.

        This will:
        1. Reassign all contacts from source to target (handling uniqueness conflicts).
        2. Delete the source tag.
        3. Publish TagDeleted event for the source tag.
        4. Publish a TagUpdated for each of the source's descendants, whose
           paths now run through the target.
        """
        if source_id == target_id:
            raise ValueError("Source and target tags must be different")

        source_tag = await self.tag_repo.find_by_id(source_id, user_id=user_id)
        target_tag = await self.tag_repo.find_by_id(target_id, user_id=user_id)

        if not source_tag:
            raise TagNotFoundError(source_id)
        if not target_tag:
            raise TagNotFoundError(target_id)

        # Prevent merging into descendant to avoid cycle
        current: Tag | None = target_tag
        while current and current.parent_id:
            if current.parent_id == source_id:
                raise ValueError("Cannot merge a tag into its own descendant")
            current = await self.tag_repo.find_by_id(current.parent_id, user_id=user_id)

        # 0. Every contact carrying the source tag ends up with a different tag
        #    set, so they are marked while the assignments still name them —
        #    which also takes their locks ahead of the rewrites below.
        await touch_contacts_holding_tag(transaction, source_id)

        # Read before the merge re-parents the source's children onto the
        # target. The target cannot sit under the source (checked above), so
        # its path is unchanged by the merge.
        descendants = await self._relative_descendant_paths(source_id, user_id=user_id)
        source_path = _compute_path_string(
            await self.tag_hierarchy_service.get_tag_path(source_id, user_id=user_id),
            source_tag,
        )
        target_path = _compute_path_string(
            await self.tag_hierarchy_service.get_tag_path(target_id, user_id=user_id),
            target_tag,
        )

        if not await self.tag_repo.merge_into(source_id, target_id, user_id=user_id):
            raise TagNotFoundError(source_id)

        # Delete the source tag itself (this will publish the event). Its
        # children have moved already, so this publishes no path changes.
        await self.delete_tag(source_id, transaction, user_id=user_id)
        await self._publish_descendant_path_changes(
            descendants,
            old_root=source_path,
            new_root=target_path,
            transaction=transaction,
            user_id=user_id,
        )
