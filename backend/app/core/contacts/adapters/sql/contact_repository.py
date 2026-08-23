"""SQL implementation of ContactRepository."""

from datetime import datetime

from core_shared.models.contacts.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    ContactRelationship,
    ContactSummary,
    ImportantDate,
    MethodType,
    RelationshipType,
    SummaryStatus,
    Tag,
)
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.contacts.value_objects import TagName
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
    CustomDateTypeNotFoundError,
    DuplicateBirthdayError,
    DuplicateEmailError,
    ImportantDateNotFoundError,
    PrimaryAddressConflictError,
    PrimaryMethodConflictError,
)
from app.core.contacts.models.repositories import ContactRepository


class SqlContactRepository(ContactRepository):
    """SQL implementation of ContactRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        self.conn = connection

    def _normalize_contact_method_value(
        self, method_type: MethodType, value: str
    ) -> str:
        """Normalize stored method values before rehydrating domain entities."""
        if method_type == MethodType.EMAIL:
            return value.strip()
        return value

    async def contact_exists(self, contact_id: int) -> bool:
        """Return whether a contact with the given ID exists."""
        result = await self.conn.execute(
            text("SELECT 1 FROM contacts WHERE id = :contact_id"),
            {"contact_id": contact_id},
        )
        return result.first() is not None

    async def find_by_id(self, contact_id: int) -> Contact | None:
        """Find a contact by ID with all related data."""
        # Get contact basic info
        contact_query = text(
            """
            SELECT id, first_name, last_name, middle_name, nick_name, company, job_title, photo_url, is_favourite, created_at, updated_at
            FROM contacts WHERE id = :contact_id
        """
        )
        result = await self.conn.execute(contact_query, {"contact_id": contact_id})
        contact_row = result.fetchone()

        if not contact_row:
            return None

        # Create contact entity
        contact = Contact(
            id=contact_row.id,
            first_name=contact_row.first_name,
            last_name=contact_row.last_name,
            middle_name=contact_row.middle_name,
            nick_name=contact_row.nick_name,
            company=contact_row.company,
            job_title=contact_row.job_title,
            photo_url=contact_row.photo_url,
            is_favourite=contact_row.is_favourite,
            created_at=contact_row.created_at,
            updated_at=contact_row.updated_at,
            methods=[],
            addresses=[],
            notes=[],
            tags=[],
            relationships=[],
            important_dates=[],
        )

        # Load contact methods
        methods_query = text(
            """
            SELECT id, method_type, value, label, is_primary, created_at, updated_at
            FROM contact_methods WHERE contact_id = :contact_id
            ORDER BY is_primary DESC, created_at ASC
        """
        )
        methods_result = await self.conn.execute(
            methods_query, {"contact_id": contact_id}
        )
        for method_row in methods_result.fetchall():
            method_type = MethodType(method_row.method_type)
            method = ContactMethod(
                id=method_row.id,
                contact_id=contact_id,
                method_type=method_type,
                value=self._normalize_contact_method_value(
                    method_type, method_row.value
                ),
                label=method_row.label,
                is_primary=method_row.is_primary,
                created_at=method_row.created_at,
                updated_at=method_row.updated_at,
            )
            assert contact.methods is not None
            contact.methods.append(method)

        # Load contact addresses
        addresses_query = text(
            """
            SELECT id, label, street_line_1, street_line_2, locality, region,
                   postal_code, country_code, is_primary, created_at, updated_at
            FROM contact_addresses WHERE contact_id = :contact_id
            ORDER BY is_primary DESC, created_at ASC
        """
        )
        addresses_result = await self.conn.execute(
            addresses_query, {"contact_id": contact_id}
        )
        for address_row in addresses_result.fetchall():
            address = ContactAddress(
                id=address_row.id,
                contact_id=contact_id,
                label=address_row.label,
                street_line_1=address_row.street_line_1,
                street_line_2=address_row.street_line_2,
                locality=address_row.locality,
                region=address_row.region,
                postal_code=address_row.postal_code,
                country_code=address_row.country_code,
                is_primary=address_row.is_primary,
                created_at=address_row.created_at,
                updated_at=address_row.updated_at,
            )
            assert contact.addresses is not None
            contact.addresses.append(address)

        # Load contact notes
        notes_query = text(
            """
            SELECT id, content, created_at, updated_at
            FROM contact_notes WHERE contact_id = :contact_id
            ORDER BY created_at DESC
        """
        )
        notes_result = await self.conn.execute(notes_query, {"contact_id": contact_id})
        for note_row in notes_result.fetchall():
            note = ContactNote(
                id=note_row.id,
                contact_id=contact_id,
                content=note_row.content,
                created_at=note_row.created_at,
                updated_at=note_row.updated_at,
            )
            assert contact.notes is not None
            contact.notes.append(note)

        # Load contact tags
        tags_query = text(
            """
            SELECT t.id, t.name, t.parent_id, t.color, t.description, t.created_at, t.updated_at
            FROM tags t
            JOIN contact_tags ct ON t.id = ct.tag_id
            WHERE ct.contact_id = :contact_id
            ORDER BY t.name
        """
        )
        tags_result = await self.conn.execute(tags_query, {"contact_id": contact_id})
        for tag_row in tags_result.fetchall():
            tag = Tag(
                id=tag_row.id,
                name=TagName(tag_row.name),
                parent_id=tag_row.parent_id,
                color=tag_row.color,
                description=tag_row.description,
                created_at=tag_row.created_at,
                updated_at=tag_row.updated_at,
            )
            assert contact.tags is not None
            contact.tags.append(tag)

        # Load contact relationships
        relationships_query = text(
            """
            SELECT
                cr.id,
                cr.from_contact_id,
                cr.to_contact_id,
                cr.relationship_type,
                cr.to_user,
                cr.created_at,
                cr.updated_at,
                c_from.first_name as from_first,
                c_from.last_name as from_last,
                c_to.first_name as to_first,
                c_to.last_name as to_last
            FROM contact_relationships cr
            LEFT JOIN contacts c_from ON cr.from_contact_id = c_from.id
            LEFT JOIN contacts c_to ON cr.to_contact_id = c_to.id
            WHERE cr.from_contact_id = :contact_id OR cr.to_contact_id = :contact_id
            ORDER BY cr.created_at DESC
        """
        )
        relationships_result = await self.conn.execute(
            relationships_query, {"contact_id": contact_id}
        )
        for rel_row in relationships_result.fetchall():
            from_name = None
            if rel_row.from_first:
                from_name = f"{rel_row.from_first} {rel_row.from_last or ''}".strip()

            to_name = None
            if rel_row.to_first:
                to_name = f"{rel_row.to_first} {rel_row.to_last or ''}".strip()

            relationship = ContactRelationship(
                id=rel_row.id,
                from_contact_id=rel_row.from_contact_id,
                to_contact_id=rel_row.to_contact_id,
                relationship_type=RelationshipType(rel_row.relationship_type),
                to_user=rel_row.to_user,
                from_contact_name=from_name,
                to_contact_name=to_name,
                created_at=rel_row.created_at,
                updated_at=rel_row.updated_at,
            )
            assert contact.relationships is not None
            contact.relationships.append(relationship)

        # Load important dates
        dates_query = text(
            """
            SELECT d.id, d.contact_id, d.date_type, d.precision, d.year, d.month, d.day,
                   d.custom_date_type_id, cdt.name as custom_date_type_name,
                   d.created_at, d.updated_at
            FROM contact_important_dates d
            LEFT JOIN custom_date_types cdt ON d.custom_date_type_id = cdt.id
            WHERE d.contact_id = :contact_id
            ORDER BY d.created_at ASC
        """
        )
        dates_result = await self.conn.execute(dates_query, {"contact_id": contact_id})
        for date_row in dates_result.fetchall():
            important_date = ImportantDate(
                id=date_row.id,
                contact_id=date_row.contact_id,
                date_type=ImportantDateType(date_row.date_type),
                precision=DatePrecision(date_row.precision),
                year=date_row.year,
                month=date_row.month,
                day=date_row.day,
                custom_date_type_id=date_row.custom_date_type_id,
                custom_date_type_name=date_row.custom_date_type_name,
                created_at=date_row.created_at,
                updated_at=date_row.updated_at,
            )
            assert contact.important_dates is not None
            contact.important_dates.append(important_date)

        # Load summary (optional one-to-one)
        summary_query = text(
            """
            SELECT id, contact_id, summary_text, follow_up_suggestions, status,
                   is_disabled, is_user_override, user_override_text,
                   generated_at, created_at, updated_at
            FROM contact_summaries
            WHERE contact_id = :contact_id
        """
        )
        summary_result = await self.conn.execute(
            summary_query, {"contact_id": contact_id}
        )
        summary_row = summary_result.fetchone()
        if summary_row:
            suggestions = summary_row.follow_up_suggestions
            if isinstance(suggestions, str):
                import json

                suggestions = json.loads(suggestions)
            if suggestions is None:
                suggestions = []
            contact.summary = ContactSummary(
                id=summary_row.id,
                contact_id=summary_row.contact_id,
                summary_text=summary_row.summary_text,
                follow_up_suggestions=suggestions,
                status=SummaryStatus(summary_row.status),
                is_disabled=summary_row.is_disabled,
                is_user_override=summary_row.is_user_override,
                user_override_text=summary_row.user_override_text,
                generated_at=summary_row.generated_at,
                created_at=summary_row.created_at,
                updated_at=summary_row.updated_at,
            )

        return contact

    async def find_names_by_ids(
        self, contact_ids: list[int]
    ) -> dict[int, tuple[str | None, str | None, str | None]]:
        """Fetch (first_name, last_name, photo_url) for multiple contacts in a single query."""
        if not contact_ids:
            return {}

        query = text(
            """
            SELECT id, first_name, last_name, photo_url
            FROM contacts
            WHERE id = ANY(:ids)
        """
        )
        result = await self.conn.execute(query, {"ids": contact_ids})
        return {
            row.id: (row.first_name, row.last_name, row.photo_url)
            for row in result.fetchall()
        }

    async def find_by_email(self, email: str) -> Contact | None:
        """Find a contact by email address."""
        normalized_email = email.strip().lower()
        if not normalized_email:
            return None

        query = text(
            """
            SELECT DISTINCT c.id FROM contacts c
            JOIN contact_methods cm ON c.id = cm.contact_id
            WHERE cm.method_type = :method_type
              AND LOWER(BTRIM(cm.value)) = :normalized_email
        """
        )
        result = await self.conn.execute(
            query,
            {
                "method_type": MethodType.EMAIL.value,
                "normalized_email": normalized_email,
            },
        )
        row = result.fetchone()

        if row:
            return await self.find_by_id(row.id)
        return None

    async def find_by_external_reference(
        self, external_system: str, external_entity_id: str
    ) -> Contact | None:
        """Find a contact by external link, read from the canonical store.

        Resolves the ``(integration_source, external_id)`` link from
        ``sync_metadata`` — the single source of truth for integration links —
        rather than ``external_references``.
        """
        query = text(
            """
            SELECT DISTINCT c.id FROM contacts c
            JOIN sync_metadata sm ON c.id = sm.internal_id
            WHERE sm.internal_entity_type = 'contact'
            AND sm.integration_source = :external_system
            AND sm.external_id = :external_entity_id
        """
        )
        result = await self.conn.execute(
            query,
            {
                "external_system": external_system,
                "external_entity_id": external_entity_id,
            },
        )
        row = result.fetchone()

        if row:
            return await self.find_by_id(row.id)
        return None

    async def get_external_references(self, contact_id: int) -> list[dict[str, str]]:
        """Get all external links for a contact from the canonical store.

        Reads ``sync_metadata`` (the consolidated link store) and maps its
        columns onto the legacy external-reference shape consumed by
        ``build_contact_external_links``.
        """
        query = text(
            """
            SELECT integration_source AS external_system,
                   external_id AS external_entity_id,
                   external_entity_type
            FROM sync_metadata
            WHERE internal_entity_type = 'contact' AND internal_id = :contact_id
            """
        )
        result = await self.conn.execute(query, {"contact_id": contact_id})
        return [
            {
                "external_system": row.external_system,
                "external_entity_id": row.external_entity_id,
                "external_entity_type": row.external_entity_type,
            }
            for row in result.fetchall()
        ]

    async def search(self, query: str, limit: int = 50) -> list[Contact]:
        """Search contacts by name, email, or notes."""
        search_query = text(
            """
            SELECT DISTINCT c.id,
                   ts_rank(to_tsvector('english',
                       COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')
                   ), plainto_tsquery('english', :query)) as rank
            FROM contacts c
            LEFT JOIN contact_methods cm ON c.id = cm.contact_id
            LEFT JOIN contact_notes cn ON c.id = cn.contact_id
            WHERE to_tsvector('english',
                COALESCE(c.first_name, '') || ' ' ||
                COALESCE(c.last_name, '') || ' ' ||
                COALESCE(c.middle_name, '') || ' ' ||
                COALESCE(c.nick_name, '') || ' ' ||
                COALESCE(cm.value, '') || ' ' ||
                COALESCE(cn.content, '')
            ) @@ plainto_tsquery('english', :query)
            ORDER BY rank DESC
            LIMIT :limit
        """
        )
        result = await self.conn.execute(search_query, {"query": query, "limit": limit})
        contact_ids = [row.id for row in result.fetchall()]

        contacts = []
        for contact_id in contact_ids:
            contact = await self.find_by_id(contact_id)
            if contact:
                contacts.append(contact)
        return contacts

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[Contact]:
        """Get all contacts with pagination."""
        query = text(
            """
            SELECT id FROM contacts
            ORDER BY first_name, last_name
            LIMIT :limit OFFSET :offset
        """
        )
        result = await self.conn.execute(query, {"limit": limit, "offset": offset})
        contact_ids = [row.id for row in result.fetchall()]

        contacts = []
        for contact_id in contact_ids:
            contact = await self.find_by_id(contact_id)
            if contact:
                contacts.append(contact)
        return contacts

    async def get_count(self) -> int:
        """Get total count of contacts."""
        query = text("SELECT COUNT(*) FROM contacts")
        result = await self.conn.execute(query)
        row = result.fetchone()
        return row[0] if row else 0

    async def save(self, contact: Contact) -> Contact:
        """Save a contact (insert or update)."""
        try:
            if contact.id is None:
                # Insert new contact
                query = text(
                    """
                    INSERT INTO contacts (first_name, last_name, middle_name, nick_name, company, job_title, photo_url, is_favourite)
                    VALUES (:first_name, :last_name, :middle_name, :nick_name, :company, :job_title, :photo_url, :is_favourite)
                    RETURNING id, created_at, updated_at
                """
                )
                result = await self.conn.execute(
                    query,
                    {
                        "first_name": contact.first_name,
                        "last_name": contact.last_name,
                        "middle_name": contact.middle_name,
                        "nick_name": contact.nick_name,
                        "company": contact.company,
                        "job_title": contact.job_title,
                        "photo_url": contact.photo_url,
                        "is_favourite": contact.is_favourite,
                    },
                )
                row = result.fetchone()
                if row is None:
                    raise RuntimeError("Failed to insert contact")
                contact.id = row.id
                contact.created_at = row.created_at
                contact.updated_at = row.updated_at
            else:
                # Update existing contact
                query = text(
                    """
                    UPDATE contacts
                    SET first_name = :first_name, last_name = :last_name,
                        middle_name = :middle_name, nick_name = :nick_name,
                        company = :company, job_title = :job_title,
                        photo_url = :photo_url,
                        is_favourite = :is_favourite, updated_at = NOW()
                    WHERE id = :id
                    RETURNING updated_at
                """
                )
                result = await self.conn.execute(
                    query,
                    {
                        "id": contact.id,
                        "first_name": contact.first_name,
                        "last_name": contact.last_name,
                        "middle_name": contact.middle_name,
                        "nick_name": contact.nick_name,
                        "company": contact.company,
                        "job_title": contact.job_title,
                        "photo_url": contact.photo_url,
                        "is_favourite": contact.is_favourite,
                    },
                )
                row = result.fetchone()
                if row is None:
                    raise RuntimeError("Failed to update contact")
                contact.updated_at = row.updated_at

            return contact

        except IntegrityError as e:
            # Handle database constraint violations
            if "unique" in str(e).lower():
                raise DuplicateEmailError(
                    "Email already exists", 0
                ) from e  # Will be handled by service
            raise

    async def touch(
        self, contact_id: int, transaction: AsyncConnection | None = None
    ) -> None:
        """Update the updated_at timestamp of a contact."""
        query = text(
            """
            UPDATE contacts
            SET updated_at = NOW()
            WHERE id = :contact_id
            """
        )
        conn = transaction or self.conn
        result = await conn.execute(query, {"contact_id": contact_id})
        if result.rowcount == 0:
            raise ContactNotFoundError(contact_id)

    async def lock(self, contact_id: int) -> None:
        """Take the contact's row lock; see the port for the ordering it fixes."""
        await self.conn.execute(
            text("SELECT 1 FROM contacts WHERE id = :contact_id FOR UPDATE"),
            {"contact_id": contact_id},
        )

    async def lock_and_get_updated_at(self, contact_id: int) -> datetime | None:
        """Lock the contact row and return its last-write timestamp.

        ``FOR UPDATE`` rather than a plain read: see the port for the
        lost-update window this closes.
        """
        query = text(
            """
            SELECT updated_at
            FROM contacts
            WHERE id = :contact_id
            FOR UPDATE
            """
        )
        result = await self.conn.execute(query, {"contact_id": contact_id})
        row = result.fetchone()

        return row.updated_at if row else None

    async def delete(self, contact_id: int) -> None:
        """Delete a contact and all related data."""
        query = text("DELETE FROM contacts WHERE id = :contact_id")
        result = await self.conn.execute(query, {"contact_id": contact_id})

        if result.rowcount == 0:
            raise ContactNotFoundError(contact_id)

    async def bulk_delete_all(self, transaction: AsyncConnection) -> None:
        """
        Bulk delete all contacts and related data for test cleanup.

        This method efficiently deletes all contacts in a single operation
        without individual validation or event publishing overhead.

        WARNING: This will delete ALL contacts. Only use in test environments.
        """
        # Delete all contacts - foreign key constraints will handle related data
        query = text("DELETE FROM contacts")
        await transaction.execute(query)

    async def repoint_methods(
        self, source_id: int, survivor_id: int, transaction: AsyncConnection
    ) -> None:
        """Re-point the source contact's methods onto the survivor.

        Exact duplicates (same ``method_type`` + ``value``) are deleted before
        the re-point so they collapse — this also clears the global
        email-uniqueness collision (``ix_contact_methods_email_unique``), as the
        survivor is the only other contact that could already hold the value.
        Source primaries for a ``method_type`` the survivor already has a primary
        of are demoted so the re-point cannot violate
        ``ix_contact_methods_primary_unique`` (survivor's primary wins).
        """
        params = {"source_id": source_id, "survivor_id": survivor_id}

        # 1. Collapse exact duplicates (and resolve the email-unique collision).
        await transaction.execute(
            text(
                """
                DELETE FROM contact_methods src
                WHERE src.contact_id = :source_id
                AND EXISTS (
                    SELECT 1 FROM contact_methods tgt
                    WHERE tgt.contact_id = :survivor_id
                    AND tgt.method_type = src.method_type
                    AND tgt.value = src.value
                )
                """
            ),
            params,
        )

        # 2. Demote source primaries where the survivor already has a primary of
        #    that type (survivor's primary wins).
        await transaction.execute(
            text(
                """
                UPDATE contact_methods src
                SET is_primary = false, updated_at = CURRENT_TIMESTAMP
                WHERE src.contact_id = :source_id
                AND src.is_primary = true
                AND EXISTS (
                    SELECT 1 FROM contact_methods tgt
                    WHERE tgt.contact_id = :survivor_id
                    AND tgt.method_type = src.method_type
                    AND tgt.is_primary = true
                )
                """
            ),
            params,
        )

        # 3. Re-point the survivors.
        await transaction.execute(
            text(
                """
                UPDATE contact_methods
                SET contact_id = :survivor_id, updated_at = CURRENT_TIMESTAMP
                WHERE contact_id = :source_id
                """
            ),
            params,
        )

    async def repoint_addresses(
        self, source_id: int, survivor_id: int, transaction: AsyncConnection
    ) -> None:
        """Re-point the source contact's addresses onto the survivor.

        Addresses that exactly match a survivor address (every field) collapse.
        Source primaries are demoted when the survivor already has a primary
        address so the re-point cannot violate
        ``idx_contact_addresses_unique_primary`` (survivor's primary wins).
        """
        params = {"source_id": source_id, "survivor_id": survivor_id}

        # 1. Collapse exact-duplicate addresses (NULL-safe field comparison).
        await transaction.execute(
            text(
                """
                DELETE FROM contact_addresses src
                WHERE src.contact_id = :source_id
                AND EXISTS (
                    SELECT 1 FROM contact_addresses tgt
                    WHERE tgt.contact_id = :survivor_id
                    AND tgt.street_line_1 = src.street_line_1
                    AND tgt.country_code = src.country_code
                    AND tgt.street_line_2 IS NOT DISTINCT FROM src.street_line_2
                    AND tgt.locality IS NOT DISTINCT FROM src.locality
                    AND tgt.region IS NOT DISTINCT FROM src.region
                    AND tgt.postal_code IS NOT DISTINCT FROM src.postal_code
                    AND tgt.label IS NOT DISTINCT FROM src.label
                )
                """
            ),
            params,
        )

        # 2. Demote source primaries where the survivor already has a primary.
        await transaction.execute(
            text(
                """
                UPDATE contact_addresses src
                SET is_primary = false, updated_at = CURRENT_TIMESTAMP
                WHERE src.contact_id = :source_id
                AND src.is_primary = true
                AND EXISTS (
                    SELECT 1 FROM contact_addresses tgt
                    WHERE tgt.contact_id = :survivor_id
                    AND tgt.is_primary = true
                )
                """
            ),
            params,
        )

        # 3. Re-point the survivors.
        await transaction.execute(
            text(
                """
                UPDATE contact_addresses
                SET contact_id = :survivor_id, updated_at = CURRENT_TIMESTAMP
                WHERE contact_id = :source_id
                """
            ),
            params,
        )

    async def repoint_notes(
        self, source_id: int, survivor_id: int, transaction: AsyncConnection
    ) -> None:
        """Re-point the source contact's notes onto the survivor, collapsing
        notes whose content already exists on the survivor."""
        params = {"source_id": source_id, "survivor_id": survivor_id}

        await transaction.execute(
            text(
                """
                DELETE FROM contact_notes src
                WHERE src.contact_id = :source_id
                AND EXISTS (
                    SELECT 1 FROM contact_notes tgt
                    WHERE tgt.contact_id = :survivor_id
                    AND tgt.content = src.content
                )
                """
            ),
            params,
        )

        await transaction.execute(
            text(
                """
                UPDATE contact_notes
                SET contact_id = :survivor_id, updated_at = CURRENT_TIMESTAMP
                WHERE contact_id = :source_id
                """
            ),
            params,
        )

    async def repoint_important_dates(
        self, source_id: int, survivor_id: int, transaction: AsyncConnection
    ) -> None:
        """Re-point the source contact's important dates onto the survivor.

        Exact-duplicate dates collapse. If the survivor already has a birthday,
        the source's birthday is dropped first (survivor wins) so the re-point
        cannot violate the ``uq_contact_birthday`` partial unique index.
        """
        params = {"source_id": source_id, "survivor_id": survivor_id}

        # 1. Collapse exact-duplicate dates (NULL-safe field comparison).
        await transaction.execute(
            text(
                """
                DELETE FROM contact_important_dates src
                WHERE src.contact_id = :source_id
                AND EXISTS (
                    SELECT 1 FROM contact_important_dates tgt
                    WHERE tgt.contact_id = :survivor_id
                    AND tgt.date_type = src.date_type
                    AND tgt.precision = src.precision
                    AND tgt.year IS NOT DISTINCT FROM src.year
                    AND tgt.month IS NOT DISTINCT FROM src.month
                    AND tgt.day IS NOT DISTINCT FROM src.day
                    AND tgt.custom_date_type_id
                        IS NOT DISTINCT FROM src.custom_date_type_id
                )
                """
            ),
            params,
        )

        # 2. Drop the source's birthday when the survivor already has one.
        await transaction.execute(
            text(
                """
                DELETE FROM contact_important_dates src
                WHERE src.contact_id = :source_id
                AND src.date_type = 'birthday'
                AND EXISTS (
                    SELECT 1 FROM contact_important_dates tgt
                    WHERE tgt.contact_id = :survivor_id
                    AND tgt.date_type = 'birthday'
                )
                """
            ),
            params,
        )

        # 3. Re-point the survivors.
        await transaction.execute(
            text(
                """
                UPDATE contact_important_dates
                SET contact_id = :survivor_id, updated_at = CURRENT_TIMESTAMP
                WHERE contact_id = :source_id
                """
            ),
            params,
        )

    async def repoint_tags(
        self, source_id: int, survivor_id: int, transaction: AsyncConnection
    ) -> None:
        """Re-point the source contact's tags onto the survivor, deduping on the
        ``contact_tags`` composite primary key (union of both contacts' tags)."""
        params = {"source_id": source_id, "survivor_id": survivor_id}

        # 1. Drop source links the survivor already holds (composite-PK dedupe).
        await transaction.execute(
            text(
                """
                DELETE FROM contact_tags src
                WHERE src.contact_id = :source_id
                AND EXISTS (
                    SELECT 1 FROM contact_tags tgt
                    WHERE tgt.contact_id = :survivor_id
                    AND tgt.tag_id = src.tag_id
                )
                """
            ),
            params,
        )

        # 2. Re-point the remaining links (contact_tags has no updated_at).
        await transaction.execute(
            text(
                """
                UPDATE contact_tags
                SET contact_id = :survivor_id
                WHERE contact_id = :source_id
                """
            ),
            params,
        )

    async def get_contacts_by_tag(self, tag_id: int) -> list[Contact]:
        """Get all contacts with a specific tag."""
        query = text(
            """
            SELECT DISTINCT c.id, c.first_name, c.last_name FROM contacts c
            JOIN contact_tags ct ON c.id = ct.contact_id
            WHERE ct.tag_id = :tag_id
            ORDER BY c.first_name, c.last_name
        """
        )
        result = await self.conn.execute(query, {"tag_id": tag_id})
        contact_ids = [row.id for row in result.fetchall()]

        contacts = []
        for contact_id in contact_ids:
            contact = await self.find_by_id(contact_id)
            if contact:
                contacts.append(contact)
        return contacts

    async def add_method(self, contact_id: int, method: ContactMethod) -> ContactMethod:
        """Add a contact method."""
        try:
            query = text(
                """
                INSERT INTO contact_methods (contact_id, method_type, value, label, is_primary)
                VALUES (:contact_id, :method_type, :value, :label, :is_primary)
                RETURNING id, created_at, updated_at
            """
            )
            result = await self.conn.execute(
                query,
                {
                    "contact_id": contact_id,
                    "method_type": method.method_type.value,
                    "value": method.value,
                    "label": method.label,
                    "is_primary": method.is_primary,
                },
            )
            row = result.fetchone()
            if row is None:
                raise RuntimeError("Failed to insert contact method")
            method.id = row.id
            method.contact_id = contact_id
            method.created_at = row.created_at
            method.updated_at = row.updated_at
            return method

        except IntegrityError as e:
            error_str = str(e).lower()
            if "contact_methods_email_unique" in error_str or (
                "email" in method.value and "unique" in error_str
            ):
                raise DuplicateEmailError(
                    method.value, 0
                ) from e  # Will be handled by service
            if "contact_methods_primary_unique" in error_str or (
                "primary" in error_str and "unique" in error_str
            ):
                raise PrimaryMethodConflictError(
                    contact_id, method.method_type.value
                ) from e
            raise

    async def update_method(self, method: ContactMethod) -> ContactMethod:
        """Update a contact method."""
        try:
            query = text(
                """
                UPDATE contact_methods
                SET method_type = :method_type, value = :value, label = :label,
                    is_primary = :is_primary, updated_at = NOW()
                WHERE id = :id
                RETURNING updated_at
            """
            )
            result = await self.conn.execute(
                query,
                {
                    "id": method.id,
                    "method_type": method.method_type.value,
                    "value": method.value,
                    "label": method.label,
                    "is_primary": method.is_primary,
                },
            )
            row = result.fetchone()
            if row is None:
                raise RuntimeError("Failed to update contact method")
            method.updated_at = row.updated_at
            return method

        except IntegrityError as e:
            error_str = str(e).lower()
            if "contact_methods_email_unique" in error_str or (
                "email" in method.value and "unique" in error_str
            ):
                raise DuplicateEmailError(
                    method.value, 0
                ) from e  # Will be handled by service
            if "contact_methods_primary_unique" in error_str or (
                "primary" in error_str and "unique" in error_str
            ):
                raise PrimaryMethodConflictError(
                    method.contact_id, method.method_type.value
                ) from e
            raise

    async def find_method_by_id(self, method_id: int) -> ContactMethod | None:
        """Find a contact method by ID."""
        query = text(
            """
            SELECT id, contact_id, method_type, value, label, is_primary, created_at, updated_at
            FROM contact_methods
            WHERE id = :method_id
        """
        )
        result = await self.conn.execute(query, {"method_id": method_id})
        row = result.fetchone()

        if row is None:
            return None

        method_type = MethodType(row.method_type)

        return ContactMethod(
            id=row.id,
            contact_id=row.contact_id,
            method_type=method_type,
            value=self._normalize_contact_method_value(method_type, row.value),
            label=row.label,
            is_primary=row.is_primary,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def delete_method(self, method_id: int) -> None:
        """Delete a contact method."""
        query = text("DELETE FROM contact_methods WHERE id = :method_id")
        result = await self.conn.execute(query, {"method_id": method_id})

        if result.rowcount == 0:
            raise ContactNotFoundError(method_id)

    async def delete_all_methods(self, contact_id: int) -> None:
        """Delete all contact methods for a contact."""
        query = text("DELETE FROM contact_methods WHERE contact_id = :contact_id")
        await self.conn.execute(query, {"contact_id": contact_id})

    async def add_address(
        self, contact_id: int, address: ContactAddress
    ) -> ContactAddress:
        """Add a contact address."""
        try:
            query = text(
                """
                INSERT INTO contact_addresses
                (contact_id, label, street_line_1, street_line_2, locality, region,
                 postal_code, country_code, is_primary)
                VALUES (:contact_id, :label, :street_line_1, :street_line_2, :locality,
                        :region, :postal_code, :country_code, :is_primary)
                RETURNING id, created_at, updated_at
            """
            )
            result = await self.conn.execute(
                query,
                {
                    "contact_id": contact_id,
                    "label": address.label,
                    "street_line_1": address.street_line_1,
                    "street_line_2": address.street_line_2,
                    "locality": address.locality,
                    "region": address.region,
                    "postal_code": address.postal_code,
                    "country_code": address.country_code,
                    "is_primary": address.is_primary,
                },
            )
            row = result.fetchone()
            if row is None:
                raise RuntimeError("Failed to insert contact address")
            address.id = row.id
            address.contact_id = contact_id
            address.created_at = row.created_at
            address.updated_at = row.updated_at
            return address

        except IntegrityError as e:
            if "unique" in str(e).lower() and "primary" in str(e).lower():
                raise PrimaryAddressConflictError(contact_id) from e
            raise

    async def update_address(self, address: ContactAddress) -> ContactAddress:
        """Update a contact address."""
        try:
            query = text(
                """
                UPDATE contact_addresses
                SET label = :label, street_line_1 = :street_line_1, street_line_2 = :street_line_2,
                    locality = :locality, region = :region, postal_code = :postal_code,
                    country_code = :country_code, is_primary = :is_primary, updated_at = NOW()
                WHERE id = :id
                RETURNING updated_at
            """
            )
            result = await self.conn.execute(
                query,
                {
                    "id": address.id,
                    "label": address.label,
                    "street_line_1": address.street_line_1,
                    "street_line_2": address.street_line_2,
                    "locality": address.locality,
                    "region": address.region,
                    "postal_code": address.postal_code,
                    "country_code": address.country_code,
                    "is_primary": address.is_primary,
                },
            )
            row = result.fetchone()
            if row is None:
                raise RuntimeError("Failed to update contact address")
            address.updated_at = row.updated_at
            return address

        except IntegrityError as e:
            if "unique" in str(e).lower() and "primary" in str(e).lower():
                raise PrimaryAddressConflictError(address.contact_id) from e
            raise

    async def find_address_by_id(self, address_id: int) -> ContactAddress | None:
        """Find a contact address by ID."""
        query = text(
            """
            SELECT id, contact_id, label, street_line_1, street_line_2, locality,
                   region, postal_code, country_code, is_primary, created_at, updated_at
            FROM contact_addresses
            WHERE id = :address_id
        """
        )
        result = await self.conn.execute(query, {"address_id": address_id})
        row = result.fetchone()

        if row is None:
            return None

        return ContactAddress(
            id=row.id,
            contact_id=row.contact_id,
            label=row.label,
            street_line_1=row.street_line_1,
            street_line_2=row.street_line_2,
            locality=row.locality,
            region=row.region,
            postal_code=row.postal_code,
            country_code=row.country_code,
            is_primary=row.is_primary,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def delete_address(self, address_id: int) -> None:
        """Delete a contact address."""
        query = text("DELETE FROM contact_addresses WHERE id = :address_id")
        result = await self.conn.execute(query, {"address_id": address_id})

        if result.rowcount == 0:
            raise ContactNotFoundError(address_id)

    async def delete_all_addresses(self, contact_id: int) -> None:
        """Delete all contact addresses for a contact."""
        query = text("DELETE FROM contact_addresses WHERE contact_id = :contact_id")
        await self.conn.execute(query, {"contact_id": contact_id})

    async def add_note(self, contact_id: int, note: ContactNote) -> ContactNote:
        """Add a contact note."""
        query = text(
            """
            INSERT INTO contact_notes (contact_id, content)
            VALUES (:contact_id, :content)
            RETURNING id, created_at, updated_at
        """
        )
        result = await self.conn.execute(
            query, {"contact_id": contact_id, "content": note.content}
        )
        row = result.fetchone()
        if row is None:
            raise RuntimeError("Failed to insert contact note")
        note.id = row.id
        note.contact_id = contact_id
        note.created_at = row.created_at
        note.updated_at = row.updated_at
        return note

    async def update_note(self, note: ContactNote) -> ContactNote:
        """Update a contact note."""
        query = text(
            """
            UPDATE contact_notes
            SET content = :content, updated_at = NOW()
            WHERE id = :id
            RETURNING updated_at
        """
        )
        result = await self.conn.execute(
            query, {"id": note.id, "content": note.content}
        )
        row = result.fetchone()
        if row is None:
            raise RuntimeError("Failed to update contact note")
        note.updated_at = row.updated_at
        return note

    async def delete_note(self, note_id: int) -> None:
        """Delete a contact note."""
        query = text("DELETE FROM contact_notes WHERE id = :note_id")
        result = await self.conn.execute(query, {"note_id": note_id})

        if result.rowcount == 0:
            raise ContactNotFoundError(note_id)

    async def delete_all_notes(self, contact_id: int) -> None:
        """Delete all contact notes for a contact."""
        query = text("DELETE FROM contact_notes WHERE contact_id = :contact_id")
        await self.conn.execute(query, {"contact_id": contact_id})

    async def assign_tag(self, contact_id: int, tag_id: int) -> None:
        """Assign a tag to a contact."""
        query = text(
            """
            INSERT INTO contact_tags (contact_id, tag_id)
            VALUES (:contact_id, :tag_id)
            ON CONFLICT (contact_id, tag_id) DO NOTHING
        """
        )
        await self.conn.execute(query, {"contact_id": contact_id, "tag_id": tag_id})

    async def remove_tag(self, contact_id: int, tag_id: int) -> None:
        """Remove a tag from a contact."""
        query = text(
            """
            DELETE FROM contact_tags
            WHERE contact_id = :contact_id AND tag_id = :tag_id
        """
        )
        await self.conn.execute(query, {"contact_id": contact_id, "tag_id": tag_id})

    async def add_important_date(
        self, contact_id: int, date: ImportantDate
    ) -> ImportantDate:
        """Add an important date to a contact."""
        query = text(
            """
            INSERT INTO contact_important_dates
            (contact_id, date_type, precision, year, month, day, custom_date_type_id)
            VALUES (:contact_id, :date_type, :precision, :year, :month, :day, :custom_date_type_id)
            RETURNING id, created_at, updated_at
        """
        )
        try:
            result = await self.conn.execute(
                query,
                {
                    "contact_id": contact_id,
                    "date_type": date.date_type.value,
                    "precision": date.precision.value,
                    "year": date.year,
                    "month": date.month,
                    "day": date.day,
                    "custom_date_type_id": date.custom_date_type_id,
                },
            )
        except IntegrityError as e:
            error_msg = str(e).lower()
            if "uq_contact_birthday" in error_msg:
                raise DuplicateBirthdayError(contact_id) from e
            if "fk" in error_msg and "custom_date_types" in error_msg:
                raise CustomDateTypeNotFoundError(date.custom_date_type_id) from e  # type: ignore
            raise

        row = result.fetchone()
        if row is None:
            raise RuntimeError("Failed to insert contact important date")

        date.id = row.id
        date.contact_id = contact_id
        date.created_at = row.created_at
        date.updated_at = row.updated_at
        return date

    async def get_important_dates(self, contact_id: int) -> list[ImportantDate]:
        """Get all important dates for a contact."""
        query = text(
            """
            SELECT d.id, d.contact_id, d.date_type, d.precision, d.year, d.month, d.day,
                   d.custom_date_type_id, cdt.name as custom_date_type_name,
                   d.created_at, d.updated_at
            FROM contact_important_dates d
            LEFT JOIN custom_date_types cdt ON d.custom_date_type_id = cdt.id
            WHERE d.contact_id = :contact_id
            ORDER BY d.created_at ASC
        """
        )
        result = await self.conn.execute(query, {"contact_id": contact_id})

        return [
            ImportantDate(
                id=row.id,
                contact_id=row.contact_id,
                date_type=ImportantDateType(row.date_type),
                precision=DatePrecision(row.precision),
                year=row.year,
                month=row.month,
                day=row.day,
                custom_date_type_id=row.custom_date_type_id,
                custom_date_type_name=row.custom_date_type_name,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in result.fetchall()
        ]

    async def delete_important_date(self, date_id: int) -> None:
        """Delete an important date."""
        query = text("DELETE FROM contact_important_dates WHERE id = :date_id")
        result = await self.conn.execute(query, {"date_id": date_id})

        if result.rowcount == 0:
            raise ImportantDateNotFoundError(date_id)

    async def delete_all_important_dates(self, contact_id: int) -> None:
        """Delete all important dates for a contact."""
        query = text(
            "DELETE FROM contact_important_dates WHERE contact_id = :contact_id"
        )
        await self.conn.execute(query, {"contact_id": contact_id})

    async def get_favourite_contacts(
        self, limit: int = 100, offset: int = 0
    ) -> list[Contact]:
        """Get all favourite contacts with pagination."""
        # Single query to get all contact data
        query = text(
            """
            SELECT id, first_name, last_name, middle_name, nick_name, company, job_title,
                   is_favourite, created_at, updated_at
            FROM contacts
            WHERE is_favourite = true
            ORDER BY first_name, last_name
            LIMIT :limit OFFSET :offset
            """
        )
        result = await self.conn.execute(query, {"limit": limit, "offset": offset})
        contacts = []

        for row in result:
            contact = Contact(
                id=row.id,
                first_name=row.first_name,
                last_name=row.last_name,
                middle_name=row.middle_name,
                nick_name=row.nick_name,
                company=row.company,
                job_title=row.job_title,
                is_favourite=row.is_favourite,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            contacts.append(contact)

        # Batch load related entities for all contacts
        if contacts:
            await self._batch_load_contact_relations(contacts)

        return contacts

    async def get_favourite_contacts_count(self) -> int:
        """Get total count of favourite contacts."""
        query = text(
            """
            SELECT COUNT(*) as count
            FROM contacts
            WHERE is_favourite = true
            """
        )
        result = await self.conn.execute(query)
        row = result.fetchone()
        return row[0] if row else 0

    def _build_contact_filter_query_parts(
        self,
        is_favourite: bool | None = None,
        tag_ids: list[int] | None = None,
    ) -> tuple[list[str], list[str], dict[str, bool | int]]:
        """Build shared SQL JOIN/WHERE fragments and params for contact filtering."""
        query_parts: list[str] = []
        where_parts: list[str] = []
        params: dict[str, bool | int] = {}

        if tag_ids:
            query_parts.append(
                """
                JOIN contact_tags ct ON c.id = ct.contact_id
                """
            )

        if is_favourite is not None:
            where_parts.append("c.is_favourite = :is_favourite")
            params["is_favourite"] = is_favourite

        if tag_ids:
            tag_param_placeholders = []
            for tag_index, tag_id_value in enumerate(tag_ids):
                tag_param_name = f"tag_id_param_{tag_index}"
                tag_param_placeholders.append(f":{tag_param_name}")
                params[tag_param_name] = tag_id_value

            tag_placeholders_sql = ", ".join(tag_param_placeholders)
            where_parts.append(f"ct.tag_id IN ({tag_placeholders_sql})")

        return query_parts, where_parts, params

    async def get_contacts_count_by_filters(
        self,
        is_favourite: bool | None = None,
        tag_ids: list[int] | None = None,
    ) -> int:
        """Get the distinct count of contacts filtered by favourite status and/or tags."""
        query_parts = [
            """
            SELECT COUNT(DISTINCT c.id) as count
            FROM contacts c
            """
        ]
        filter_query_parts, where_parts, params = (
            self._build_contact_filter_query_parts(
                is_favourite=is_favourite,
                tag_ids=tag_ids,
            )
        )
        query_parts.extend(filter_query_parts)

        if where_parts:
            query_parts.append("WHERE " + " AND ".join(where_parts))

        query = text("".join(query_parts))
        result = await self.conn.execute(query, params)
        row = result.fetchone()
        return row[0] if row else 0

    async def get_contacts_by_filters(
        self,
        is_favourite: bool | None = None,
        tag_ids: list[int] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Contact]:
        """Get contacts filtered by favourite status and/or tags."""
        query_parts = [
            """
            SELECT DISTINCT c.id, c.first_name, c.last_name, c.middle_name, c.nick_name,
                   c.company, c.job_title, c.photo_url, c.is_favourite, c.created_at, c.updated_at
            FROM contacts c
            """
        ]
        filter_query_parts, where_parts, filter_params = (
            self._build_contact_filter_query_parts(
                is_favourite=is_favourite,
                tag_ids=tag_ids,
            )
        )
        query_parts.extend(filter_query_parts)
        params: dict[str, bool | int] = {
            **filter_params,
            "limit": limit,
            "offset": offset,
        }

        if where_parts:
            query_parts.append("WHERE " + " AND ".join(where_parts))

        query_parts.append(
            """
            ORDER BY c.first_name, c.last_name
            LIMIT :limit OFFSET :offset
            """
        )

        query = text("".join(query_parts))
        result = await self.conn.execute(query, params)
        contacts = []

        for row in result:
            contact = Contact(
                id=row.id,
                first_name=row.first_name,
                last_name=row.last_name,
                middle_name=row.middle_name,
                nick_name=row.nick_name,
                company=row.company,
                job_title=row.job_title,
                photo_url=row.photo_url,
                is_favourite=row.is_favourite,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            contacts.append(contact)

        # Batch load related entities for all contacts
        if contacts:
            await self._batch_load_contact_relations(contacts)

        return contacts

    async def _batch_load_contact_relations(self, contacts: list[Contact]) -> None:
        """Efficiently load all related entities for a list of contacts in batches."""
        if not contacts:
            return
        contact_ids = [contact.id for contact in contacts]
        contact_map = {contact.id: contact for contact in contacts}

        for contact in contacts:
            if contact.methods is None:
                contact.methods = []
            if contact.addresses is None:
                contact.addresses = []
            if contact.notes is None:
                contact.notes = []
            if contact.tags is None:
                contact.tags = []
            if contact.relationships is None:
                contact.relationships = []

        # Batch load contact methods
        methods_query = text(
            """
            SELECT contact_id, id, method_type, value, label, is_primary, created_at, updated_at
            FROM contact_methods
            WHERE contact_id = ANY(:contact_ids)
            ORDER BY contact_id, is_primary DESC, created_at ASC
            """
        )
        result = await self.conn.execute(methods_query, {"contact_ids": contact_ids})
        for row in result:
            method_type = MethodType(row.method_type)
            method = ContactMethod(
                method_type=method_type,
                value=self._normalize_contact_method_value(method_type, row.value),
                contact_id=row.contact_id,
                id=row.id,
                label=row.label,
                is_primary=row.is_primary,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            contact_map[row.contact_id].methods.append(method)  # type: ignore[union-attr]

        # Batch load contact addresses
        addresses_query = text(
            """
            SELECT contact_id, id, label, street_line_1, street_line_2, locality, region,
                   postal_code, country_code, is_primary, created_at, updated_at
            FROM contact_addresses
            WHERE contact_id = ANY(:contact_ids)
            ORDER BY contact_id, is_primary DESC, created_at ASC
            """
        )
        result = await self.conn.execute(addresses_query, {"contact_ids": contact_ids})
        for row in result:
            address = ContactAddress(
                street_line_1=row.street_line_1,
                country_code=row.country_code,
                contact_id=row.contact_id,
                id=row.id,
                label=row.label,
                street_line_2=row.street_line_2,
                locality=row.locality,
                region=row.region,
                postal_code=row.postal_code,
                is_primary=row.is_primary,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            contact_map[row.contact_id].addresses.append(address)  # type: ignore[union-attr]

        # Batch load contact notes
        notes_query = text(
            """
            SELECT contact_id, id, content, created_at, updated_at
            FROM contact_notes
            WHERE contact_id = ANY(:contact_ids)
            ORDER BY contact_id, created_at DESC
            """
        )
        result = await self.conn.execute(notes_query, {"contact_ids": contact_ids})
        for row in result:
            note = ContactNote(
                content=row.content,
                contact_id=row.contact_id,
                id=row.id,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            contact_map[row.contact_id].notes.append(note)  # type: ignore[union-attr]

        # Batch load contact tags
        tags_query = text(
            """
            SELECT ct.contact_id, t.id, t.name, t.parent_id, t.color, t.description,
                   t.created_at, t.updated_at
            FROM tags t
            JOIN contact_tags ct ON t.id = ct.tag_id
            WHERE ct.contact_id = ANY(:contact_ids)
            ORDER BY ct.contact_id, t.name
            """
        )
        result = await self.conn.execute(tags_query, {"contact_ids": contact_ids})
        for row in result:
            tag = Tag(
                id=row.id,
                name=TagName(row.name),
                parent_id=row.parent_id,
                color=row.color,
                description=row.description,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            contact_map[row.contact_id].tags.append(tag)  # type: ignore[union-attr]
