"""The dashboard, put together: every section read from CX at once, each one standing on
its own. A permission the token lacks locks that section -- saying which scope to add --
and the rest still show."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import config, engagement, insights, metrics
from .client import CXApiError, CXClient, InvalidToken, MissingScope, RateLimited

logger = logging.getLogger(__name__)

NPS_HINTS = ("nps", "recom", "satisf", "experiencia", "encuesta")


def date_range(field: str, start: datetime, end: datetime) -> list[dict]:
    return [{"field": field, "operator": "range", "value": {"gte": start.isoformat(), "lt": end.isoformat()}}]


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


async def _section(name: str, work: Callable[[], Awaitable[dict]]) -> dict:
    try:
        return await work()
    except MissingScope:
        return {"status": "missing_scope", "scope": config.SCOPES[name]}
    except InvalidToken:
        return {"status": "invalid_token"}
    except RateLimited:
        return {"status": "error", "message": "El CX pidió esperar (límite de solicitudes). Actualiza en un minuto."}
    except CXApiError as exc:
        logger.warning("cx dashboard section %s failed: %s", name, exc)
        return {"status": "error", "message": "El CX no respondió bien a esta sección. Intenta actualizar."}
    except Exception:  # noqa: BLE001 -- a record shaped unlike any seen must cost one card, not the page
        logger.exception("cx dashboard section %s broke", name)
        return {"status": "error", "message": "Esta sección no se pudo calcular con los datos del CX."}


class _Shared:
    """Reads more than one section needs, made once on first use. Each is a task, so two
    sections asking at once wait on the same request."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Future] = {}

    def get(self, key: str, make: Callable[[], Awaitable[Any]]) -> asyncio.Future:
        if key not in self._tasks:
            self._tasks[key] = asyncio.ensure_future(make())
        return self._tasks[key]

    def peek(self, key: str) -> asyncio.Future | None:
        return self._tasks.get(key)

    def close(self) -> None:
        # a section that failed may have left a shared read unawaited
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
            elif not task.cancelled():
                task.exception()


async def account(client: CXClient) -> dict | None:
    """The sub-account's own name, time zone and currency -- so days are the business's
    days and money its money, whoever opens the dashboard from wherever."""
    try:
        location = await client.location()
    except (MissingScope, InvalidToken, RateLimited, CXApiError):
        return None
    except Exception:  # noqa: BLE001 -- optional: without it the dashboard uses the browser's zone
        logger.exception("cx dashboard could not read the location")
        return None
    return {"name": location.get("name"), "timezone": location.get("timezone"), "currency": location.get("currency")}


def zone(name: str | None, fallback: Any) -> Any:
    try:
        return ZoneInfo(name) if name else fallback
    except (ZoneInfoNotFoundError, ValueError):
        return fallback


def user_name(user: dict) -> str | None:
    return user.get("name") or " ".join(filter(None, [user.get("firstName"), user.get("lastName")])) or user.get("email")


async def build(client: CXClient, days: int, tz: Any, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    business = await account(client)
    tz = zone((business or {}).get("timezone"), tz)
    period = metrics.period_ending(now, days, tz)
    months = insights.month_starts(now, tz)
    shared = _Shared()

    def opportunities():
        return shared.get("opportunities", lambda: client.opportunities(config.MAX_OPPORTUNITIES))

    def waiting():
        return shared.get(
            "waiting", lambda: client.conversations(config.MAX_WAITING_CONVERSATIONS, lastMessageDirection="inbound")
        )

    def contacts():
        return shared.get("contacts", lambda: client.contacts(date_range("dateAdded", period.start, period.end), config.MAX_CONTACTS))

    def users():
        return shared.get("users", client.users)

    def transactions():
        # a year and more of payments, for the period's total, growth and retention alike
        return shared.get(
            "transactions", lambda: client.transactions(months[0].isoformat(), now.isoformat(), config.MAX_TRANSACTIONS)
        )

    async def leads() -> dict:
        (rows, more), previous = await asyncio.gather(
            contacts(), client.contacts_count(date_range("dateAdded", period.previous_start, period.start))
        )
        return metrics.leads(rows, previous, period, more)

    async def inbox() -> dict:
        (rows, more), unread = await asyncio.gather(waiting(), client.conversations_count(status="unread"))
        return metrics.inbox(rows, unread, now, more)

    async def pipeline() -> dict:
        (rows, more), definitions = await asyncio.gather(opportunities(), client.pipelines())
        return metrics.pipeline(rows, definitions, now, more)

    async def sales() -> dict:
        rows, _ = await opportunities()
        return metrics.sales(rows, period)

    async def appointments() -> dict:
        calendars = await client.calendars()
        start, end = _ms(period.start), _ms(now + timedelta(days=config.UPCOMING_DAYS))
        found = await asyncio.gather(*(client.events(c["id"], start, end) for c in calendars if c.get("id")))
        result = metrics.appointments([event for events in found for event in events], period, now)
        return {**result, "calendars": len(calendars)}

    async def team() -> dict:
        (deals, _), (conversations, _) = await asyncio.gather(opportunities(), waiting())
        try:
            people = await users()
        except MissingScope:
            people = None
        result = metrics.team(deals, conversations, people)
        return result if people is not None else {**result, "scope": config.SCOPES["team"]}

    async def payments() -> dict:
        rows, more = await transactions()
        return metrics.payments(rows, period, more)

    async def growth() -> dict:
        bounds = [*months[1:], now]
        counts = await asyncio.gather(
            *(client.contacts_count(date_range("dateAdded", start, end)) for start, end in zip(months, bounds, strict=True))
        )
        deals, _ = await opportunities()
        try:
            paid, _ = await transactions()
        except MissingScope:
            paid = None
        return insights.growth(months, counts, deals, paid, now)

    async def conversion() -> dict:
        (rows, _), (deals, _) = await asyncio.gather(contacts(), opportunities())
        return insights.conversion(rows, deals, period)

    async def response() -> dict:
        recent, _ = await client.conversations(config.RESPONSE_SAMPLE)
        inside = [c for c in recent if period.contains(metrics.parse_time(c.get("lastMessageDate")))]
        threads = await asyncio.gather(*(client.messages(c["id"], config.MESSAGES_PER_CONVERSATION) for c in inside if c.get("id")))
        return insights.response_times(zip(inside, threads, strict=True), period, now)

    async def ads() -> dict:
        rows, _ = await contacts()
        return {**insights.ads(rows, period), "campaigns": engagement.campaigns(rows, period)}

    async def handovers() -> dict:
        rows, _ = await contacts()
        return engagement.handovers(rows, period)

    async def tasks() -> dict:
        rows = await client.tasks(config.MAX_TASKS)
        return engagement.tasks(rows, now, tz)

    async def social() -> dict:
        accounts = await client.social_accounts()
        profiles = [a["profileId"] for a in accounts if a.get("profileId") and not a.get("deleted")]
        if not profiles:
            return {"status": "ok", "accounts": 0}
        # posts reach back at least 90 days, so the best day and hour rest on enough of them
        since = min(period.start, now - timedelta(days=90))
        statistics, posts = await asyncio.gather(
            client.social_statistics(profiles), client.social_posts(since.isoformat(), now.isoformat(), config.MAX_POSTS)
        )
        return {
            **insights.social(accounts, statistics, posts, period),
            "content": engagement.posts(posts, period, now),
            "series": engagement.weekly_series(statistics),
            "networks": sorted({str(a.get("platform")) for a in accounts if a.get("platform") and not a.get("deleted")}),
        }

    async def retention() -> dict:
        paid, _ = await transactions()
        try:
            subscriptions, _ = await client.subscriptions(config.MAX_SUBSCRIPTIONS)
        except MissingScope:
            subscriptions = None
        return insights.retention(paid, subscriptions, period)

    async def nps() -> dict:
        surveys = await client.surveys()
        if not surveys:
            return {"status": "no_survey"}
        named = [s for s in surveys if any(hint in str(s.get("name") or "").lower() for hint in NPS_HINTS)]
        chosen = named or surveys
        found = await asyncio.gather(
            *(client.survey_submissions(s["id"], months[0].isoformat(), now.isoformat(), config.MAX_SUBMISSIONS) for s in chosen if s.get("id"))
        )
        submissions = [row for rows in found for row in rows]
        name = chosen[0].get("name") if len(chosen) == 1 else None
        return insights.nps(surveys, submissions, period, name)

    sections = {
        "leads": leads,
        "inbox": inbox,
        "pipeline": pipeline,
        "sales": sales,
        "appointments": appointments,
        "team": team,
        "payments": payments,
        "growth": growth,
        "conversion": conversion,
        "response": response,
        "ads": ads,
        "social": social,
        "retention": retention,
        "nps": nps,
        "handovers": handovers,
        "tasks": tasks,
    }
    try:
        # sales reads the opportunities, so it needs the pipeline's scope
        results = await asyncio.gather(
            *(_section(name if name in config.SCOPES else "pipeline", work) for name, work in sections.items())
        )
    finally:
        shared.close()

    if any(result.get("status") == "invalid_token" for result in results):
        return {"connected": True, "invalidToken": True, "generatedAt": now.isoformat()}

    names: dict[str, str] = {}
    task = shared.peek("users")
    if task is not None and task.done() and not task.cancelled() and task.exception() is None:
        names = {u["id"]: user_name(u) for u in task.result() if u.get("id") and user_name(u)}

    return {
        "connected": True,
        "generatedAt": now.isoformat(),
        "period": {"days": days, "start": period.start.isoformat(), "end": period.end.isoformat(), "timezone": str(tz)},
        "account": business,
        # every person the sections name by id, so the panel shows who, not "Usuario 1234"
        "users": names,
        **dict(zip(sections, results, strict=True)),
    }
