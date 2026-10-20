from src.assistants.context import ToolContext
from src.core.tools.domain import Tool

from . import use_cases as preferences_use_cases
from .tool_schemas import RememberPreference


def build(context: ToolContext) -> dict[str, Tool]:
    async def remember_preference(preference: str) -> str:
        saved = await preferences_use_cases.remember(
            organization_id=context.organization_id,
            user_id=context.user_id,
            text=preference,
            list_preferences_for_user_fn=context.ports.list_preferences_fn,
            create_preference_fn=context.ports.create_preference_fn,
        )
        return f"Remembered: {saved.text}"

    return {
        # Nothing it writes is hard to undo, but everything it writes shapes every future
        # turn. The approval is the consent.
        RememberPreference.__name__: Tool(
            schema=RememberPreference,
            handler=remember_preference,
            requires_approval=True,
            describe=lambda preference: f"remember for every future conversation:\n{preference}",
        ),
    }


async def context_block(context: ToolContext) -> str:
    return preferences_use_cases.render(await context.ports.list_preferences_fn(context.user_id))
