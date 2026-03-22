#!/usr/bin/env python3
"""
Script to fix incorrectly imported Google Contact tags.
Google API sometimes returns tags as 16-character hexadecimal hashes
(e.g., 130928a58fa27eeb) instead of their human-readable names.
This script finds those tags in the database, fetches the correct names
from Google Contacts API, and updates them.
"""

import argparse
import asyncio
import os
import sys

import asyncpg

# Add required paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../integration_workers/google")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../core_shared")))

try:
    from google_auth_service import GoogleAuthService
    from google_client import GoogleAPIClient
    from worker import _build_contact_group_mapping
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print("Make sure this script is run from the project root or with inside a configured venv.")
    sys.exit(1)


async def fix_google_tags(db_url: str, google_account_email: str) -> None:
    """Find and fix tags with 16-character hex hash names."""
    print("Connecting to database...")

    # Connect directly with asyncpg for simplicity in a one-off script
    conn = await asyncpg.connect(db_url)

    try:
        # Find all tags that look like 16-character hex hashes
        # Regex for 16 exactly lowercase hex chars
        hex_pattern = "^[0-9a-f]{16}$"

        tags_query = """
            SELECT id, name
            FROM tags
            WHERE name ~ $1
        """

        bad_tags = await conn.fetch(tags_query, hex_pattern)

        if not bad_tags:
            print("No tags matching the 16-character hex pattern found in the database. Nothing to fix.")
            return

        print(f"Found {len(bad_tags)} tags that appear to be Google Contact hashes.")

        print(f"Authenticating with Google for account {google_account_email}...")

        # We need the Google OAuth credentials configured in the environment
        # or we could fetch the refresh token from the DB.
        # But GoogleAuthService from the worker knows how to initialize given an email

        # Initialize the auth service
        auth_service = GoogleAuthService()

        print("Fetching Google contact groups to build translation mapping...")
        client = GoogleAPIClient(auth_service, google_account_email)

        # Re-use our newly fixed mapping logic
        group_mapping = await _build_contact_group_mapping(client)

        if not group_mapping:
            print("Failed to fetch group mapping or mapping is empty. Cannot translate tags.")
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
                print(f"Translating tag ID {tag_id}: '{hash_name}' -> '{correct_name}'")

                # Check if a tag with the correct name already exists to avoid unique constraint violations
                check_query = "SELECT id FROM tags WHERE name = $1"
                existing = await conn.fetchval(check_query, correct_name)

                if existing:
                    print(f"  Tag '{correct_name}' already exists (ID {existing}). Merging contacts into it.")

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

                        print(f"  Successfully merged tag '{hash_name}' into existing tag.")
                        fixes_applied += 1

                    except Exception as e:
                        print(f"  Failed to merge tag: {e}")
                        fixes_failed += 1
                else:
                    # Rename the tag
                    try:
                        update_query = "UPDATE tags SET name = $1 WHERE id = $2"
                        await conn.execute(update_query, correct_name, tag_id)
                        print(f"  Successfully renamed tag '{hash_name}'.")
                        fixes_applied += 1
                    except Exception as e:
                        print(f"  Failed to rename tag: {e}")
                        fixes_failed += 1
            else:
                print(f"Could not find translation for hash '{hash_name}' in Google Contact Groups.")
                fixes_failed += 1

        print(f"\nSummary: {fixes_applied} tags fixed, {fixes_failed} tags could not be fixed.")

    finally:
        await conn.close()


def main():
    parser = argparse.ArgumentParser(description="Fix imported Google Contact tags that show as hashes")
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL", "postgresql://user:password@localhost:5432/pms"),
        help="Database connection URL"
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Google account email address to fetch contact groups for"
    )

    args = parser.parse_args()

    asyncio.run(fix_google_tags(args.db_url, args.email))


if __name__ == "__main__":
    main()
