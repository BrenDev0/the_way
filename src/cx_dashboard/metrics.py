"""What a business owner wants to know, worked out from the records CX returns.

Pure functions: records in, one dashboard section out, as JSON-ready dicts with the keys
the panel reads. Nothing here calls CX, so every figure can be checked against a handful
of hand-made records.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from . import config

UNKNOWN = "sin dato"


@dataclass(frozen=True)
class Period:
    start: datetime
    end: datetime
    tz: ZoneInfo

    @property
    def days(self) -> int:
        return max(1, round((self.end - self.start).total_seconds() / 86400))

    @property
    def previous_start(self) -> datetime:
        return self.start - (self.end - self.start)

    def contains(self, moment: datetime | None) -> bool:
        return moment is not None and self.start <= moment < self.end

    def local_day(self, moment: datetime) -> date:
        return moment.astimezone(self.tz).date()

    def days_list(self) -> list[date]:
        first, last = self.local_day(self.start), self.local_day(self.end - timedelta(microseconds=1))
        return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def period_ending(now: datetime, days: int, tz: ZoneInfo) -> Period:
    """The last `days` days up to now, starting at local midnight so each day is whole."""
    local_start = (now.astimezone(tz) - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return Period(start=local_start, end=now, tz=tz)


def parse_time(value: Any) -> datetime | None:
    """CX writes times as ISO strings in some places and epoch milliseconds in others."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000, tz=ZoneInfo("UTC"))
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo("UTC"))


def _change(current: float, previous: float) -> float | None:
    """The change against the previous period, as a fraction; None when there is nothing
    to compare with (a jump from zero is not a percentage)."""
    if not previous:
        return None
    return round((current - previous) / previous, 4)


def _top(counter: Counter, limit: int = config.TOP) -> list[dict]:
    return [{"name": name, "count": count} for name, count in counter.most_common(limit)]


def _hours_between(earlier: datetime, later: datetime) -> float:
    return round((later - earlier).total_seconds() / 3600, 1)


# --- leads ------------------------------------------------------------------------------


def channel_of(contact: dict) -> str:
    attribution = contact.get("attributionSource") or {}
    channel = attribution.get("medium") or attribution.get("sessionSource") or contact.get("source")
    return str(channel).strip().lower() if channel else UNKNOWN


def leads(contacts: Sequence[dict], previous_total: int, period: Period, truncated: bool) -> dict:
    """New contacts in the period: how many, against the period before, by day, by
    channel and by the ad that brought them."""
    inside = [c for c in contacts if period.contains(parse_time(c.get("dateAdded")))]
    per_day = Counter(period.local_day(parse_time(c["dateAdded"])) for c in inside)
    ads = Counter(
        (c.get("attributionSource") or {}).get("adName")
        for c in inside
        if (c.get("attributionSource") or {}).get("adName")
    )
    return {
        "status": "ok",
        "total": len(inside),
        "previous": previous_total,
        "change": _change(len(inside), previous_total),
        "perDay": round(len(inside) / period.days, 1),
        "byDay": [{"date": day.isoformat(), "count": per_day.get(day, 0)} for day in period.days_list()],
        "byChannel": _top(Counter(channel_of(c) for c in inside)),
        "byAd": _top(ads),
        "truncated": truncated,
    }


# --- inbox ------------------------------------------------------------------------------


CHANNELS = {
    "TYPE_WHATSAPP": "whatsapp",
    "TYPE_SMS": "sms",
    "TYPE_CALL": "llamada",
    "TYPE_EMAIL": "email",
    "TYPE_FACEBOOK": "facebook",
    "TYPE_INSTAGRAM": "instagram",
    "TYPE_GMB": "google",
    "TYPE_LIVE_CHAT": "chat web",
    "TYPE_WEBCHAT": "chat web",
}


def channel_of_message(kind: str | None) -> str:
    if not kind:
        return UNKNOWN
    return CHANNELS.get(kind, kind.removeprefix("TYPE_").replace("_", " ").lower())


def inbox(waiting: Sequence[dict], unread: int, now: datetime, truncated: bool) -> dict:
    """Conversations whose last word is the client's -- someone owes them an answer --
    and how long the longest have been left."""
    rows = []
    for conversation in waiting:
        if conversation.get("lastMessageDirection") != "inbound":
            continue
        last = parse_time(conversation.get("lastMessageDate"))
        if last is None:
            continue
        rows.append((conversation, _hours_between(last, now)))
    # shortest wait first: these are the ones still worth answering today
    rows.sort(key=lambda row: row[1])
    hours = [h for _, h in rows]
    return {
        "status": "ok",
        "unread": unread,
        "waiting": len(rows),
        "waitingOver24h": sum(1 for h in hours if h >= 24),
        "waitingUnder1h": sum(1 for h in hours if h < 1),
        # most accounts carry a long tail of leads nobody will answer now; what can still be
        # saved is the recent end
        "buckets": [
            {"label": "menos de 1 h", "count": sum(1 for h in hours if h < 1)},
            {"label": "1 a 24 h", "count": sum(1 for h in hours if 1 <= h < 24)},
            {"label": "1 a 7 días", "count": sum(1 for h in hours if 24 <= h < 24 * 7)},
            {"label": "1 a 4 semanas", "count": sum(1 for h in hours if 24 * 7 <= h < 24 * 30)},
            {"label": "más de 1 mes", "count": sum(1 for h in hours if h >= 24 * 30)},
        ],
        "recent": sum(1 for h in hours if h < 24 * 7),
        "medianWaitingHours": round(median(hours), 1) if hours else None,
        "byChannel": _top(Counter(channel_of_message(c.get("lastMessageType")) for c, _ in rows)),
        "toAnswer": [
            {
                "conversationId": c.get("id"),
                "contactId": c.get("contactId"),
                "name": c.get("fullName") or c.get("contactName") or "Sin nombre",
                "channel": channel_of_message(c.get("lastMessageType")),
                "preview": (c.get("lastMessageBody") or "")[:120],
                "waitingHours": h,
                "assignedTo": c.get("assignedTo"),
            }
            for c, h in rows[: config.TOP]
        ],
        "truncated": truncated,
    }


# --- pipeline and sales -----------------------------------------------------------------


def _value(opportunity: dict) -> float:
    try:
        return float(opportunity.get("monetaryValue") or 0)
    except (TypeError, ValueError):
        return 0.0


OUTLIER_FACTOR = 100


def outliers(opportunities: Sequence[dict]) -> list[dict]:
    """Amounts far beyond the account's typical deal -- prices typed run together, an extra
    few zeros. Kept out of the totals, which they would swamp, and named so someone fixes
    them. Typical is the median of the deals that have an amount."""
    valued = [o for o in opportunities if _value(o) > 0]
    if len(valued) < 3:
        return []
    typical = median(_value(o) for o in valued)
    return [o for o in valued if _value(o) > OUTLIER_FACTOR * typical]


def _value_warning(opportunities: Sequence[dict]) -> dict | None:
    odd = outliers(opportunities)
    if not odd:
        return None
    valued = [_value(o) for o in opportunities if _value(o) > 0]
    return {
        "count": len(odd),
        "value": sum(_value(o) for o in odd),
        "typical": median(valued),
        "examples": [{"id": o.get("id"), "name": o.get("name") or "Sin nombre", "value": _value(o)} for o in odd[: config.TOP]],
    }


def pipeline(opportunities: Sequence[dict], pipelines: Sequence[dict], now: datetime, truncated: bool) -> dict:
    """Open deals by pipeline and stage, what they are worth, and the ones nobody has moved."""
    open_deals = [o for o in opportunities if o.get("status") == "open"]
    odd = {id(o) for o in outliers(open_deals)}

    def worth(deals: Iterable[dict]) -> float:
        return sum(_value(o) for o in deals if id(o) not in odd)

    stage_names = {}
    shaped = []
    for definition in pipelines:
        stages = sorted(definition.get("stages") or [], key=lambda s: s.get("position", 0))
        in_pipeline = [o for o in open_deals if o.get("pipelineId") == definition.get("id")]
        by_stage = defaultdict(list)
        for deal in in_pipeline:
            by_stage[deal.get("pipelineStageId")].append(deal)
        for stage in stages:
            stage_names[stage.get("id")] = (definition.get("name"), stage.get("name"))
        shaped.append(
            {
                "id": definition.get("id"),
                "name": definition.get("name") or "Pipeline",
                "open": len(in_pipeline),
                "openValue": worth(in_pipeline),
                "stages": [
                    {
                        "id": stage.get("id"),
                        "name": stage.get("name") or "Etapa",
                        "count": len(by_stage.get(stage.get("id"), [])),
                        "value": worth(by_stage.get(stage.get("id"), [])),
                    }
                    for stage in stages
                ],
            }
        )
    shaped.sort(key=lambda p: p["open"], reverse=True)

    stale = []
    for deal in open_deals:
        moved = parse_time(deal.get("lastStageChangeAt")) or parse_time(deal.get("createdAt"))
        if moved is None:
            continue
        idle = (now - moved).days
        if idle >= config.STALE_DAYS:
            stale.append((deal, idle))
    stale.sort(key=lambda row: row[1], reverse=True)

    return {
        "status": "ok",
        "open": len(open_deals),
        # without amounts that look mistyped (valueWarning lists them)
        "openValue": worth(open_deals),
        "pipelines": shaped,
        "stale": len(stale),
        "staleDays": config.STALE_DAYS,
        "staleList": [
            {
                "id": deal.get("id"),
                "name": deal.get("name") or (deal.get("contact") or {}).get("name") or "Sin nombre",
                "pipeline": stage_names.get(deal.get("pipelineStageId"), (None, None))[0],
                "stage": stage_names.get(deal.get("pipelineStageId"), (None, None))[1],
                "idleDays": idle,
                "value": _value(deal),
                "assignedTo": deal.get("assignedTo"),
            }
            for deal, idle in stale[: config.TOP]
        ],
        "valueWarning": _value_warning(open_deals),
        "truncated": truncated,
    }


def sales(opportunities: Sequence[dict], period: Period) -> dict:
    """What was won and lost in the period, the close rate, and where new deals come from."""

    def closed(status: str) -> list[dict]:
        return [o for o in opportunities if o.get("status") == status and period.contains(parse_time(o.get("lastStatusChangeAt")))]

    won, lost, abandoned = closed("won"), closed("lost"), closed("abandoned")
    created = [o for o in opportunities if period.contains(parse_time(o.get("createdAt")))]
    sources: dict[str, dict] = {}
    for deal in created:
        name = (deal.get("source") or "").strip() or UNKNOWN
        entry = sources.setdefault(name, {"name": name, "count": 0, "won": 0, "value": 0.0})
        entry["count"] += 1
        entry["value"] += _value(deal)
        entry["won"] += deal.get("status") == "won"
    decided = len(won) + len(lost)
    won_value = sum(_value(o) for o in won)
    return {
        "status": "ok",
        "created": len(created),
        "won": len(won),
        "wonValue": won_value,
        "lost": len(lost),
        "abandoned": len(abandoned),
        "winRate": round(len(won) / decided, 4) if decided else None,
        "averageWon": round(won_value / len(won), 2) if won else None,
        "bySource": sorted(sources.values(), key=lambda s: s["count"], reverse=True)[: config.TOP],
    }


# --- appointments -----------------------------------------------------------------------


SHOWED = {"showed"}
NO_SHOW = {"noshow", "no_show"}
CANCELLED = {"cancelled", "canceled", "invalid"}


def appointments(events: Iterable[dict], period: Period, now: datetime) -> dict:
    """Appointments booked in the period, how many turned up, and the coming week."""
    past = Counter()
    upcoming = []
    horizon = now + timedelta(days=config.UPCOMING_DAYS)
    seen = set()
    for event in events:
        if event.get("deleted") or event.get("id") in seen:
            continue
        seen.add(event.get("id"))
        start = parse_time(event.get("startTime"))
        status = (event.get("appointmentStatus") or event.get("appoinmentStatus") or "").lower()
        if start is None:
            continue
        if period.contains(start):
            past["showed" if status in SHOWED else "noshow" if status in NO_SHOW else "cancelled" if status in CANCELLED else "pending"] += 1
        elif now <= start < horizon and status not in CANCELLED:
            upcoming.append((start, event, status))
    upcoming.sort(key=lambda row: row[0])
    attended = past["showed"] + past["noshow"]
    return {
        "status": "ok",
        "total": sum(past.values()),
        "showed": past["showed"],
        "noShow": past["noshow"],
        "cancelled": past["cancelled"],
        "pending": past["pending"],
        "showRate": round(past["showed"] / attended, 4) if attended else None,
        "upcoming": len(upcoming),
        "upcomingList": [
            {"id": event.get("id"), "title": event.get("title") or "Cita", "start": start.isoformat(), "status": status or "pendiente"}
            for start, event, status in upcoming[: config.TOP]
        ],
    }


# --- team -------------------------------------------------------------------------------


def team(opportunities: Sequence[dict], waiting: Sequence[dict], users: Sequence[dict] | None) -> dict:
    """Who holds the open deals and the unanswered conversations. Without the users scope
    the people are known only by id; the panel says what to add to see their names."""
    names = {u.get("id"): (u.get("name") or " ".join(filter(None, [u.get("firstName"), u.get("lastName")])) or u.get("email")) for u in users or []}
    open_by = Counter(o.get("assignedTo") or None for o in opportunities if o.get("status") == "open")
    waiting_by = Counter(c.get("assignedTo") or None for c in waiting if c.get("lastMessageDirection") == "inbound")
    people = set(open_by) | set(waiting_by)
    members = [
        {
            "id": person,
            "name": names.get(person) if person else "Sin asignar",
            "openOpportunities": open_by.get(person, 0),
            "waitingConversations": waiting_by.get(person, 0),
        }
        for person in people
    ]
    members.sort(key=lambda m: (m["id"] is None, -(m["waitingConversations"] + m["openOpportunities"])))
    return {"status": "ok" if users is not None else "partial", "members": members}


# --- payments ---------------------------------------------------------------------------


PAID = {"succeeded", "success", "paid", "completed"}


def payments(transactions: Sequence[dict], period: Period, truncated: bool) -> dict:
    paid = [t for t in transactions if str(t.get("status") or "").lower() in PAID and period.contains(parse_time(t.get("createdAt")))]
    per_day = Counter()
    for t in paid:
        per_day[period.local_day(parse_time(t["createdAt"]))] += float(t.get("amount") or 0)
    currencies = Counter(str(t.get("currency") or "").upper() for t in paid if t.get("currency"))
    total = sum(float(t.get("amount") or 0) for t in paid)
    return {
        "status": "ok",
        "collected": round(total, 2),
        "count": len(paid),
        "average": round(total / len(paid), 2) if paid else None,
        "currency": currencies.most_common(1)[0][0] if currencies else None,
        "byDay": [{"date": day.isoformat(), "amount": round(per_day.get(day, 0.0), 2)} for day in period.days_list()],
        "truncated": truncated,
    }
