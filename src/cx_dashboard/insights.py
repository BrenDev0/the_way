"""The second row of the dashboard: growth over a year, conversion and sales cycle, how
fast the team answers, which ads bring buyers, social reach, retention and NPS.

Pure functions like metrics.py: records in, a JSON-ready section out.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from . import config
from .metrics import UNKNOWN, Period, _change, _value, channel_of_message, outliers, parse_time

# --- growth -----------------------------------------------------------------------------


def month_starts(now: datetime, tz: ZoneInfo, months: int = config.GROWTH_MONTHS) -> list[datetime]:
    """The first instant of each of the last `months` calendar months, local time, oldest
    first; the last one is the current month."""
    local = now.astimezone(tz)
    year, month = local.year, local.month
    starts = []
    for _ in range(months):
        starts.append(datetime(year, month, 1, tzinfo=tz))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return list(reversed(starts))


def _month_of(moment: datetime, tz: ZoneInfo) -> date:
    local = moment.astimezone(tz)
    return date(local.year, local.month, 1)


def growth(
    starts: Sequence[datetime],
    leads_per_month: Sequence[int],
    opportunities: Sequence[dict],
    transactions: Sequence[dict] | None,
    now: datetime,
) -> dict:
    """Month by month: leads, new opportunities, deals won and money in. Growth compares
    the last whole month with the one before and with the same month a year earlier --
    the current month is still running, so it is shown but never compared."""
    tz = starts[0].tzinfo
    months = [date(s.year, s.month, 1) for s in starts]
    created = Counter()
    won = Counter()
    won_value = defaultdict(float)
    odd = {id(o) for o in outliers(opportunities)}
    for deal in opportunities:
        made = parse_time(deal.get("createdAt"))
        if made is not None:
            created[_month_of(made, tz)] += 1
        if deal.get("status") == "won":
            closed = parse_time(deal.get("lastStatusChangeAt"))
            if closed is not None:
                won[_month_of(closed, tz)] += 1
                won_value[_month_of(closed, tz)] += 0 if id(deal) in odd else _value(deal)
    revenue = defaultdict(float)
    if transactions is not None:
        for t in transactions:
            when = parse_time(t.get("createdAt"))
            if when is not None and str(t.get("status") or "").lower() in PAID:
                revenue[_month_of(when, tz)] += float(t.get("amount") or 0)

    rows = [
        {
            "month": month.isoformat(),
            "leads": leads_per_month[index],
            "opportunities": created.get(month, 0),
            "won": won.get(month, 0),
            "wonValue": round(won_value.get(month, 0.0), 2),
            "revenue": round(revenue.get(month, 0.0), 2) if transactions is not None else None,
            "current": index == len(months) - 1,
        }
        for index, month in enumerate(months)
    ]

    def compare(measure: str) -> dict:
        if len(rows) < 3:
            return {"lastMonth": None, "monthOverMonth": None, "yearOverYear": None}
        last, before = rows[-2], rows[-3]
        year_ago = rows[-14] if len(rows) >= 14 else None
        value = last[measure]
        if value is None:
            return {"lastMonth": None, "monthOverMonth": None, "yearOverYear": None}
        return {
            "lastMonth": value,
            "monthOverMonth": _change(value, before[measure] or 0),
            "yearOverYear": _change(value, year_ago[measure] or 0) if year_ago else None,
        }

    return {
        "status": "ok",
        "months": rows,
        "leads": compare("leads"),
        "opportunities": compare("opportunities"),
        "wonValue": compare("wonValue"),
        "revenue": compare("revenue") if transactions is not None else None,
        "revenueScope": None if transactions is not None else config.SCOPES["payments"],
    }


# --- conversion and sales cycle ---------------------------------------------------------


def conversion(contacts: Sequence[dict], opportunities: Sequence[dict], period: Period) -> dict:
    """Of the leads that came in during the period: how many became an opportunity and
    how many bought. And how long a won deal takes, from opened to won."""
    leads = [c for c in contacts if period.contains(parse_time(c.get("dateAdded")))]
    with_opportunity = [c for c in leads if c.get("opportunities")]
    customers = [c for c in leads if any(o.get("status") == "won" for o in c.get("opportunities") or [])]

    cycles = []
    year_ago = period.end - timedelta(days=365)
    for deal in opportunities:
        if deal.get("status") != "won":
            continue
        opened, closed = parse_time(deal.get("createdAt")), parse_time(deal.get("lastStatusChangeAt"))
        if opened and closed and closed >= year_ago and closed >= opened:
            cycles.append((closed - opened).total_seconds() / 86400)

    def rate(part: int, whole: int) -> float | None:
        return round(part / whole, 4) if whole else None

    return {
        "status": "ok",
        "leads": len(leads),
        "withOpportunity": len(with_opportunity),
        "customers": len(customers),
        "leadToOpportunity": rate(len(with_opportunity), len(leads)),
        "leadToCustomer": rate(len(customers), len(leads)),
        "opportunityToCustomer": rate(len(customers), len(with_opportunity)),
        "cycleDays": round(median(cycles), 1) if cycles else None,
        "cycleSample": len(cycles),
    }


# --- first-response time ----------------------------------------------------------------

# Messages that are not someone talking: notes, stage changes, call logs the system writes.
NOT_SPEECH_PREFIX = "TYPE_ACTIVITY"
AUTOMATED_SOURCES = {"workflow", "campaign", "bulk_actions", "automation", "ai", "bot"}
INSTANT_SECONDS = 60


def _human_reply(message: dict) -> bool:
    if message.get("direction") != "outbound":
        return False
    if str(message.get("messageType") or "").startswith(NOT_SPEECH_PREFIX):
        return False
    source = str(message.get("source") or "").lower()
    return source not in AUTOMATED_SOURCES


def response_times(threads: Iterable[tuple[dict, Sequence[dict]]], period: Period, now: datetime) -> dict:
    """How long a client who writes waits for a person to answer. Every client message
    that follows silence on our side starts the clock; the first reply someone writes --
    not an automation -- stops it. One still unanswered counts as waiting until now."""
    waits: list[tuple[float, str, str | None, bool]] = []  # hours, channel, who answered, answered
    sampled = 0
    for conversation, messages in threads:
        sampled += 1
        pending: dict | None = None
        for message in messages:
            kind = str(message.get("messageType") or "")
            if kind.startswith(NOT_SPEECH_PREFIX):
                continue
            if message.get("direction") == "inbound":
                if pending is None:
                    pending = message
            elif pending is not None and _human_reply(message):
                asked, answered = parse_time(pending.get("dateAdded")), parse_time(message.get("dateAdded"))
                if asked and answered and period.contains(asked):
                    waits.append(((answered - asked).total_seconds() / 3600, channel_of_message(kind), message.get("userId"), True))
                pending = None
        if pending is not None:
            asked = parse_time(pending.get("dateAdded"))
            if asked and period.contains(asked):
                waits.append(((now - asked).total_seconds() / 3600, channel_of_message(pending.get("messageType")), None, False))

    answered = [w for w in waits if w[3]]
    hours = [w[0] for w in answered]
    # CX cannot tell a person from an AI agent replying as a user; a reply inside a minute
    # almost always is one. Shown apart, so the owner sees both what clients get and how
    # fast the people are.
    instant = [h for h in hours if h * 3600 < INSTANT_SECONDS]
    considered = [h for h in hours if h * 3600 >= INSTANT_SECONDS]
    by_channel: dict[str, list[float]] = defaultdict(list)
    by_person: dict[Any, list[float]] = defaultdict(list)
    for h, channel, who, _ in answered:
        by_channel[channel].append(h)
        by_person[who].append(h)

    def within(limit: float) -> float | None:
        return round(sum(1 for w in waits if w[3] and w[0] <= limit) / len(waits), 4) if waits else None

    return {
        "status": "ok",
        "sampled": sampled,
        "messages": len(waits),
        "answered": len(answered),
        "unanswered": len(waits) - len(answered),
        "medianHours": round(median(hours), 2) if hours else None,
        "instantShare": round(len(instant) / len(hours), 4) if hours else None,
        "medianHoursWithoutInstant": round(median(considered), 2) if considered else None,
        "within1h": within(1),
        "within24h": within(24),
        "byChannel": sorted(
            ({"name": name, "medianHours": round(median(v), 2), "count": len(v)} for name, v in by_channel.items()),
            key=lambda row: -row["count"],
        )[: config.TOP],
        "byPerson": sorted(
            ({"id": who, "medianHours": round(median(v), 2), "count": len(v)} for who, v in by_person.items() if who),
            key=lambda row: -row["count"],
        )[: config.TOP],
    }


# --- ads --------------------------------------------------------------------------------


def ads(contacts: Sequence[dict], period: Period) -> dict:
    """Each ad that brought leads in the period: how many, how many became opportunities,
    how many bought, and what those deals are worth. Spend lives in the ad platform, so
    cost per lead is not here -- what is here is which ads bring people who buy."""
    rows: dict[str, dict] = {}
    for contact in contacts:
        if not period.contains(parse_time(contact.get("dateAdded"))):
            continue
        attribution = contact.get("attributionSource") or {}
        name = attribution.get("adName")
        if not name:
            continue
        row = rows.setdefault(name, {"name": name, "leads": 0, "opportunities": 0, "won": 0, "value": 0.0})
        row["leads"] += 1
        deals = contact.get("opportunities") or []
        row["opportunities"] += bool(deals)
        row["won"] += any(o.get("status") == "won" for o in deals)
        row["value"] += sum(_value(o) for o in deals if o.get("status") in ("open", "won"))
    attributed = sum(r["leads"] for r in rows.values())
    leads = sum(1 for c in contacts if period.contains(parse_time(c.get("dateAdded"))))
    ranked = sorted(rows.values(), key=lambda r: (-r["leads"], r["name"]))
    for row in ranked:
        row["toOpportunity"] = round(row["opportunities"] / row["leads"], 4)
        row["value"] = round(row["value"], 2)
    candidates = [r for r in ranked if r["leads"] >= 3]
    best = max(candidates, key=lambda r: (r["won"], r["toOpportunity"], r["leads"]), default=None)
    return {
        "status": "ok",
        "ads": ranked[: config.TOP * 2],
        "attributed": attributed,
        "leads": leads,
        "attributedShare": round(attributed / leads, 4) if leads else None,
        "best": best["name"] if best else None,
    }


# --- social -----------------------------------------------------------------------------


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def social(accounts: Sequence[dict], statistics: dict, posts: Sequence[dict], period: Period) -> dict:
    """Reach and engagement across the connected profiles. CX's statistics always cover
    the last 7 days against the 7 before -- the card says so -- while the post count
    follows the dashboard's own period."""
    connected = [a for a in accounts if not a.get("deleted") and a.get("active", True)]
    expired = [a.get("platform") for a in connected if a.get("isExpired")]
    totals = statistics.get("totals") or {}
    breakdowns = statistics.get("breakdowns") or {}

    def change(metric: str) -> float | None:
        raw = _number((breakdowns.get(metric) or {}).get("totalChange"))
        return round(raw / 100, 4) if raw is not None else None

    engagement = breakdowns.get("engagement") or {}
    interactions = sum(
        (e.get("likes") or 0) + (e.get("comments") or 0) + (e.get("shares") or 0) for e in engagement.values() if isinstance(e, dict)
    )
    impressions = totals.get("impressions") or 0
    platforms = {}
    for metric in ("impressions", "posts"):
        for name, entry in ((breakdowns.get(metric) or {}).get("platforms") or {}).items():
            row = platforms.setdefault(name, {"name": name, "impressions": 0, "posts": 0, "engagement": 0, "change": None})
            row[metric] = entry.get("value") or 0
            if metric == "impressions":
                change_value = _number(entry.get("change"))
                row["change"] = round(change_value / 100, 4) if change_value is not None else None
    for name, entry in engagement.items():
        if isinstance(entry, dict):
            row = platforms.setdefault(name, {"name": name, "impressions": 0, "posts": 0, "engagement": 0, "change": None})
            row["engagement"] = (entry.get("likes") or 0) + (entry.get("comments") or 0) + (entry.get("shares") or 0)

    published = [p for p in posts if str(p.get("status") or "").lower() == "published" and period.contains(parse_time(p.get("publishedAt") or p.get("displayDate")))]
    return {
        "status": "ok",
        "accounts": len(connected),
        "expired": [e for e in expired if e],
        "window": "7d",
        "impressions": impressions,
        "impressionsChange": change("impressions"),
        "reach": (breakdowns.get("reach") or {}).get("total"),
        "reachChange": change("reach"),
        "interactions": interactions,
        "engagementRate": round(interactions / impressions, 4) if impressions else None,
        "newFollowers": totals.get("followers"),
        "postsLastWeek": totals.get("posts"),
        "postsInPeriod": len(published),
        "postsByPlatform": [{"name": n, "count": c} for n, c in Counter(str(p.get("platform") or UNKNOWN) for p in published).most_common()],
        "platforms": sorted(platforms.values(), key=lambda r: -r["impressions"]),
    }


# --- retention --------------------------------------------------------------------------

PAID = {"succeeded", "success", "paid", "completed"}
ACTIVE = {"active", "trialing"}
CANCELLED = {"canceled", "cancelled", "incomplete_expired", "unpaid"}
MONTHS_PER = {"day": 1 / 30, "week": 7 / 30, "month": 1, "year": 12}


def retention(transactions: Sequence[dict], subscriptions: Sequence[dict] | None, period: Period) -> dict:
    """Customers who come back: of everyone who paid in the last year, how many paid more
    than once, what a customer is worth, and how much of the period's money came from
    people who had bought before. With subscriptions: what recurs each month and who left."""
    paid = sorted(
        (t for t in transactions if str(t.get("status") or "").lower() in PAID and parse_time(t.get("createdAt"))),
        key=lambda t: parse_time(t["createdAt"]),
    )
    customer_of = lambda t: t.get("contactId") or (t.get("contactSnapshot") or {}).get("id") or t.get("contactEmail")  # noqa: E731
    by_customer: dict[Any, list[dict]] = defaultdict(list)
    for t in paid:
        if customer_of(t):
            by_customer[customer_of(t)].append(t)
    customers = len(by_customer)
    repeat = sum(1 for rows in by_customer.values() if len(rows) > 1)
    total = sum(float(t.get("amount") or 0) for t in paid)

    in_period = [t for t in paid if period.contains(parse_time(t["createdAt"]))]
    returning_value = 0.0
    for t in in_period:
        earlier = [x for x in by_customer.get(customer_of(t), []) if parse_time(x["createdAt"]) < period.start]
        if earlier:
            returning_value += float(t.get("amount") or 0)
    period_value = sum(float(t.get("amount") or 0) for t in in_period)

    result: dict[str, Any] = {
        "status": "ok",
        "customers": customers,
        "repeatCustomers": repeat,
        "repeatRate": round(repeat / customers, 4) if customers else None,
        "valuePerCustomer": round(total / customers, 2) if customers else None,
        "returningShare": round(returning_value / period_value, 4) if period_value else None,
        "subscriptions": None,
        "subscriptionsScope": None,
    }
    if subscriptions is None:
        result["subscriptionsScope"] = config.SCOPES["subscriptions"]
        return result

    active = [s for s in subscriptions if str(s.get("status") or "").lower() in ACTIVE]
    mrr = 0.0
    for s in active:
        amount = float(s.get("amount") or (s.get("recurringPrice") or {}).get("amount") or 0)
        interval = str(s.get("interval") or (s.get("recurringPrice") or {}).get("interval") or "month").lower()
        count = float(s.get("intervalCount") or (s.get("recurringPrice") or {}).get("intervalCount") or 1)
        mrr += amount / (MONTHS_PER.get(interval, 1) * count)
    cancelled = [
        s
        for s in subscriptions
        if str(s.get("status") or "").lower() in CANCELLED
        and period.contains(parse_time(s.get("canceledAt") or s.get("cancelledAt") or s.get("updatedAt")))
    ]
    at_start = len(active) + len(cancelled)
    result["subscriptions"] = {
        "active": len(active),
        "mrr": round(mrr, 2),
        "cancelled": len(cancelled),
        "churnRate": round(len(cancelled) / at_start, 4) if at_start else None,
    }
    return result


# --- NPS --------------------------------------------------------------------------------


def _score(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float) and float(value).is_integer() and 0 <= value <= 10:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit() and 0 <= int(value.strip()) <= 10:
        return int(value.strip())
    return None


def nps_field(submissions: Sequence[dict]) -> str | None:
    """Which answer is the 0-10 'how likely are you to recommend us': the field whose
    answers are all whole numbers from 0 to 10, the most often answered of those."""
    answered: Counter = Counter()
    disqualified: set = set()
    for submission in submissions:
        for key, value in (submission.get("others") or {}).items():
            if value in (None, ""):
                continue
            if _score(value) is None:
                disqualified.add(key)
            else:
                answered[key] += 1
    candidates = [(count, key) for key, count in answered.items() if key not in disqualified]
    return max(candidates)[1] if candidates else None


def _nps(scores: Sequence[int]) -> dict:
    promoters = sum(1 for s in scores if s >= 9)
    detractors = sum(1 for s in scores if s <= 6)
    return {
        "responses": len(scores),
        "score": round(100 * (promoters - detractors) / len(scores)) if scores else None,
        "promoters": promoters,
        "passives": len(scores) - promoters - detractors,
        "detractors": detractors,
    }


def nps(surveys: Sequence[dict], submissions: Sequence[dict], period: Period, survey_name: str | None) -> dict:
    """Net Promoter Score from a CX survey with a 0-10 question: % promoters (9-10) minus
    % detractors (0-6). Found by its answers, so any wording of the question works."""
    if not surveys:
        return {"status": "no_survey"}
    field = nps_field(submissions)
    if field is None:
        return {"status": "no_survey", "surveys": len(surveys)}

    def scored(rows: Iterable[dict]) -> list[tuple[datetime, int, dict]]:
        out = []
        for submission in rows:
            score = _score((submission.get("others") or {}).get(field))
            when = parse_time(submission.get("createdAt"))
            if score is not None and when is not None:
                out.append((when, score, submission))
        return out

    every = scored(submissions)
    current = [s for when, s, _ in every if period.contains(when)]
    previous = [s for when, s, _ in every if period.previous_start <= when < period.start]
    by_month: dict[date, list[int]] = defaultdict(list)
    for when, score, _ in every:
        local = when.astimezone(period.tz)
        by_month[date(local.year, local.month, 1)].append(score)

    comments = []
    for when, score, submission in sorted(every, key=lambda row: row[0], reverse=True):
        text = next(
            (str(v) for k, v in (submission.get("others") or {}).items() if k != field and isinstance(v, str) and len(v.strip()) >= 12 and "@" not in v),
            None,
        )
        if text and period.contains(when):
            comments.append({"score": score, "text": text[:280], "date": when.isoformat(), "name": submission.get("name")})
        if len(comments) >= 5:
            break

    now = _nps(current)
    before = _nps(previous)
    return {
        "status": "ok",
        "survey": survey_name,
        **now,
        "previousScore": before["score"],
        "change": (now["score"] - before["score"]) if now["score"] is not None and before["score"] is not None else None,
        "byMonth": [{"month": m.isoformat(), **_nps(v)} for m, v in sorted(by_month.items())][-12:],
        "comments": comments,
    }
