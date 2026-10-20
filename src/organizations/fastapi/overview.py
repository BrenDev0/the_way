"""The organization at a glance, for its owners and admins: seats, storage, the projects
nobody owns any more, and how much AI the team uses.

The numbers are worked out by the overview use cases from read ports; this only asks for
them and shapes the answer.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.auth.fastapi import dependencies as auth_dependencies
from src.invitations.fastapi import dependencies as invitations_dependencies
from src.invitations.ports import CountPendingForOrganizationFn
from src.users.domain import Role, User
from src.users.fastapi import dependencies as users_dependencies
from src.users.ports import CountUsersForOrganizationFn, ListUsersFn

from .. import use_cases as organizations_use_cases
from ..ports import GetOrganizationByIdFn, ListMonthlyUsageFn, ListProjectStorageFn
from . import dependencies as organizations_dependencies
from .schemas import OrganizationOverviewResponse, UsageResponse

router = APIRouter(tags=["organizations"])

Manager = Annotated[User, Depends(auth_dependencies.require_role(Role.OWNER, Role.ADMIN))]

MAX_USAGE_MONTHS = 12


@router.get("/me/overview", response_model=OrganizationOverviewResponse)
async def overview_route(
    current_user: Manager,
    get_organization_by_id_fn: Annotated[
        GetOrganizationByIdFn,
        Depends(organizations_dependencies.provide_get_organization_by_id_fn),
    ],
    count_users_for_organization_fn: Annotated[
        CountUsersForOrganizationFn,
        Depends(users_dependencies.provide_count_users_for_organization_fn),
    ],
    count_pending_for_organization_fn: Annotated[
        CountPendingForOrganizationFn,
        Depends(invitations_dependencies.provide_count_pending_for_organization_fn),
    ],
    list_users_fn: Annotated[ListUsersFn, Depends(users_dependencies.provide_list_users_fn)],
    list_project_storage_fn: Annotated[
        ListProjectStorageFn,
        Depends(organizations_dependencies.provide_list_project_storage_fn),
    ],
) -> OrganizationOverviewResponse:
    """Seats in use, who owns the organization, where the storage goes, and the projects
    left without an owner when someone was removed -- to reassign or delete."""
    overview = await organizations_use_cases.get_overview(
        organization_id=current_user.organization_id,
        get_organization_by_id_fn=get_organization_by_id_fn,
        count_users_for_organization_fn=count_users_for_organization_fn,
        count_pending_for_organization_fn=count_pending_for_organization_fn,
        list_users_fn=list_users_fn,
        list_project_storage_fn=list_project_storage_fn,
    )
    return OrganizationOverviewResponse.from_domain(overview)


@router.get("/me/usage", response_model=UsageResponse)
async def usage_route(
    current_user: Manager,
    list_monthly_usage_fn: Annotated[
        ListMonthlyUsageFn,
        Depends(organizations_dependencies.provide_list_monthly_usage_fn),
    ],
    months: Annotated[int, Query(ge=1, le=MAX_USAGE_MONTHS)] = 6,
) -> UsageResponse:
    """AI use per person and month: conversations and tokens -- read, written, and read
    from the prompt cache. A conversation counts in the month it started."""
    report = await organizations_use_cases.get_usage(
        organization_id=current_user.organization_id,
        months=months,
        now=datetime.now(UTC),
        list_monthly_usage_fn=list_monthly_usage_fn,
    )
    return UsageResponse.from_domain(report)
