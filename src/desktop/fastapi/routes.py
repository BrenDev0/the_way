import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from src.auth.fastapi import dependencies as auth_dependencies
from src.core.exceptions import ValidationError
from src.fastapi.schemas import ApiBaseModel
from src.users.domain import User

from .. import config, extract
from .. import tools as desktop_tools

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


class ExtractedTextResponse(ApiBaseModel):
    text: str


@router.post("/extract-text", response_model=ExtractedTextResponse)
async def extract_text_route(
    request: Request,
    name: Annotated[str, Query(min_length=1, max_length=255)],
    _current_user: Annotated[User, Depends(auth_dependencies.get_current_user)],
) -> ExtractedTextResponse:
    """The text of a PDF, Word or Excel file the desktop app read off the user's computer.
    The file is the body; nothing is stored, and the app hands the text to the agent."""
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > config.MAX_EXTRACT_BYTES:
        raise ValidationError(message="That file is too large to read", code="document_too_large")

    data = await request.body()
    if len(data) > config.MAX_EXTRACT_BYTES:
        raise ValidationError(message="That file is too large to read", code="document_too_large")

    return ExtractedTextResponse(text=await asyncio.to_thread(extract.text_of, data, name))
