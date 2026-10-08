"""Posts, follow-ups, hand-offs and campaigns: what was published and how people
answered it, the team's open tasks, the chats an AI agent passed to a person, and which
campaigns bring leads.

Pure functions like metrics.py: records in, a JSON-ready section out.
"""

from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from . import config
from .metrics import UNKNOWN, Period, parse_time

# --- posts ------------------------------------------------------------------------------

WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
DAYPARTS = (("madrugada", 0, 6), ("mañana", 6, 12), ("tarde", 12, 18), ("noche", 18, 24))
# A day or time of day is named the best only with this many posts behind it.
MIN_POSTS_FOR_A_PATTERN = 3


def _interactions(post: dict) -> tuple[int, int, int]:
    insight = post.get("insights") or {}
    return int(insight.get("like") or 0), int(insight.get("comment") or 0), int(insight.get("share") or 0)


def _published(post: dict) -> datetime | None:
    if str(post.get("status") or "").lower() != "published":
        return None
    return parse_time(post.get("publishedAt") or post.get("displayDate"))


def _average(total: float, n: int) -> float | None:
    return round(total / n, 2) if n else None


def _summary(group: Sequence[tuple[dict, datetime]]) -> dict:
    likes = comments = shares = 0
    for post, _ in group:
        like, comment, share = _interactions(post)
        likes, comments, shares = likes + like, comments + comment, shares + share
    total = likes + comments + shares
    return {"posts": len(group), "likes": likes, "comments": comments, "shares": shares, "engagement": total, "average": _average(total, len(group))}


def _best(rows: Sequence[dict]) -> str | None:
    eligible = [r for r in rows if r["posts"] >= MIN_POSTS_FOR_A_PATTERN and r["average"]]
    return max(eligible, key=lambda r: r["average"])["name"] if eligible else None


def _shown(post: dict, when: datetime) -> dict:
    like, comment, share = _interactions(post)
    media = (post.get("media") or [{}])[0] or {}
    link = post.get("previewLink")
    kind = str(media.get("type") or "")
    return {
        "id": post.get("_id") or post.get("id"),
        "platform": post.get("platform") or UNKNOWN,
        "format": post.get("type") or "post",
        "caption": " ".join(str(post.get("summary") or "").split())[:160],
        "thumbnail": media.get("thumbnail") or media.get("defaultThumb") or (media.get("url") if kind.startswith("image") else None),
        "link": link if isinstance(link, str) and link.startswith("http") else None,
        "publishedAt": when.isoformat(),
        "likes": like,
        "comments": comment,
        "shares": share,
        "engagement": like + comment + share,
    }


def posts(rows: Sequence[dict], period: Period, now: datetime) -> dict:
    """What was published and how people answered it: per platform and format, the best
    day and time of day to post, how steady the posting is, and the posts that did best.
    Day and time patterns read every post fetched -- a longer window than the period --
    so a couple of posts do not decide them; everything else is the period's."""
    every = [(p, when) for p in rows if (when := _published(p)) is not None]
    # CX syncs per-post numbers for some networks only; where no post has a single like,
    # comment or share, zeros mean "not reported", and averaging them in would bury the
    # networks that do report. Those posts still count as published.
    measured = {str(p.get("platform") or UNKNOWN) for p, _ in every if sum(_interactions(p))}
    unmeasured = sorted({str(p.get("platform") or UNKNOWN) for p, _ in every} - measured)
    published = [(p, when) for p, when in every if str(p.get("platform") or UNKNOWN) in measured]
    inside = [(p, when) for p, when in published if period.contains(when)]
    posted = [(p, when) for p, when in every if period.contains(when)]

    def grouped(key: Callable[[dict], str]) -> list[dict]:
        groups: dict[str, list] = defaultdict(list)
        for post, when in inside:
            groups[key(post)].append((post, when))
        return sorted(({"name": name, **_summary(group)} for name, group in groups.items()), key=lambda r: -(r["average"] or 0))

    def pattern(key: Callable[[datetime], str], names: Sequence[str]) -> list[dict]:
        groups: dict[str, list] = defaultdict(list)
        for post, when in published:
            groups[key(when.astimezone(period.tz))].append((post, when))
        return [{"name": name, **_summary(groups.get(name, []))} for name in names]

    weekdays = pattern(lambda local: WEEKDAYS[local.weekday()], WEEKDAYS)
    dayparts = pattern(lambda local: next(n for n, a, b in DAYPARTS if a <= local.hour < b), [n for n, _, _ in DAYPARTS])

    weeks: Counter = Counter()
    for _, when in posted:
        local = when.astimezone(period.tz).date()
        weeks[local - timedelta(days=local.weekday())] += 1
    start = period.local_day(period.start)
    week = start - timedelta(days=start.weekday())
    cadence = []
    while week <= period.local_day(now):
        cadence.append({"week": week.isoformat(), "posts": weeks.get(week, 0)})
        week += timedelta(days=7)

    last = max((when for _, when in every), default=None)
    ranked = sorted(inside, key=lambda row: sum(_interactions(row[0])), reverse=True)
    return {
        **_summary(inside),
        "published": len(posted),
        "unmeasured": unmeasured,
        "perWeek": round(len(posted) / max(1, period.days / 7), 1),
        "daysSinceLastPost": (now - last).days if last else None,
        "byPlatform": grouped(lambda post: str(post.get("platform") or UNKNOWN)),
        "postsByPlatform": [{"name": n, "count": c} for n, c in Counter(str(p.get("platform") or UNKNOWN) for p, _ in posted).most_common()],
        "byFormat": grouped(lambda post: str(post.get("type") or "post")),
        "byWeekday": weekdays,
        "byDaypart": dayparts,
        "bestWeekday": _best(weekdays),
        "bestDaypart": _best(dayparts),
        "patternSample": len(published),
        "cadence": cadence,
        "top": [_shown(post, when) for post, when in ranked[:6]],
    }


# --- tasks ------------------------------------------------------------------------------


def _contact_name(task: dict) -> str | None:
    details = task.get("contactDetails") or {}
    return " ".join(filter(None, [details.get("firstName"), details.get("lastName")])) or details.get("name") or None


def tasks(rows: Sequence[dict], now: datetime, tz: ZoneInfo) -> dict:
    """The team's follow-ups: what is open, what is late, and whose."""
    open_tasks = [t for t in rows if not t.get("completed") and not t.get("deleted")]
    today = now.astimezone(tz).date()
    overdue: list[tuple[dict, int]] = []
    due_today = 0
    for task in open_tasks:
        due = parse_time(task.get("dueDate"))
        if due is None:
            continue
        local = due.astimezone(tz).date()
        if local < today:
            overdue.append((task, (today - local).days))
        elif local == today:
            due_today += 1
    overdue.sort(key=lambda row: -row[1])

    by_person: dict[Any, dict] = {}
    for task in open_tasks:
        who = task.get("assignedTo") or None
        by_person.setdefault(who, {"id": who, "open": 0, "overdue": 0})["open"] += 1
    for task, _ in overdue:
        by_person[task.get("assignedTo") or None]["overdue"] += 1

    return {
        "status": "ok",
        "open": len(open_tasks),
        "overdue": len(overdue),
        "dueToday": due_today,
        "byPerson": sorted(by_person.values(), key=lambda r: (r["id"] is None, -r["overdue"], -r["open"])),
        "overdueList": [
            {"id": task.get("_id") or task.get("id"), "title": task.get("title") or "Tarea", "contact": _contact_name(task), "daysLate": days, "assignedTo": task.get("assignedTo")}
            for task, days in overdue[: config.TOP]
        ],
    }


# --- tags and AI hand-offs --------------------------------------------------------------


def _handed_over(contact: dict) -> bool:
    return any(any(word in str(tag).lower() for word in config.HANDOVER_TAGS) for tag in contact.get("tags") or [])


def handovers(contacts: Sequence[dict], period: Period) -> dict:
    """Leads of the period by tag, and how many an AI agent handed to a person -- tagged
    with one of the hand-off tags agencies use."""
    leads = [c for c in contacts if period.contains(parse_time(c.get("dateAdded")))]
    tags = Counter(str(tag).strip().lower() for c in leads for tag in c.get("tags") or [] if str(tag).strip())
    handed = sum(1 for c in leads if _handed_over(c))
    return {
        "status": "ok",
        "leads": len(leads),
        "handedOver": handed,
        "handoverRate": round(handed / len(leads), 4) if leads else None,
        "tags": [{"name": name, "count": n} for name, n in tags.most_common(config.TOP * 2)],
    }


# --- campaigns --------------------------------------------------------------------------


def _utm(url: str | None, key: str) -> str | None:
    if not url or "?" not in url:
        return None
    values = parse_qs(urlsplit(url).query).get(key)
    return values[0].strip() if values and values[0].strip() else None


def campaigns(contacts: Sequence[dict], period: Period) -> list[dict]:
    """Leads by campaign, read from the utm_campaign of the page they landed on."""
    rows: dict[str, dict] = {}
    for contact in contacts:
        if not period.contains(parse_time(contact.get("dateAdded"))):
            continue
        url = (contact.get("attributionSource") or {}).get("url")
        name = _utm(url, "utm_campaign")
        if not name:
            continue
        row = rows.setdefault(name, {"name": name, "source": _utm(url, "utm_source"), "leads": 0, "opportunities": 0, "won": 0})
        row["leads"] += 1
        deals = contact.get("opportunities") or []
        row["opportunities"] += bool(deals)
        row["won"] += any(o.get("status") == "won" for o in deals)
    return sorted(rows.values(), key=lambda r: -r["leads"])[: config.TOP * 2]


# --- weekly social series ---------------------------------------------------------------


def weekly_series(statistics: dict) -> list[dict]:
    """The statistics' last seven days, day by day: impressions, likes and comments."""
    days = statistics.get("dayRange") or []
    performance = statistics.get("postPerformance") or {}

    def at(series: Any, index: int) -> int:
        return int(series[index]) if isinstance(series, list) and index < len(series) and series[index] is not None else 0

    return [
        {"day": name, "impressions": at(performance.get("impressions"), i), "likes": at(performance.get("likes"), i), "comments": at(performance.get("comments"), i)}
        for i, name in enumerate(days)
    ]
