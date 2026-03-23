"""
Helper module for fetching and building Google Contact Group mappings.
Extracted to avoid side-effects from worker module-level imports.
"""

import structlog

from api_models import ListContactGroupsResponse
from google_client import GoogleAPIClient

logger = structlog.get_logger(__name__)


async def _build_contact_group_mapping(client: GoogleAPIClient) -> dict[str, str]:
    """Fetch contact groups and build the translation mapping."""
    group_mapping: dict[str, str] = {}
    try:
        page_token: str | None = None
        groups_processed_count = 0
        while True:
            groups_data = await client.list_contact_groups(
                page_size=1000, page_token=page_token
            )
            groups_response = ListContactGroupsResponse(**groups_data)

            if (
                hasattr(groups_response, "contact_groups")
                and groups_response.contact_groups
            ):
                groups_processed_count += len(groups_response.contact_groups)
                for group in groups_response.contact_groups:
                    name_to_use = group.formatted_name or group.name
                    if group.resource_name and name_to_use:
                        group_mapping[group.resource_name] = name_to_use

            if (
                hasattr(groups_response, "next_page_token")
                and groups_response.next_page_token
            ):
                page_token = groups_response.next_page_token
            else:
                break

        logger.info(
            "Successfully built contact group translation mapping",
            groups_count=groups_processed_count,
            mapping_entries_count=len(group_mapping),
        )
    except Exception as e:
        logger.error(
            "Failed to fetch contact groups for mapping",
            error=str(e),
            account_email=client.google_account_email,
        )

    return group_mapping
