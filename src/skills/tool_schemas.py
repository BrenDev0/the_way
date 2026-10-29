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
    personal: bool = Field(
        default=False,
        description="true: a skill only for the person you are working for, which nobody else in "
        "the organization sees. false (the default): a skill for the whole organization. Only "
        "owners and admins can write organization skills; for everyone else a skill is always "
        "their own, whatever this says. When it is not clear which they want, ask.",
    )


class ImportSkill(BaseModel):
    """Keep a skill file the user brought -- one they wrote, or took from another service -- EXACTLY
    as written. Nothing is rewritten, improved or adapted. Asks them first.

    Read the skill file (ReadFile) in this conversation, then pass its whole text here. The name and
    description come from its `---` header (`name:`, `description:`, `triggers:`); if the header
    has no name, give one. A skill often points to reference files beside it -- templates, laws, a
    brief, a stylesheet: read each one the same way and pass it in `files`, or it is lost. Text files
    only; a logo, image or font cannot be kept in a skill (put it in a project and have the skill
    name its path)."""

    instructions: str = Field(description="The skill file's whole text, as read, header included")
    files: dict[str, str] | None = Field(
        default=None,
        description="Its reference files: each one's path as the skill names it (relative to the "
        "skill's folder, e.g. 'templates/report.html') mapped to its whole text, as read. At most "
        "30 files, 100,000 characters each and 400,000 in all. Leave it out to keep the files the "
        "skill already has when this replaces one.",
    )
    name: str | None = Field(
        default=None, description="A kebab-case name, when the file's header does not give one"
    )
    personal: bool = Field(
        default=False,
        description="true: only for the person you are working for. false: for the whole "
        "organization (owners and admins only; for everyone else it is always their own)",
    )


class DeleteMySkill(BaseModel):
    """Delete a skill of the user's OWN (marked "(yours)" in the skill listing). Asks them first.
    It never deletes an organization skill: those are managed by owners and admins elsewhere."""

    name: str = Field(description="The kebab-case name of the user's own skill")


class SaveSkill(BaseModel):
    """Save a skill, replacing any existing skill with the same name."""

    name: str = Field(description="The kebab-case skill name")
    description: str = Field(description="1-2 sentences: what it does and when to use it")
    instructions: str = Field(description="The full step-by-step instructions")
    triggers: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="2-5 requests a person would actually say when they need this skill, "
        "e.g. 'write the minutes for today's meeting'. Keep the existing ones that still fit",
    )
