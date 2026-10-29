from src.assistants.context import ToolContext
from src.core.agents.runner import run_assistant
from src.core.llm import domain as llm_domain
from src.core.tools.domain import Tool
from src.core.tools.executor import Executor
from src.core.tools.gates import AutoApproveGate
from src.knowledge.schemas import ReadSkill
from src.users.domain import Role

from . import use_cases as skills_use_cases
from .prompt import BUILDER_PROMPT
from .tool_schemas import BuildSkill, DeleteMySkill, ImportSkill, SaveSkill

# Writing a skill to a layout the prompt spells out is templated work, not reasoning.
BUILDER_MODELS = ("gpt-5.4-mini", "claude-haiku-4-5-20251001")
BUILDER_MAX_ITERATIONS = 8

# Who may write skills for the whole organization. Anyone may write their own.
AUTHORS = frozenset({Role.OWNER, Role.ADMIN})


def build(context: ToolContext) -> dict[str, Tool]:
    """BuildSkill and DeleteMySkill, for everyone. What a skill is for decides who can write it:
    the organization's skills are for owners and admins; an operator's skills are their own, and
    nobody else in the organization sees them."""
    ports = context.ports
    can_share = context.user_role in AUTHORS

    def scope(personal: bool):
        """Whose skill this is: the person's own, or None for the whole organization. An operator
        has no other choice."""
        return context.user_id if (personal or not can_share) else None

    async def read_skill(name: str, owner_id, file: str | None = None) -> str:
        getter = ports.get_skill_in_scope_fn
        skill = await getter(name, context.organization_id, owner_id) if getter else await ports.get_skill_fn(name, context.organization_id)
        if skill is None:
            return f"No skill named '{name}' exists yet."
        if file is not None:
            # The builder rewrites the skill file only; its reference files are kept.
            return f"Reference files are kept as they are when you save; '{file}' is not shown."
        triggers = "\n".join(f"- {trigger}" for trigger in skill.triggers) or "(none)"
        files = ", ".join(sorted(skill.files or {})) or "(none)"
        return (
            f"description: {skill.description}\n\ntriggers:\n{triggers}\n\n"
            f"reference files (kept on save): {files}\n\n{skill.instructions}"
        )

    async def save_skill(
        owner_id, name: str, description: str, instructions: str, triggers: list[str] | None = None
    ) -> str:
        if not triggers:
            # A builder that leaves them out has not decided to drop them.
            getter = ports.get_skill_in_scope_fn
            existing = await getter(name, context.organization_id, owner_id) if getter else None
            triggers = existing.triggers if existing else []
        skill = await skills_use_cases.save_skill(
            organization_id=context.organization_id,
            instructions=instructions,
            created_by=context.user_id,
            count_skills_fn=ports.count_skills_fn,
            get_skill_fn=ports.get_skill_fn,
            upsert_skill_fn=ports.upsert_skill_fn,
            name=name,
            description=description,
            triggers=triggers,
            owner_id=owner_id,
            count_personal_skills_fn=ports.count_personal_skills_fn,
            get_skill_in_scope_fn=ports.get_skill_in_scope_fn,
        )
        return f"Saved skill '{skill.name}'."

    async def build_skill(skill_name: str, description: str, personal: bool = False) -> str:
        owner_id = scope(personal)

        async def builder_read(name: str, file: str | None = None, offset: int = 0) -> str:
            return await read_skill(name, owner_id, file)

        async def builder_save(
            name: str, description: str, instructions: str, triggers: list[str] | None = None
        ) -> str:
            return await save_skill(owner_id, name, description, instructions, triggers)

        builder_tools = {
            ReadSkill.__name__: Tool(schema=ReadSkill, handler=builder_read),
            SaveSkill.__name__: Tool(schema=SaveSkill, handler=builder_save),
        }
        llm = await context.llm_factory(BUILDER_MODELS)
        result = await run_assistant(
            llm,
            Executor(builder_tools, AutoApproveGate(), context.events),
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

    async def import_skill(
        instructions: str,
        files: dict[str, str] | None = None,
        name: str | None = None,
        personal: bool = False,
    ) -> str:
        """Saved as it is: the file is the user's, and is not rewritten by anyone."""
        skill = await skills_use_cases.save_skill(
            organization_id=context.organization_id,
            instructions=instructions,
            created_by=context.user_id,
            count_skills_fn=ports.count_skills_fn,
            get_skill_fn=ports.get_skill_fn,
            upsert_skill_fn=ports.upsert_skill_fn,
            name=name,
            files=files,
            owner_id=scope(personal),
            count_personal_skills_fn=ports.count_personal_skills_fn,
            get_skill_in_scope_fn=ports.get_skill_in_scope_fn,
        )
        who = "yours alone" if skill.owner_id is not None else "shared with the organization"
        kept = sorted(skill.files or {})
        extra = f" Reference files kept: {', '.join(kept)}." if kept else " It has no reference files."
        return f"Saved skill '{skill.name}' exactly as written ({who}).{extra}"

    async def delete_my_skill(name: str) -> str:
        delete = ports.delete_skill_in_scope_fn
        if delete is None:
            return "Skills of your own cannot be deleted here."
        if await delete(name.strip(), context.organization_id, context.user_id):
            return f"Deleted your skill '{name.strip()}'."
        return (
            f"You have no skill of your own named '{name.strip()}'. The organization's skills "
            "are not deleted here: only owners and admins manage those, from the Skills page."
        )

    def describe_build(skill_name: str, personal: bool = False, **_) -> str:
        if scope(personal) is not None:
            return f"create or update your own skill '{skill_name}' (only you will see it)"
        return f"create or update the organization skill '{skill_name}' (everyone in the organization will see it)"

    def describe_import(personal: bool = False, name: str | None = None, **_) -> str:
        which = f"the skill '{name}'" if name else "a skill"
        where = "for yourself only" if scope(personal) is not None else "for the whole organization"
        return f"keep {which} exactly as written, {where}"

    return {
        # Saving asks first: a skill changes how the agent works, for one person or for everyone.
        BuildSkill.__name__: Tool(
            schema=BuildSkill,
            handler=build_skill,
            requires_approval=True,
            describe=describe_build,
        ),
        ImportSkill.__name__: Tool(
            schema=ImportSkill,
            handler=import_skill,
            requires_approval=True,
            describe=describe_import,
        ),
        DeleteMySkill.__name__: Tool(
            schema=DeleteMySkill,
            handler=delete_my_skill,
            requires_approval=True,
            describe=lambda name, **_: f"delete your own skill '{name}'",
        ),
    }
