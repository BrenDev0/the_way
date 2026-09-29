from src.preferences.domain import Preference, PreferenceCreate

from .models import PreferenceRow


def row_to_domain(row: PreferenceRow) -> Preference:
    return Preference(
        id=row.id,
        organization_id=row.organization_id,
        user_id=row.user_id,
        text=row.text,
        created_at=row.created_at,
    )


def domain_create_to_row(preference: PreferenceCreate) -> PreferenceRow:
    return PreferenceRow(
        organization_id=preference.organization_id,
        user_id=preference.user_id,
        text=preference.text,
    )
