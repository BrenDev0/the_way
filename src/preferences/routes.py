from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from src.auth import dependencies as auth_dependencies
from src.users.domain import User

from . import dependencies as preferences_dependencies
from . import mapper
from . import use_cases as preferences_use_cases
from .ports import (
    CreatePreferenceFn,
    DeletePreferenceForUserFn,
    ListPreferencesForUserFn,
)
from .schemas import (
    CreatePreferenceRequest,
    DeletePreferenceResponse,
    PreferenceResponse,
)

router = APIRouter(tags=["preferences"])

CurrentUser = Annotated[User, Depends(auth_dependencies.get_current_user)]
ListPreferences = Annotated[
    ListPreferencesForUserFn,
    Depends(preferences_dependencies.provide_list_preferences_for_user_fn),
]


@router.get("", response_model=list[PreferenceResponse])
async def list_preferences_route(
    current_user: CurrentUser, list_preferences_for_user_fn: ListPreferences
) -> list[PreferenceResponse]:
    preferences = await preferences_use_cases.list_preferences(
        user_id=current_user.id,
        list_preferences_for_user_fn=list_preferences_for_user_fn,
    )
    return [mapper.domain_to_preference_response(p) for p in preferences]


@router.post("", response_model=PreferenceResponse, status_code=status.HTTP_201_CREATED)
async def create_preference_route(
    payload: CreatePreferenceRequest,
    current_user: CurrentUser,
    list_preferences_for_user_fn: ListPreferences,
    create_preference_fn: Annotated[
        CreatePreferenceFn,
        Depends(preferences_dependencies.provide_create_preference_fn),
    ],
) -> PreferenceResponse:
    preference = await preferences_use_cases.remember(
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        text=payload.text,
        list_preferences_for_user_fn=list_preferences_for_user_fn,
        create_preference_fn=create_preference_fn,
    )
    return mapper.domain_to_preference_response(preference)


@router.delete("/{preference_id}", response_model=DeletePreferenceResponse)
async def delete_preference_route(
    preference_id: UUID,
    current_user: CurrentUser,
    delete_preference_for_user_fn: Annotated[
        DeletePreferenceForUserFn,
        Depends(preferences_dependencies.provide_delete_preference_for_user_fn),
    ],
) -> DeletePreferenceResponse:
    await preferences_use_cases.forget(
        preference_id=preference_id,
        user_id=current_user.id,
        delete_preference_for_user_fn=delete_preference_for_user_fn,
    )
    return DeletePreferenceResponse(detail="Preference deleted")
