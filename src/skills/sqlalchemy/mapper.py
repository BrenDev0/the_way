from src.skills.domain import Skill, SkillCreate

from .models import SkillRow


def row_to_domain(row: SkillRow) -> Skill:
    return Skill(
        id=row.id,
        organization_id=row.organization_id,
        name=row.name,
        description=row.description,
        instructions=row.instructions,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def domain_create_to_row(skill: SkillCreate) -> SkillRow:
    return SkillRow(
        organization_id=skill.organization_id,
        name=skill.name,
        description=skill.description,
        instructions=skill.instructions,
        created_by=skill.created_by,
    )
