"""Journal domain MCP tools, one module per area.

Each module holds the tools for one area and a registrar for them;
``register_journal_tools`` registers every journal-domain tool. The tools
are adapters — argument parsing, a service or repository call, and the
response — and the journal logic behind them lives in ``app.core.journal``.
"""

from fastmcp import FastMCP

from app.mcp.domains.journals.tools.activities import register_activity_tools

# EVENT and PHOTO_ALBUM types require additional data (calendar_id, immich_album_id)
# These will be created when the user provides type_data
from app.mcp.domains.journals.tools.calendars import register_calendar_tools
from app.mcp.domains.journals.tools.contacts import register_journal_contact_tools
from app.mcp.domains.journals.tools.daily_summary import register_daily_summary_tools
from app.mcp.domains.journals.tools.gear import register_gear_tools
from app.mcp.domains.journals.tools.hierarchy import register_journal_hierarchy_tools
from app.mcp.domains.journals.tools.history import register_journal_history_tools
from app.mcp.domains.journals.tools.journal_entries import register_journal_entry_tools
from app.mcp.domains.journals.tools.journals import register_journal_read_tools
from app.mcp.domains.journals.tools.merge import register_journal_merge_tools
from app.mcp.domains.journals.tools.outdoor import register_outdoor_tools
from app.mcp.domains.journals.tools.review_items import register_review_item_tools
from app.mcp.domains.journals.tools.routes import register_journal_route_tools
from app.mcp.domains.journals.tools.search import register_journal_search_tools
from app.mcp.domains.journals.tools.series import register_journal_series_tools
from app.mcp.domains.journals.tools.tags import register_journal_tag_tools
from app.mcp.domains.journals.tools.templates import register_template_tools


def register_journal_tools(mcp: FastMCP[None]) -> None:
    """Register every journal-domain MCP tool with the FastMCP server."""
    register_journal_read_tools(mcp)
    register_journal_entry_tools(mcp)
    register_journal_search_tools(mcp)
    register_journal_hierarchy_tools(mcp)
    register_activity_tools(mcp)
    register_journal_history_tools(mcp)
    register_journal_contact_tools(mcp)
    register_calendar_tools(mcp)
    register_journal_merge_tools(mcp)
    register_review_item_tools(mcp)
    register_outdoor_tools(mcp)
    register_daily_summary_tools(mcp)
    register_template_tools(mcp)
    register_gear_tools(mcp)
    register_journal_tag_tools(mcp)
    register_journal_series_tools(mcp)
    register_journal_route_tools(mcp)
