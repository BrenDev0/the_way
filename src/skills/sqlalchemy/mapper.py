from src.skills.domain import Skill, SkillCreate

from .models import SkillRow


def row_to_domain(
    row: SkillRow, with_files: bool = True, file_names: list[str] | None = None
) -> Skill:
    if file_names is None:
        file_names = sorted(row.files or {}) if with_files else []
    return Skill(
        id=row.id,
        organization_id=row.organization_id,
        name=row.name,
        description=row.description,
        instructions=row.instructions,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        triggers=list(row.triggers or []),
        files=dict(row.files or {}) if with_files else None,
        file_names=sorted(file_names),
    )


def domain_create_to_row(skill: SkillCreate) -> SkillRow:
    return SkillRow(
        organization_id=skill.organization_id,
        name=skill.name,
        description=skill.description,
        instructions=skill.instructions,
        triggers=list(skill.triggers),
        files=dict(skill.files or {}),
        created_by=skill.created_by,
    )
