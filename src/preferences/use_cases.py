"""Standing preferences: how the user wants things done, always in effect.

Distinct from skills, and the distinction is the whole point. A skill is a procedure the
model reaches for when a task matches it -- the listing is always in context, the content
is read on demand. That is right for "how to build a FastAPI module" and wrong for "never
expose password hashes", which has to hold on every turn, including the ones where nothing
prompts the model to go looking.
"""

from collections.abc import Sequence
from uuid import UUID

from src.core.exceptions import ConflictError, NotFoundError, ValidationError

from . import config
from .domain import Preference, PreferenceCreate
from .ports import (
    CreatePreferenceFn,
    DeletePreferenceForUserFn,
    ListPreferencesForUserFn,
)

HEADER = (
    "Standing preferences. These apply to every reply unless the user overrides them in "
    "this conversation; follow them without being asked and without mentioning them."
)


def _not_found() -> NotFoundError:
    return NotFoundError(message="Preference not found", code="preference_not_found")


def normalize(text: str) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        raise ValidationError(
            message="Nothing to remember -- the preference was empty",
            code="preference_empty",
        )
    if len(cleaned) > config.MAX_PREFERENCE_CHARS:
        raise ValidationError(
            message=(
                f"That preference is {len(cleaned)} characters; the limit is "
                f"{config.MAX_PREFERENCE_CHARS}. It is meant to be a standing rule, not a "
                "document -- shorten it, or write a skill instead."
            ),
            code="preference_too_long",
        )
    return cleaned


async def remember(
    organization_id: UUID,
    user_id: UUID,
    text: str,
    list_preferences_for_user_fn: ListPreferencesForUserFn,
    create_preference_fn: CreatePreferenceFn,
) -> Preference:
    cleaned = normalize(text)
    held = await list_preferences_for_user_fn(user_id)

    if any(existing.text.lower() == cleaned.lower() for existing in held):
        raise ConflictError(
            message=f"Already remembered: {cleaned}",
            code="preference_already_exists",
        )

    if len(held) >= config.MAX_PREFERENCES_PER_USER:
        raise ConflictError(
            message=(
                f"You already have {config.MAX_PREFERENCES_PER_USER} preferences. Remove a "
                "stale one before adding another."
            ),
            code="preference_limit_reached",
        )

    return await create_preference_fn(
        PreferenceCreate(organization_id=organization_id, user_id=user_id, text=cleaned)
    )


async def list_preferences(
    user_id: UUID, list_preferences_for_user_fn: ListPreferencesForUserFn
) -> Sequence[Preference]:
    return await list_preferences_for_user_fn(user_id)


async def forget(
    preference_id: UUID,
    user_id: UUID,
    delete_preference_for_user_fn: DeletePreferenceForUserFn,
) -> None:
    if not await delete_preference_for_user_fn(preference_id, user_id):
        raise _not_found()


def render(preferences: Sequence[Preference]) -> str:
    """The preferences as they go into the turn's context, or "" when there are none."""
    if not preferences:
        return ""
    return "\n".join([HEADER, *(f"- {preference.text}" for preference in preferences)])
