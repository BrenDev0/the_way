"""Whether an organization's skills are actually read -- counted from the stored
conversations, not estimated.

    python -m src.skills.usage --email owner@example.com
    python -m src.skills.usage --email owner@example.com --days 7

Read only: it runs in a read-only transaction and writes nothing. It still reads whatever
DATABASE_URL points at, so it prints that host first -- check it is the database you mean.

What it sees: the conversation assistant's calls (ReadSkill, and a skill handed on through
BuildHtmlPage `skill` or StartBackgroundTask `skills`), and since 15 October 2026 a
background worker's own calls too. A task that ran before then has no calls recorded.
"""

import argparse
import asyncio
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Text, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.background import use_cases as background_use_cases
from src.background.sqlalchemy.models import BackgroundTaskRow
from src.conversations.sqlalchemy.models import ConversationRow, MessageRow

from .sqlalchemy.models import SkillRow

# The calls that say a skill was used, and where each carries its name(s).
READ = "ReadSkill"
HANDED_ON = {"BuildHtmlPage": "skill", "StartBackgroundTask": "skills"}
TASK_SKILLS_MARK = background_use_cases.SKILLS_TO_FOLLOW.split(".", 1)[0]


@dataclass
class SkillUse:
    reads: int = 0
    handed_on: int = 0
    worker_reads: int = 0
    conversations: set[UUID] = field(default_factory=set)
    last: datetime | None = None


@dataclass
class Usage:
    since: datetime
    skills: dict[str, SkillUse]
    conversations: int
    conversations_reading: int
    tasks: int
    tasks_with_skills: int
    tasks_reading: int = 0
    unknown: Counter[str] = field(default_factory=Counter)


def _names(call: dict) -> list[str]:
    args = call.get("args") or {}
    if call.get("name") == READ:
        return [args["name"]] if isinstance(args.get("name"), str) else []
    key = HANDED_ON.get(call.get("name", ""))
    value = args.get(key) if key else None
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def tally(
    skill_names: Iterable[str],
    calls: Iterable[tuple[UUID, datetime, Sequence[dict]]],
) -> tuple[dict[str, SkillUse], set[UUID], Counter[str]]:
    """Per skill: reads, hand-ons and the conversations they were in. A name the
    organization does not hold (a guess, or a skill since deleted) is counted apart."""
    skills = {name: SkillUse() for name in skill_names}
    reading: set[UUID] = set()
    unknown: Counter[str] = Counter()
    for conversation_id, at, tool_calls in calls:
        for call in tool_calls or ():
            for name in _names(call):
                use = skills.get(name.strip())
                if use is None:
                    unknown[name] += 1
                    continue
                if call.get("name") == READ:
                    use.reads += 1
                    reading.add(conversation_id)
                else:
                    use.handed_on += 1
                use.conversations.add(conversation_id)
                use.last = max(use.last or at, at)
    return skills, reading, unknown


def tally_workers(
    skills: dict[str, SkillUse],
    tasks: Iterable[tuple[UUID, datetime, Sequence[dict]]],
    unknown: Counter[str],
) -> set[UUID]:
    """Adds the workers' own reads and hand-ons; returns the tasks that read a skill."""
    reading: set[UUID] = set()
    for task_id, at, calls in tasks:
        for call in calls or ():
            for name in _names(call):
                use = skills.get(name.strip())
                if use is None:
                    unknown[name] += 1
                    continue
                if call.get("name") == READ:
                    use.worker_reads += 1
                    reading.add(task_id)
                else:
                    use.handed_on += 1
                use.last = max(use.last or at, at)
    return reading


async def measure(session: AsyncSession, organization_id: UUID, since: datetime) -> Usage:
    skill_names = (
        await session.scalars(select(SkillRow.name).where(SkillRow.organization_id == organization_id, SkillRow.owner_id.is_(None)))
    ).all()

    in_window = (ConversationRow.organization_id == organization_id) & (MessageRow.created_at >= since)
    names = [READ, *HANDED_ON]
    rows = (
        await session.execute(
            select(MessageRow.conversation_id, MessageRow.created_at, MessageRow.tool_calls)
            .join(ConversationRow, ConversationRow.id == MessageRow.conversation_id)
            .where(in_window, MessageRow.tool_calls.is_not(None))
            # only the messages holding one of these calls; the counting is done below
            .where(cast(MessageRow.tool_calls, Text).op("~")(f'"name": "({"|".join(names)})"'))
        )
    ).all()
    skills, reading, unknown = tally(
        skill_names, [(row.conversation_id, row.created_at, row.tool_calls or []) for row in rows]
    )

    conversations = await session.scalar(
        select(func.count(func.distinct(MessageRow.conversation_id)))
        .join(ConversationRow, ConversationRow.id == MessageRow.conversation_id)
        .where(in_window, MessageRow.role == "user")
    )
    task_window = (BackgroundTaskRow.organization_id == organization_id) & (BackgroundTaskRow.created_at >= since)
    tasks = await session.scalar(select(func.count()).select_from(BackgroundTaskRow).where(task_window))
    worker_calls = (
        await session.execute(
            select(BackgroundTaskRow.id, BackgroundTaskRow.created_at, BackgroundTaskRow.tool_calls).where(task_window)
        )
    ).all()
    tasks_reading = tally_workers(
        skills, [(row.id, row.created_at, row.tool_calls or []) for row in worker_calls], unknown
    )
    with_skills = await session.scalar(
        select(func.count())
        .select_from(BackgroundTaskRow)
        .where(task_window, BackgroundTaskRow.instructions.startswith(TASK_SKILLS_MARK))
    )
    return Usage(
        since=since,
        skills=skills,
        conversations=int(conversations or 0),
        conversations_reading=len(reading),
        tasks=int(tasks or 0),
        tasks_with_skills=int(with_skills or 0),
        tasks_reading=len(tasks_reading),
        unknown=unknown,
    )


def render(usage: Usage) -> str:
    def share(part: int, whole: int) -> str:
        return f"{part}/{whole}" + (f" ({part / whole:.0%})" if whole else "")

    lines = [
        f"Since {usage.since:%Y-%m-%d %H:%M} UTC",
        f"Conversations with a user message: {usage.conversations}",
        f"  ... that read at least one skill: {share(usage.conversations_reading, usage.conversations)}",
        f"Background tasks started: {usage.tasks}",
        f"  ... with skills to follow: {share(usage.tasks_with_skills, usage.tasks)}",
        f"  ... whose worker read at least one skill: {share(usage.tasks_reading, usage.tasks)}",
        "",
        f"{'skill':32} {'reads':>6} {'by workers':>10} {'handed on':>10} {'convs':>6}  last used",
    ]
    ordered = sorted(
        usage.skills.items(), key=lambda item: (-(item[1].reads + item[1].worker_reads), -item[1].handed_on, item[0])
    )
    for name, use in ordered:
        last = f"{use.last:%Y-%m-%d}" if use.last else "never"
        lines.append(
            f"{name:32} {use.reads:>6} {use.worker_reads:>10} {use.handed_on:>10} {len(use.conversations):>6}  {last}"
        )
    never = [
        name for name, use in usage.skills.items() if not use.reads and not use.worker_reads and not use.handed_on
    ]
    lines += ["", f"Never used in this window: {len(never)} of {len(usage.skills)} skills."]
    if usage.unknown:
        named = ", ".join(f"{name} ×{count}" for name, count in usage.unknown.most_common())
        lines.append(f"Names asked for that the organization does not hold: {named}")
    lines.append("(Workers' own calls are recorded from 15 October 2026; earlier tasks show none.)")
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--email", required=True, help="any member of the organization to measure")
    parser.add_argument("--days", type=int, default=30, help="how far back to look (default 30)")
    args = parser.parse_args(argv)

    from sqlalchemy.engine import make_url

    from src.core.cryptography.bcrypt.adapter import BcryptHashingService
    from src.core.database.sqlalchemy.core import async_session_factory
    from src.core.settings.shared import settings
    from src.users.sqlalchemy import adapter as users_adapter

    print(f"Reading (read only) from database host: {make_url(settings.DATABASE_URL).host}", file=sys.stderr)
    hashing = BcryptHashingService()
    async with async_session_factory() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        user = None
        for candidate in dict.fromkeys((args.email.strip(), args.email.strip().lower())):
            user = await users_adapter.get_user_by_email_hash(session, hashing.deterministic_hash(candidate))
            if user is not None:
                break
        if user is None:
            print(f"No user with the email {args.email}", file=sys.stderr)
            return 1
        usage = await measure(session, user.organization_id, datetime.now(UTC) - timedelta(days=args.days))
        await session.rollback()
    print(render(usage))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
