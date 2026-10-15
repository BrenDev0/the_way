"""An organization skill, put in front of the page builder.

The builder runs in its own two passes with no ReadSkill: a skill the conversation read
reached it only as far as the assistant retold it in the brief. Named on the call, the
skill's text and its reference files (a template, a stylesheet, a list of laws) go to both
passes whole, so the page is made the skill's way rather than the house's guess at it.
"""

from src.knowledge import skill_notes
from src.skills.domain import Skill

from . import config

HEADER = "=== SKILL: {name} (the organization's method for this page -- binding) ==="

GUIDANCE = (
    "Follow this skill where it bears on the page itself: its structure, copy rules, laws, "
    "template and stylesheets. Where it names a template or a stylesheet below, build from "
    "it rather than from the house defaults, and put any stylesheet inside the page as a "
    "<style> block -- the page must stand alone. A brand pack, when given, still decides "
    "colours, typefaces and logos. Steps that need someone's approval, a deploy or a "
    "command were settled before this call or are not yours: do not stop for them, and "
    "mark anything still undecided as [TK]."
)

LEFT_OUT = "Not included (over the budget, or a program the page cannot use): {files}."


def render(skill: Skill) -> str:
    sections = [
        HEADER.format(name=skill.name),
        GUIDANCE,
        "",
        skill_notes.note_for(skill.name) + skill.instructions.strip(),
    ]
    budget = config.MAX_SKILL_CHARS - len(sections[-1])
    left_out: list[str] = []
    for path in sorted(skill.files or {}):
        text = (skill.files or {})[path]
        if path.lower().endswith(config.SKILL_FILES_LEFT_OUT) or len(text) > budget:
            left_out.append(path)
            continue
        sections += ["", f"--- {skill.name}/{path} ---", text.strip()]
        budget -= len(text)
    if left_out:
        sections += ["", LEFT_OUT.format(files=", ".join(left_out))]
    return "\n".join(sections)
