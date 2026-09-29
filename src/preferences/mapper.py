from .domain import Preference
from .schemas import PreferenceResponse


def domain_to_preference_response(preference: Preference) -> PreferenceResponse:
    return PreferenceResponse(
        id=preference.id,
        text=preference.text,
        created_at=preference.created_at,
    )
