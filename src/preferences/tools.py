from src.core.tools.context import ToolContext
from src.core.tools.domain import Tool

from . import use_cases as preferences_use_cases
from .sqlalchemy import adapter
from .tool_schemas import RememberPreference


def build(context: ToolContext) -> dict[str, Tool]:
    async def list_preferences_for_user_fn(user_id):
        return await adapter.list_for_user(context.session, user_id)

    async def create_preference_fn(preference):
        return await adapter.create(context.session, preference)

    async def remember_preference(preference: str) -> str:
        saved = await preferences_use_cases.remember(
            organization_id=context.organization_id,
            user_id=context.user_id,
            text=preference,
            list_preferences_for_user_fn=list_preferences_for_user_fn,
            create_preference_fn=create_preference_fn,
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
    return preferences_use_cases.render(
        await adapter.list_for_user(context.session, context.user_id)
    )
