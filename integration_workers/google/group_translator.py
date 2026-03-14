"""
Translator for converting Google Contact Groups to local Tag Names.
Handles reserved group rules and translates contactGroupResourceName to actual names using a mapping.
"""

from collections.abc import Mapping

import structlog

logger = structlog.get_logger()


class GoogleGroupNameTranslator:
    """
    Translates Google Contact Groups to local Tag Names.
    """

    def __init__(
        self,
        reserved_group_ids: list[str],
        group_mapping: Mapping[str, str],
    ) -> None:
        """
        Initialize the translator.

        Args:
            reserved_group_ids: List of contact group IDs to ignore (e.g. ["myContacts"])
            group_mapping: Mapping of contactGroupResourceName to formattedName or name
        """
        self.reserved_group_ids = frozenset(reserved_group_ids)
        self.group_mapping = group_mapping

    def is_reserved(self, group_id: str | None) -> bool:
        """
        Check if a group ID is in the reserved list.
        `starred` is explicitly checked elsewhere or can be considered reserved for tag creation.
        For tags, we ignore any reserved groups.

        Args:
            group_id: The contactGroupId from the API

        Returns:
            True if reserved, False otherwise
        """
        if not group_id:
            return False

        return group_id in self.reserved_group_ids or group_id == "starred"

    def translate(
        self, resource_name: str | None, fallback_name: str | None = None
    ) -> str | None:
        """
        Translate a contact group resource name to its actual display name.

        Args:
            resource_name: The contactGroupResourceName from the API
            fallback_name: A fallback name to use if the resource_name is not in the mapping

        Returns:
            The translated name, or the fallback name, or None
        """
        if not resource_name:
            return fallback_name

        # Look up the name in the mapping provided by listContactGroups
        mapped_name = self.group_mapping.get(resource_name)
        if mapped_name:
            return mapped_name

        return fallback_name
