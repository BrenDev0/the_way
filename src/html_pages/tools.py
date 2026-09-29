"""The two-pass page builder, running inside a tool call.

Pass 1 is art direction with no write tools: it commits to typefaces, hex values, layout
and a signature detail in writing. Pass 2 executes that brief. The split is not the same
as splitting design into its own agent -- design and markup are one artifact, and a
separate agent would write CSS blind to a DOM that does not exist yet. What needs
separating is the *decision*: a model that styles a page one tag at a time chooses
implicitly, and implicit choices collapse to the median of its training data, which is
what "plain" is.
"""

from src.core.agents.runner import run_assistant
from src.core.exceptions import ApplicationError
from src.core.llm import domain as llm_domain
from src.core.tools.context import ToolContext
from src.core.tools.domain import Tool
from src.core.tools.executor import Executor
from src.core.tools.gates import AutoApproveGate
from src.projects import tools as project_tools
from src.projects.domain import ProjectFile
from src.projects.files import ProjectFiles
from src.web import tools as web_tools

from . import config
from .design import archetype_guidance
from .prompt import BUILDER_PROMPT, DESIGNER_PROMPT
from .tool_schemas import BuildHtmlPage

FAILURE_MARKER = "HTML BUILD FAILED"

NO_BRIEF = (
    "(The art-direction pass did not produce a brief. Follow the house design system "
    "exactly, and make the concrete choices it leaves open yourself -- typefaces, the "
    "palette hex values, and the section structure -- before writing any markup.)"
)


def build(context: ToolContext) -> dict[str, Tool]:
    available = {**project_tools.build(context), **web_tools.build(context)}
    files = ProjectFiles(
        context.session, context.organization_id, context.user_id, context.bucket_store
    )

    def executor_for(names: frozenset[str]) -> Executor:
        # Auto-approved: the builder revises the page it is writing, with nobody to ask,
        # and nothing destructive is in its reach to approve.
        tools = {name: tool for name, tool in available.items() if name in names}
        return Executor(tools, AutoApproveGate())

    async def written(project: str, path: str) -> str:
        try:
            target = await files.project(project)
            entry = await files.entry(target, path)
        except ApplicationError:
            entry = None
        if not isinstance(entry, ProjectFile):
            return f"NO FILE was written at {project}/{path}."
        return f"Wrote {project}/{path} ({entry.size_bytes:,} bytes)."

    async def build_html_page(
        project: str,
        output_path: str,
        page_type: str,
        brief: str,
        style_direction: str | None = None,
    ) -> str:
        request = (
            f"Page type: {page_type}\nProject: {project}\nOutput file: {output_path}\n\n"
            f"Brief:\n{brief}"
        )
        if style_direction:
            request += f"\n\nStyle direction from the user (treat as binding):\n{style_direction}"
        archetype = archetype_guidance(page_type)

        designer = await context.llm_factory(config.MODELS, config.DESIGNER_TEMPERATURE)
        try:
            direction = await run_assistant(
                designer,
                executor_for(config.DESIGNER_TOOLS),
                [llm_domain.system(DESIGNER_PROMPT), llm_domain.user(f"{request}\n\n{archetype}")],
                config.DESIGNER_MAX_ITERATIONS,
            )
            design_brief = direction.text if direction.finished and direction.text else NO_BRIEF
        except Exception:  # noqa: BLE001 -- a failed art pass costs quality, not the page
            design_brief = NO_BRIEF

        builder = await context.llm_factory(config.MODELS, config.BUILDER_TEMPERATURE)
        try:
            result = await run_assistant(
                builder,
                executor_for(config.BUILDER_TOOLS),
                [
                    llm_domain.system(BUILDER_PROMPT),
                    llm_domain.user(
                        f"{request}\n\n=== DESIGN BRIEF (execute this) ===\n{design_brief}"
                        f"\n\n{archetype}"
                    ),
                ],
                config.BUILDER_MAX_ITERATIONS,
            )
        except Exception as exc:  # noqa: BLE001
            return (
                f"{FAILURE_MARKER} -- {type(exc).__name__}: {exc}. "
                f"{await written(project, output_path)} Tell the user plainly that the page "
                "is unfinished; do not describe it as done."
            )

        # the builder's own report is not evidence the file exists -- check the project
        evidence = await written(project, output_path)
        if not result.finished:
            return (
                f"{FAILURE_MARKER} -- the builder ran out of steps. {evidence} It reported: "
                f"{result.text} Tell the user plainly that the page is unfinished."
            )
        return f"{evidence}\n{result.text}"

    return {BuildHtmlPage.__name__: Tool(schema=BuildHtmlPage, handler=build_html_page)}
