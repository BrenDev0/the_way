"""The server-side tools every assistant draws from.

Each slice builds its own tools from the run's ToolContext; this only puts them side by
side. An assistant takes the subset its job needs -- the conversation assistant adds the
desktop and background tools on top, the background worker keeps an allowlist.
"""

from src.core.tools.context import ToolContext
from src.core.tools.domain import Tool
from src.crm import tools as crm_tools
from src.exports import tools as export_tools
from src.html_pages import tools as html_tools
from src.images import tools as image_tools
from src.knowledge import tools as knowledge_tools
from src.media import tools as media_tools
from src.projects import tools as project_tools
from src.web import tools as web_tools


def server_tools(context: ToolContext) -> dict[str, Tool]:
    return {
        **knowledge_tools.build(context.session, context.organization_id),
        **project_tools.build(context),
        **crm_tools.build(context),
        **web_tools.build(context),
        **html_tools.build(context),
        **export_tools.build(context),
        **media_tools.build(context),
        **(image_tools.build(context) if image_tools.available(context) else {}),
    }


def unavailable(context: ToolContext) -> list[str]:
    """Integrations this user has no key for, so the assistant can say why it cannot do
    something rather than pretend the tools do not exist."""
    missing = []
    if not crm_tools.available(context):
        missing.append("CX (the CRM) -- no CX key has been issued to this user")
    if not web_tools.available(context):
        missing.append("web search -- no web search key has been issued to this user")
    if not image_tools.available(context):
        missing.append("image generation -- no OpenAI key has been issued to this user")
    return missing
