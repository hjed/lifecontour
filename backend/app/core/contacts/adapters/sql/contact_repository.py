"""SQL implementation of ContactRepository."""

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    MethodType,
    Tag,
)
from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
    DuplicateEmailError,
    PrimaryAddressConflictError,
    PrimaryMethodConflictError,
)
from app.core.contacts.models.repositories import ContactRepository
from app.core.contacts.models.value_objects import TagName


class SqlContactRepository(ContactRepository):
    """SQL implementation of ContactRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        self.conn = connection

    async def find_by_id(self, contact_id: int) -> Contact | None:
        """Find a contact by ID with all related data."""
        # Get contact basic info
        contact_query = text(
            """
            SELECT id, first_name, last_name, middle_name, nick_name, is_favourite, created_at, updated_at
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
            is_favourite=contact_row.is_favourite,
            created_at=contact_row.created_at,
            updated_at=contact_row.updated_at,
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
            method = ContactMethod(
                id=method_row.id,
                contact_id=contact_id,
                method_type=MethodType(method_row.method_type),
                value=method_row.value,
                label=method_row.label,
                is_primary=method_row.is_primary,
                created_at=method_row.created_at,
                updated_at=method_row.updated_at,
            )
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
            contact.tags.append(tag)

        return contact

    async def find_by_email(self, email: str) -> Contact | None:
        """Find a contact by email address."""
        query = text(
            """
            SELECT DISTINCT c.id FROM contacts c
            JOIN contact_methods cm ON c.id = cm.contact_id
            WHERE cm.method_type = :method_type AND cm.value = :email
        """
        )
        result = await self.conn.execute(
            query, {"method_type": MethodType.EMAIL.value, "email": email}
        )
        row = result.fetchone()

        if row:
            return await self.find_by_id(row.id)
        return None

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
                    INSERT INTO contacts (first_name, last_name, middle_name, nick_name, is_favourite)
                    VALUES (:first_name, :last_name, :middle_name, :nick_name, :is_favourite)
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
        try:
            query = text(
                """
                INSERT INTO contact_tags (contact_id, tag_id)
                VALUES (:contact_id, :tag_id)
            """
            )
            await self.conn.execute(query, {"contact_id": contact_id, "tag_id": tag_id})
        except IntegrityError:
            # Tag already assigned - ignore
            pass

    async def remove_tag(self, contact_id: int, tag_id: int) -> None:
        """Remove a tag from a contact."""
        query = text(
            """
            DELETE FROM contact_tags
            WHERE contact_id = :contact_id AND tag_id = :tag_id
        """
        )
        await self.conn.execute(query, {"contact_id": contact_id, "tag_id": tag_id})

    async def get_favourite_contacts(
        self, limit: int = 100, offset: int = 0
    ) -> list[Contact]:
        """Get all favourite contacts with pagination."""
        # Single query to get all contact data
        query = text(
            """
            SELECT id, first_name, last_name, middle_name, nick_name,
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

    async def get_contacts_by_filters(
        self,
        is_favourite: bool | None = None,
        tag_ids: list[int] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Contact]:
        """Get contacts filtered by favourite status and/or tags."""
        # Build the query dynamically based on filters
        query_parts = [
            """
            SELECT DISTINCT c.id, c.first_name, c.last_name, c.middle_name, c.nick_name,
                   c.is_favourite, c.created_at, c.updated_at
            FROM contacts c
            """
        ]

        # Add tag join if filtering by tags
        if tag_ids:
            query_parts.append(
                """
                JOIN contact_tags ct ON c.id = ct.contact_id
                """
            )

        # Start WHERE clause
        where_parts = []
        params = {"limit": limit, "offset": offset}

        # Add favourite filter if specified
        if is_favourite is not None:
            where_parts.append("c.is_favourite = :is_favourite")
            params["is_favourite"] = is_favourite

        # Add tag filter if specified
        if tag_ids:
            # Create safe parameter names and placeholders for tag IDs
            tag_param_placeholders = []
            for tag_index, tag_id_value in enumerate(tag_ids):
                # Use explicit, safe parameter naming pattern
                tag_param_name = f"tag_id_param_{tag_index}"
                tag_param_placeholders.append(f":{tag_param_name}")
                params[tag_param_name] = tag_id_value

            tag_placeholders_sql = ", ".join(tag_param_placeholders)
            where_parts.append(f"ct.tag_id IN ({tag_placeholders_sql})")

        # Combine WHERE parts if any
        if where_parts:
            query_parts.append("WHERE " + " AND ".join(where_parts))

        # Add ORDER BY and LIMIT
        query_parts.append(
            """
            ORDER BY c.first_name, c.last_name
            LIMIT :limit OFFSET :offset
            """
        )

        # Execute the query
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
            method = ContactMethod(
                method_type=MethodType(row.method_type),
                value=row.value,
                contact_id=row.contact_id,
                id=row.id,
                label=row.label,
                is_primary=row.is_primary,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            contact_map[row.contact_id].methods.append(method)

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
            contact_map[row.contact_id].addresses.append(address)

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
            contact_map[row.contact_id].notes.append(note)

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
                name=row.name,
                parent_id=row.parent_id,
                color=row.color,
                description=row.description,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            contact_map[row.contact_id].tags.append(tag)
