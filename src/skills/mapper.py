from .domain import Skill
from .schemas import SkillResponse


def domain_to_skill_response(skill: Skill) -> SkillResponse:
    return SkillResponse(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        instructions=skill.instructions,
        created_by=skill.created_by,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )
