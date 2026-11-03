from datetime import UTC, datetime
from uuid import uuid4

from src.projects import config
from src.projects.domain import Project
from src.projects.use_cases import management
from src.projects.use_cases import projects as project_use_cases

ORGANIZATION = uuid4()
OWNER = uuid4()


def project(name: str) -> Project:
    now = datetime.now(UTC)
    return Project(
        id=uuid4(), organization_id=ORGANIZATION, owner_id=OWNER, name=name, created_at=now, updated_at=now
    )


HELD = [project("Campaña"), project(config.WORKSPACE_PROJECT), project(config.DRAFTS_PROJECT)]


async def held(_owner_id):
    return HELD


async def held_by_organization(_organization_id, _owner_id):
    return HELD


def names(projects) -> list[str]:
    return [p.name for p in projects]


async def test_the_list_leaves_out_the_agents_workspace():
    listed = await project_use_cases.list_projects(OWNER, held)

    assert names(listed) == ["Campaña", config.DRAFTS_PROJECT]


async def test_the_workspace_comes_back_when_it_is_asked_for():
    listed = await project_use_cases.list_projects(OWNER, held, include_workspace=True)

    assert config.WORKSPACE_PROJECT in names(listed)
    assert len(listed) == 3


async def test_the_workspace_is_told_by_name_whatever_the_case():
    assert project_use_cases.is_workspace(project(config.WORKSPACE_PROJECT.upper()))
    assert not project_use_cases.is_workspace(project("Campaña"))


async def test_the_drafts_project_stays_listed():
    listed = await project_use_cases.list_projects(OWNER, held)

    assert config.DRAFTS_PROJECT in names(listed)


async def test_a_manager_does_not_see_a_members_workspace_either():
    listed = await management.list_organization_projects(ORGANIZATION, held_by_organization)

    assert names(listed) == ["Campaña", config.DRAFTS_PROJECT]
