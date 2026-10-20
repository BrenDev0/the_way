from uuid import uuid4

import pytest
from helpers import make_user

from src.core.exceptions import NotFoundError
from src.projects.use_cases import management as management_use_cases


async def test_a_manager_resolves_any_project_in_their_organization(store, new_project, owner):
    project = await new_project()

    resolved = await management_use_cases.resolve_organization_project(
        project.id, owner.organization_id, store.get_project
    )

    assert resolved.id == project.id


async def test_a_manager_cannot_reach_another_organizations_project(store, new_project):
    project = await new_project()

    with pytest.raises(NotFoundError):
        await management_use_cases.resolve_organization_project(
            project.id, uuid4(), store.get_project
        )


async def test_managers_can_filter_projects_by_owner(store, new_project, owner):
    await new_project("Mine")
    colleague = make_user(organization_id=owner.organization_id)
    await new_project("Theirs", user=colleague)

    everything = await management_use_cases.list_organization_projects(
        owner.organization_id, store.list_projects_for_organization
    )
    theirs = await management_use_cases.list_organization_projects(
        owner.organization_id, store.list_projects_for_organization, owner_id=colleague.id
    )

    assert {p.name for p in everything} == {"Mine", "Theirs"}
    assert [p.name for p in theirs] == ["Theirs"]


async def test_a_project_transfers_to_a_colleague(store, new_project, owner):
    project = await new_project()
    colleague = make_user(organization_id=owner.organization_id)

    async def get_user_by_id_fn(user_id):
        return colleague if user_id == colleague.id else None

    transferred = await management_use_cases.transfer_project(
        project=project,
        new_owner_id=colleague.id,
        get_user_by_id_fn=get_user_by_id_fn,
        update_project_fn=store.update_project,
    )

    assert transferred.owner_id == colleague.id


async def test_a_project_cannot_transfer_outside_the_organization(store, new_project):
    project = await new_project()
    outsider = make_user()

    async def get_user_by_id_fn(_user_id):
        return outsider

    with pytest.raises(NotFoundError) as exc:
        await management_use_cases.transfer_project(
            project=project,
            new_owner_id=outsider.id,
            get_user_by_id_fn=get_user_by_id_fn,
            update_project_fn=store.update_project,
        )

    assert exc.value.code == "user_not_found"
