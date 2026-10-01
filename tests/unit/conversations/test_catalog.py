from uuid import uuid4

import pytest
from helpers import FakeBucketStore

from src.assistants import catalog
from src.background import config as background_config
from src.conversations import tools as conversation_tools
from src.core.tools.context import Credential, ToolContext
from src.core.tools.domain import ToolLocation
from src.desktop import tools as desktop_tools
from src.users.domain import Role


async def no_llm(preferred=(), temperature=0.0):
    raise AssertionError("no model should be built while listing tools")


def context(role=Role.MEMBER, **credentials) -> ToolContext:
    return ToolContext(
        session=None,  # type: ignore[arg-type] -- building tools never touches it
        organization_id=uuid4(),
        user_id=uuid4(),
        user_role=str(role),
        bucket_store=FakeBucketStore(),
        credentials={name: Credential(**value) for name, value in credentials.items()},
        llm_factory=no_llm,
    )


def test_a_desktop_conversation_gets_every_desktop_tool():
    tools = conversation_tools.build(context(), desktop=True)

    assert {schema.__name__ for schema in desktop_tools.SCHEMAS} <= set(tools)


def test_a_web_conversation_gets_no_desktop_tool():
    tools = conversation_tools.build(context(), desktop=False)

    assert not any(tool.location is ToolLocation.DESKTOP for tool in tools.values())


def test_desktop_tools_have_no_server_handler():
    for tool in desktop_tools.build().values():
        assert tool.handler is None
        assert tool.location is ToolLocation.DESKTOP


@pytest.mark.parametrize(
    "name",
    ["UpdateFile", "MovePath", "RenamePath", "DeleteFile", "DeleteDir", "SendWhatsappMessage", "UploadToProject"],
)
def test_desktop_calls_that_change_or_send_need_approval(name):
    assert desktop_tools.build()[name].requires_approval is True


@pytest.mark.parametrize("name", ["ReadFile", "ListDir", "SearchCode", "CreateFile", "OpenBrowserPage"])
def test_desktop_calls_that_only_look_or_create_do_not(name):
    assert desktop_tools.build()[name].requires_approval is False


def test_without_a_cx_key_there_are_no_cx_tools_and_it_is_said():
    ctx = context()

    assert "ExecuteCXOperation" not in conversation_tools.build(ctx, desktop=False)
    assert any("CX" in item for item in catalog.unavailable(ctx))


def test_a_cx_key_with_its_location_brings_the_cx_tools():
    ctx = context(gohighlevel={"secret": "pit-1", "account_id": "loc-1"})
    tools = conversation_tools.build(ctx, desktop=False)

    assert {"SearchCXOperations", "FetchCXDataset", "QueryCXDataset"} <= set(tools)
    assert not any("CX" in item for item in catalog.unavailable(ctx))


def test_a_web_search_key_brings_the_web_tools():
    tools = conversation_tools.build(context(tavily={"secret": "tvly-1"}), desktop=False)

    assert {"WebSearch", "ExtractWebPages", "CrawlWebPages"} <= set(tools)


def test_members_cannot_author_organization_skills():
    assert "BuildSkill" not in conversation_tools.build(context(Role.MEMBER), desktop=False)


@pytest.mark.parametrize("role", [Role.OWNER, Role.ADMIN])
def test_owners_and_admins_can_and_are_asked_first(role):
    tool = conversation_tools.build(context(role), desktop=False)["BuildSkill"]

    assert tool.requires_approval is True


@pytest.mark.parametrize(
    "name", ["EditProjectFile", "MoveProjectPath", "RenameProjectPath", "DeleteProjectPath", "RememberPreference"]
)
def test_server_calls_that_change_things_need_approval(name):
    assert conversation_tools.build(context(), desktop=False)[name].requires_approval is True


def test_the_background_worker_cannot_reach_destructive_or_desktop_tools():
    full = conversation_tools.build(
        context(gohighlevel={"secret": "p", "account_id": "l"}, tavily={"secret": "t"}),
        desktop=True,
    )
    worker = {name for name in full if name in background_config.TOOLS}

    assert not worker & {"DeleteProjectPath", "MoveProjectPath", "StartBackgroundTask"}
    assert not worker & {schema.__name__ for schema in desktop_tools.SCHEMAS}
    assert "RememberPreference" not in worker
    assert {"WriteProjectFile", "FetchCXDataset", "BuildHtmlPage"} <= worker


def test_image_tools_come_with_an_openai_key_and_always_ask_with_a_model_menu():
    without = conversation_tools.build(context(), desktop=False)
    with_key = conversation_tools.build(context(openai={"secret": "sk"}), desktop=False)

    assert "GenerateImages" not in without
    assert any("image generation" in item for item in catalog.unavailable(context()))
    for name in ("GenerateImages", "EditImage"):
        tool = with_key[name]
        assert tool.requires_approval and tool.always_ask
        assert tool.choices == {"model": ("gpt-image-2.5-flare", "gpt-image-2.5-sunburst")}
        assert name in background_config.TOOLS  # the worker gets them, and suspends on them


def test_deletions_ask_even_in_auto_mode_and_messages_do_not():
    server = conversation_tools.build(context(), desktop=True)

    assert server["DeleteProjectPath"].always_ask
    assert server["DeleteFile"].always_ask and server["DeleteDir"].always_ask
    assert not server["SendWhatsappMessage"].always_ask
    assert not server["MoveProjectPath"].always_ask


async def test_an_image_call_reaches_the_client_marked_to_ask_even_in_auto_mode():
    from src.conversations import mapper
    from src.core.llm.domain import ToolCall
    from src.core.tools.executor import Executor
    from src.core.tools.gates import SuspendGate

    tools = conversation_tools.build(context(openai={"secret": "sk"}), desktop=False)
    executor = Executor(tools, SuspendGate())
    image = ToolCall(id="call-image", name="GenerateImages", args={"project": "B", "images": [{"prompt": "x", "output_path": "a.png"}]})
    edit = ToolCall(id="call-edit", name="EditProjectFile", args={"project": "B", "path": "a.md", "old_string": "a", "new_string": "b"})

    with pytest.raises(Exception) as stopped:
        await executor.execute([image, edit])

    asked = {r.call.id: mapper.request_to_response(r).always_ask for r in stopped.value.requests}  # type: ignore[attr-defined]
    assert asked == {"call-image": True, "call-edit": False}
