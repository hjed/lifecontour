"""
Helper module for fetching and building Google Contact Group mappings.
Extracted to avoid side-effects from worker module-level imports.
"""

import structlog

from api_models import ListContactGroupsResponse
from google_client import GoogleAPIClient

logger = structlog.get_logger(__name__)


async def _collect_contact_groups(
    client: GoogleAPIClient, group_mapping: dict[str, str]
) -> int:
    """Page through the account's contact groups into ``group_mapping``.

    Fills ``group_mapping`` (resource name → display name) in place, so a caller
    that tolerates failure can keep whatever pages arrived before an error.

    Returns:
        The number of groups processed.

    Raises:
        Exception: Whatever the Google client raises for a failed page.
    """
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
            return groups_processed_count


async def _fetch_contact_group_mapping(client: GoogleAPIClient) -> dict[str, str]:
    """Fetch the complete contact-group mapping, raising if any page fails.

    Use this wherever an incomplete mapping would be acted on destructively.
    The outbound push replaces a person's ``memberships`` wholesale, so a
    mapping missing groups would strip the contact from them — and make their
    tags look groupless, prompting duplicate group creation.
    """
    group_mapping: dict[str, str] = {}
    groups_processed_count = await _collect_contact_groups(client, group_mapping)
    logger.info(
        "Successfully built contact group translation mapping",
        groups_count=groups_processed_count,
        mapping_entries_count=len(group_mapping),
    )
    return group_mapping


async def _build_contact_group_mapping(client: GoogleAPIClient) -> dict[str, str]:
    """Fetch contact groups and build the translation mapping, tolerating failure.

    On error this logs and returns whatever pages arrived. That suits the
    inbound sync, which only translates group ids to tag names and is better off
    importing a contact without some tags than not at all. Outbound code must
    use :func:`_fetch_contact_group_mapping` instead.
    """
    group_mapping: dict[str, str] = {}
    try:
        groups_processed_count = await _collect_contact_groups(client, group_mapping)
        logger.info(
            "Successfully built contact group translation mapping",
            groups_count=groups_processed_count,
            mapping_entries_count=len(group_mapping),
        )
    except Exception as e:  # noqa: BLE001
        logger.error(
            "Failed to fetch contact groups for mapping",
            error=str(e),
            account_email=client.google_account_email,
        )

    return group_mapping
