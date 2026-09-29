from src.core.agents.runner import run_assistant
from src.core.llm import domain as llm_domain
from src.core.tools.context import ToolContext
from src.core.tools.domain import Tool
from src.core.tools.executor import Executor
from src.core.tools.gates import AutoApproveGate
from src.knowledge.schemas import ReadSkill
from src.users.domain import Role

from . import use_cases as skills_use_cases
from .prompt import BUILDER_PROMPT
from .sqlalchemy import adapter
from .tool_schemas import BuildSkill, SaveSkill

# Writing a skill to a layout the prompt spells out is templated work, not reasoning.
BUILDER_MODELS = ("gpt-5.4-mini", "claude-haiku-4-5-20251001")
BUILDER_MAX_ITERATIONS = 8

AUTHORS = frozenset({Role.OWNER, Role.ADMIN})


def build(context: ToolContext) -> dict[str, Tool]:
    """BuildSkill, for the people allowed to change the organization's skills -- the same
    roles the skills routes admit. Everyone else gets no tool rather than a failing one."""
    if context.user_role not in AUTHORS:
        return {}

    async def get_skill_fn(name, organization_id):
        return await adapter.get_for_organization(context.session, name, organization_id)

    async def count_skills_fn(organization_id):
        return await adapter.count_for_organization(context.session, organization_id)

    async def upsert_skill_fn(skill):
        return await adapter.upsert(context.session, skill)

    async def read_skill(name: str) -> str:
        skill = await get_skill_fn(name, context.organization_id)
        if skill is None:
            return f"No skill named '{name}' exists yet."
        return f"description: {skill.description}\n\n{skill.instructions}"

    async def save_skill(name: str, description: str, instructions: str) -> str:
        skill = await skills_use_cases.save_skill(
            organization_id=context.organization_id,
            instructions=instructions,
            created_by=context.user_id,
            count_skills_fn=count_skills_fn,
            get_skill_fn=get_skill_fn,
            upsert_skill_fn=upsert_skill_fn,
            name=name,
            description=description,
        )
        return f"Saved skill '{skill.name}'."

    builder_tools = {
        ReadSkill.__name__: Tool(schema=ReadSkill, handler=read_skill),
        SaveSkill.__name__: Tool(schema=SaveSkill, handler=save_skill),
    }

    async def build_skill(skill_name: str, description: str) -> str:
        llm = await context.llm_factory(BUILDER_MODELS)
        result = await run_assistant(
            llm,
            Executor(builder_tools, AutoApproveGate()),
            [
                llm_domain.system(BUILDER_PROMPT),
                llm_domain.user(f"Skill name: {skill_name}\n\nBrief:\n{description}"),
            ],
            BUILDER_MAX_ITERATIONS,
        )
        if not result.finished:
            return (
                f"BuildSkill did not finish '{skill_name}' within its step limit. It "
                f"reported: {result.text} Retry with the same skill_name to resume."
            )
        return result.text

    return {
        # Skills are shared with the whole organization, so saving one asks first.
        BuildSkill.__name__: Tool(
            schema=BuildSkill,
            handler=build_skill,
            requires_approval=True,
            describe=lambda skill_name, **_: (
                f"create or update the organization skill '{skill_name}'"
            ),
        ),
    }
