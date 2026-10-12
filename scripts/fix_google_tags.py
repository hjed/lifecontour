#!/usr/bin/env python3
"""
Script to fix incorrectly imported Google Contact tags.
Google API sometimes returns tags as 16-character hexadecimal hashes
(e.g., 130928a58fa27eeb) instead of their human-readable names.
This script finds those tags in the database, fetches the correct names
from Google Contacts API, and updates them.

Contact tags are per user, so it works on the tags of the user who owns the
given Google account only: another user's tags, even of the same name, are
never read, renamed or merged into. When several users have connected the same
Google account, it refuses unless ``--user-id`` names which one.
"""

import argparse
import asyncio
import os
import re
import sys

import asyncpg

# Add required paths
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../integration_workers/google")
    ),
)
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../core_shared"))
)

try:
    from google_client import GoogleAPIClient
    from group_mapping import _build_contact_group_mapping
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print(
        "Make sure this script is run from the project root or with inside a configured venv."
    )
    sys.exit(1)


async def fix_google_tags(
    db_url: str, google_account_email: str, user_id: str | None = None
) -> None:
    """Find and fix tags with 16-character hex hash names."""
    print("Connecting to database...")

    # Connect directly with asyncpg for simplicity in a one-off script
    conn = await asyncpg.connect(db_url)

    try:
        auth_rows = await conn.fetch(
            "SELECT user_id, encrypted_access_token FROM user_google_auth "
            "WHERE google_account_email = $1 AND ($2::text IS NULL OR user_id = $2)",
            google_account_email,
            user_id,
        )
        if not auth_rows:
            print(
                f"Error: Could not find Google credentials for {google_account_email} in database."
            )
            return
        if len(auth_rows) > 1:
            owners = ", ".join(sorted(str(row["user_id"]) for row in auth_rows))
            print(
                f"Error: {google_account_email} is connected by several users "
                f"({owners}). Pass --user-id to choose whose tags to repair."
            )
            return
        auth_row = auth_rows[0]
        owner = auth_row["user_id"]

        # Find the owner's tags that look like 16-character hex hashes
        # Regex for 16 exactly lowercase hex chars
        hex_pattern = "^[0-9a-f]{16}$"

        tags_query = """
            SELECT id, name
            FROM tags
            WHERE name ~ $1 AND user_id = $2
        """

        bad_tags = await conn.fetch(tags_query, hex_pattern, owner)

        if not bad_tags:
            print(
                "No tags matching the 16-character hex pattern found in the database. Nothing to fix."
            )
            return

        print(f"Found {len(bad_tags)} tags that appear to be Google Contact hashes.")

        print(f"Authenticating with Google for account {google_account_email}...")

        # We fetch the encrypted token from the DB and decrypt it locally.
        encryption_key = os.environ.get("ENCRYPTION_KEY")
        if not encryption_key:
            print(
                "Error: ENCRYPTION_KEY environment variable is required to decrypt Google tokens."
            )
            print("Set it using: export ENCRYPTION_KEY=...")
            return

        encrypted_token = auth_row["encrypted_access_token"]

        from cryptography.fernet import Fernet

        fernet = Fernet(encryption_key.encode())
        if isinstance(encrypted_token, str):
            encrypted_token = encrypted_token.encode()

        try:
            access_token = fernet.decrypt(encrypted_token).decode()
        except Exception as e:
            print(f"Error decrypting token: {e}")
            return

        # Initialize the dummy auth service
        class ScriptAuthService:
            async def get_access_token(
                self, user_id: str, google_account_email: str
            ) -> str:
                return access_token

        auth_service = ScriptAuthService()

        client = GoogleAPIClient(
            auth_service=auth_service,  # type: ignore[arg-type]
            google_account_email=google_account_email,
            google_client_id="dummy_client_id",
            google_client_secret="dummy_client_secret",
            user_id="script_user",
        )

        # Re-use our newly fixed mapping logic
        group_mapping = await _build_contact_group_mapping(client)

        if not group_mapping:
            print(
                "Failed to fetch group mapping or mapping is empty. Cannot translate tags."
            )
            return

        print(f"Successfully retrieved {len(group_mapping)} contact group mappings.")

        fixes_applied = 0
        fixes_failed = 0

        for bad_tag in bad_tags:
            tag_id = bad_tag["id"]
            hash_name = bad_tag["name"]

            # The mapping now contains both "contactGroups/{hash}" and "{hash}" keys
            correct_name = group_mapping.get(hash_name)

            if not correct_name:
                # Some API scopes prefix it with 'contactGroups/'
                correct_name = group_mapping.get(f"contactGroups/{hash_name}")

            if correct_name:
                # Sanitize the Google Contact Group name to match `tags.name` constraints
                correct_name = re.sub(r"[^a-zA-Z0-9_&-]", "-", correct_name.strip())
                correct_name = re.sub(r"-+", "-", correct_name)
                correct_name = correct_name.strip("-")

            if correct_name:
                print(f"Translating tag ID {tag_id}: '{hash_name}' -> '{correct_name}'")

                # Check if a tag with the correct name already exists to avoid unique constraint violations
                check_query = (
                    "SELECT id FROM tags WHERE LOWER(name) = LOWER($1) AND user_id = $2"
                )
                existing = await conn.fetchval(check_query, correct_name, owner)

                if existing:
                    print(
                        f"  Tag '{correct_name}' already exists (ID {existing}). Merging contacts into it."
                    )

                    # Update contact_tags to point to the existing correct tag
                    # Assuming junction table is contact_tags with contact_id and tag_id
                    try:
                        async with conn.transaction():
                            # First delete old references that would cause a unique constraint conflict
                            # i.e. where the contact already has the target tag
                            delete_dupes = """
                                DELETE FROM contact_tags
                                WHERE tag_id = $2
                                AND contact_id IN (
                                    SELECT contact_id FROM contact_tags WHERE tag_id = $1
                                )
                            """
                            await conn.execute(delete_dupes, existing, tag_id)

                            # Then update the remaining references
                            update_refs = """
                                UPDATE contact_tags
                                SET tag_id = $1
                                WHERE tag_id = $2
                            """
                            await conn.execute(update_refs, existing, tag_id)

                            # Delete the hash tag
                            delete_tag = "DELETE FROM tags WHERE id = $1"
                            await conn.execute(delete_tag, tag_id)

                        print(
                            f"  Successfully merged tag '{hash_name}' into existing tag."
                        )
                        fixes_applied += 1

                    except Exception as e:
                        print(f"  Failed to merge tag: {e}")
                        fixes_failed += 1
                else:
                    # Rename the tag
                    try:
                        update_query = "UPDATE tags SET name = $1, updated_at = NOW() WHERE id = $2"
                        await conn.execute(update_query, correct_name, tag_id)
                        print(f"  Successfully renamed tag '{hash_name}'.")
                        fixes_applied += 1
                    except Exception as e:
                        print(f"  Failed to rename tag: {e}")
                        fixes_failed += 1
            else:
                print(
                    f"Could not find translation for hash '{hash_name}' in Google Contact Groups."
                )
                fixes_failed += 1

        print(
            f"\nSummary: {fixes_applied} tags fixed, {fixes_failed} tags could not be fixed."
        )

    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix imported Google Contact tags that show as hashes"
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get(
            "DATABASE_URL",
            "postgresql://dev_user:dev_password@localhost:5432/personal_management_dev",
        ),
        help="Database connection URL",
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Google account email address to fetch contact groups for",
    )
    parser.add_argument(
        "--user-id",
        default=None,
        help="Owner whose tags to repair, when several users connect the same email",
    )

    args = parser.parse_args()

    asyncio.run(fix_google_tags(args.db_url, args.email, args.user_id))


if __name__ == "__main__":
    main()
