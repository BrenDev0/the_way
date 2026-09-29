from typing import Annotated, Any

from fastapi import APIRouter, Depends

from src.auth import dependencies as auth_dependencies
from src.core.schemas import ApiBaseModel
from src.users.domain import User

from . import tools as desktop_tools

router = APIRouter(tags=["desktop-tools"])


class DesktopToolResponse(ApiBaseModel):
    name: str
    description: str
    # JSON Schema for the call's arguments, exactly as the model is shown it.
    parameters: dict[str, Any]
    requires_approval: bool


@router.get("", response_model=list[DesktopToolResponse])
async def list_desktop_tools_route(
    _current_user: Annotated[User, Depends(auth_dependencies.get_current_user)],
) -> list[DesktopToolResponse]:
    """The tools the desktop app is expected to carry out. Built from the same list the
    model is offered, so the app can check at start-up that it implements every one."""
    return [
        DesktopToolResponse(
            name=name,
            description=(tool.schema.__doc__ or "").strip(),
            parameters=tool.schema.model_json_schema(),
            requires_approval=tool.requires_approval,
        )
        for name, tool in desktop_tools.build().items()
    ]
