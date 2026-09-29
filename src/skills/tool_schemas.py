from pydantic import BaseModel, Field


class BuildSkill(BaseModel):
    """Create or update a "skill": a set of instructions every assistant in the
    organization can read later to reliably perform a specific recurring task. Use this
    when asked to create, build or package a skill, workflow, or reusable capability.
    Returns a short summary of what was created or changed."""

    skill_name: str = Field(
        description="A short, kebab-case name, e.g. 'pdf-report-generator'. Reuse the exact "
        "same name to update an existing skill rather than create a duplicate."
    )
    description: str = Field(
        description="A detailed brief of what the skill should do, when to use it, and any "
        "specific steps or conventions it needs. More detail -> a better skill."
    )


class SaveSkill(BaseModel):
    """Save a skill, replacing any existing skill with the same name."""

    name: str = Field(description="The kebab-case skill name")
    description: str = Field(description="1-2 sentences: what it does and when to use it")
    instructions: str = Field(description="The full step-by-step instructions")
