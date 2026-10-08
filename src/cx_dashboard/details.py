"""The detail behind the dashboard's lists: one conversation and its messages, every
post with what it got, and the leads each ad brought.

Pure functions like metrics.py: CX records in, what the panel shows out.
"""

from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta
from . import config
from .engagement import _interactions, _published
from .metrics import UNKNOWN, Period, _value, channel_of_message, parse_time

# --- conversations ----------------------------------------------------------------------

# The channel a reply goes out on, named as CX's send endpoint names it. Email needs a
# subject and a body CX renders, and a call cannot be answered with text -- both are left
# to GoHighLevel itself.
REPLY_TYPES = {
    "TYPE_WHATSAPP": "WhatsApp",
    "TYPE_SMS": "SMS",
    "TYPE_INSTAGRAM": "IG",
    "TYPE_FACEBOOK": "FB",
    "TYPE_LIVE_CHAT": "Live_Chat",
    "TYPE_WEBCHAT": "Live_Chat",
    "TYPE_GMB": "GMB",
}

ACTIVITY = "TYPE_ACTIVITY"

# Meta lets a business answer on WhatsApp, Instagram and Messenger only within 24 hours of
# the client's last message; past it, only an approved template may open the chat again,
# and CX refuses a plain reply. Checked here first, so nobody writes into a closed window.
REPLY_WINDOW = {"WhatsApp": timedelta(hours=24), "IG": timedelta(hours=24), "FB": timedelta(hours=24)}


def _name(contact: dict) -> str | None:
    full = " ".join(filter(None, [contact.get("firstName"), contact.get("lastName")])).strip()
    return contact.get("contactName") or contact.get("name") or full or None


def reply_type(messages: Sequence[dict]) -> str | None:
    """Where an answer should go: the channel the client last wrote on, else the last
    channel used at all. None when that channel cannot be answered from here."""
    spoken = [m for m in messages if not str(m.get("messageType") or "").startswith(ACTIVITY)]
    ordered = sorted(spoken, key=lambda m: str(m.get("dateAdded") or ""))
    inbound = [m for m in ordered if m.get("direction") == "inbound"]
    last = (inbound or ordered or [None])[-1]
    return REPLY_TYPES.get(str(last.get("messageType"))) if last else None


def last_inbound(messages: Sequence[dict], kind: str | None, conversation: dict | None = None) -> datetime | None:
    """When the client last wrote on the channel a reply would use. Falls back on the
    conversation's own record when the loaded page holds none of their messages."""
    channel = next((k for k, v in REPLY_TYPES.items() if v == kind), None)
    times = [
        parse_time(m.get("dateAdded"))
        for m in messages
        if m.get("direction") == "inbound" and (channel is None or m.get("messageType") == channel)
    ]
    times = [t for t in times if t is not None]
    if times:
        return max(times)
    if conversation and kind == "WhatsApp":
        return parse_time(conversation.get("lastInboundWhatsappMessageDate"))
    return None


def reply_window(messages: Sequence[dict], kind: str | None, now: datetime, conversation: dict | None = None) -> dict:
    """Whether a reply can go out now, and until when. Channels without a window (SMS,
    web chat) are always open."""
    limit = REPLY_WINDOW.get(kind or "")
    if kind is None:
        return {"open": False, "closesAt": None, "lastInbound": None, "reason": "unsupported_channel"}
    if limit is None:
        return {"open": True, "closesAt": None, "lastInbound": None, "reason": None}
    last = last_inbound(messages, kind, conversation)
    if last is None:
        return {"open": False, "closesAt": None, "lastInbound": None, "reason": "window_closed"}
    closes = last + limit
    return {"open": now < closes, "closesAt": closes.isoformat(), "lastInbound": last.isoformat(), "reason": None if now < closes else "window_closed"}


def message_view(message: dict, users: dict[str, str]) -> dict:
    kind = str(message.get("messageType") or "")
    who = message.get("userId")
    when = parse_time(message.get("dateAdded")) or parse_time(message.get("dateUpdated"))
    return {
        "id": message.get("id"),
        "direction": message.get("direction") or "outbound",
        "kind": "activity" if kind.startswith(ACTIVITY) else "message",
        "channel": channel_of_message(kind),
        "body": str(message.get("body") or ""),
        "attachments": [str(a) for a in message.get("attachments") or [] if isinstance(a, str) and a.startswith("http")],
        "date": when.isoformat() if when else None,
        "status": message.get("status"),
        "sender": users.get(who) if who else None,
        "automated": message.get("direction") == "outbound" and not who,
    }


def conversation_view(
    conversation: dict, contact: dict, messages: Sequence[dict], before: str | None, users: dict[str, str], now: datetime
) -> dict:
    ordered = sorted(messages, key=lambda m: str(m.get("dateAdded") or ""))
    kind = reply_type(ordered)
    return {
        "id": conversation.get("id"),
        "contactId": conversation.get("contactId") or contact.get("id"),
        "name": _name(contact) or conversation.get("fullName") or conversation.get("contactName") or "Sin nombre",
        "phone": contact.get("phone"),
        "email": contact.get("email"),
        "tags": contact.get("tags") or [],
        "assignedTo": users.get(conversation.get("assignedTo")) if conversation.get("assignedTo") else None,
        "unread": conversation.get("unreadCount") or 0,
        "messages": [message_view(m, users) for m in ordered],
        "before": before,
        "replyType": kind,
        "replyChannel": next((channel_of_message(k) for k, v in REPLY_TYPES.items() if v == kind), None) if kind else None,
        "replyWindow": reply_window(ordered, kind, now, conversation),
    }


# --- posts ------------------------------------------------------------------------------


def _title(post: dict) -> str:
    youtube = post.get("youtubePostDetails") or {}
    title = str(youtube.get("title") or "").strip()
    caption = " ".join(str(post.get("summary") or "").split())
    if title:
        return title
    return (caption[:90] + "…") if len(caption) > 90 else (caption or "(sin texto)")


def post_view(post: dict, accounts: dict[str, dict], users: dict[str, str]) -> dict:
    like, comment, share = _interactions(post)
    when = _published(post) or parse_time(post.get("displayDate")) or parse_time(post.get("createdAt"))
    ids = post.get("accountIds") or ([post["accountId"]] if post.get("accountId") else [])
    profiles = [accounts[i] for i in ids if i in accounts]
    media = [
        {"url": m.get("url"), "thumbnail": m.get("thumbnail") or m.get("defaultThumb") or None, "type": m.get("type")}
        for m in post.get("media") or []
        if isinstance(m, dict) and str(m.get("url") or "").startswith("http")
    ]
    link = post.get("previewLink")
    creator = post.get("createdBy")
    return {
        "id": post.get("_id") or post.get("id"),
        "title": _title(post),
        "caption": str(post.get("summary") or "").strip(),
        "platform": post.get("platform") or UNKNOWN,
        "profiles": [p.get("name") for p in profiles if p.get("name")],
        "format": post.get("type") or "post",
        "status": post.get("status"),
        "publishedAt": when.isoformat() if when else None,
        "likes": like,
        "comments": comment,
        "shares": share,
        "engagement": like + comment + share,
        "media": media,
        "thumbnail": next((m["thumbnail"] for m in media if m["thumbnail"]), None)
        or next((m["url"] for m in media if str(m["type"] or "").startswith("image")), None),
        # what to show when there is no cover image: the video itself, first frame only
        "video": next((m["url"] for m in media if str(m["type"] or "").startswith("video") or str(m["url"]).lower().split("?")[0].endswith((".mp4", ".mov", ".webm"))), None),
        "link": link if isinstance(link, str) and link.startswith("http") else None,
        "tags": post.get("tags") or [],
        "createdBy": users.get(creator) if isinstance(creator, str) else None,
        "error": post.get("error") or None,
    }


def posts_view(posts: Sequence[dict], accounts: Sequence[dict], users: dict[str, str], period: Period) -> dict:
    """Every post of the period, newest first, with everything CX says about it."""
    by_id = {}
    for account in accounts:
        for key in ("id", "profileId", "oauthId"):
            if account.get(key):
                by_id[account[key]] = account
    rows = [post_view(p, by_id, users) for p in posts]
    inside = [r for r in rows if r["publishedAt"] and period.contains(parse_time(r["publishedAt"]))]
    inside.sort(key=lambda r: r["publishedAt"], reverse=True)
    measured = {r["platform"] for r in inside if r["engagement"]}
    return {
        "posts": inside,
        "networks": [{"name": n, "count": c, "measured": n in measured} for n, c in Counter(r["platform"] for r in inside).most_common()],
    }


# --- ads --------------------------------------------------------------------------------


def ads_view(contacts: Sequence[dict], pipelines: Sequence[dict], period: Period) -> dict:
    """Each ad of the period with the leads it brought: who, when, on which channel, and
    how far each got -- the only way to judge an ad from CX, which does not see spend."""
    stages = {
        stage.get("id"): (pipeline.get("name"), stage.get("name"))
        for pipeline in pipelines
        for stage in pipeline.get("stages") or []
    }
    ads: dict[str, dict] = {}
    for contact in contacts:
        added = parse_time(contact.get("dateAdded"))
        if not period.contains(added):
            continue
        attribution = contact.get("attributionSource") or {}
        name = attribution.get("adName")
        if not name:
            continue
        ad = ads.setdefault(name, {"name": name, "adId": attribution.get("adId"), "urls": Counter(), "leads": []})
        if attribution.get("url"):
            ad["urls"][attribution["url"].split("?")[0]] += 1
        deals = contact.get("opportunities") or []
        best = next((d for d in deals if d.get("status") == "won"), None) or next((d for d in deals if d.get("status") == "open"), None) or (deals[0] if deals else None)
        pipeline, stage = stages.get(best.get("pipelineStageId"), (None, None)) if best else (None, None)
        ad["leads"].append(
            {
                "contactId": contact.get("id"),
                "name": _name(contact) or contact.get("phone") or "Sin nombre",
                "date": added.isoformat(),
                "channel": (attribution.get("medium") or attribution.get("sessionSource") or UNKNOWN).lower(),
                "status": best.get("status") if best else None,
                "pipeline": pipeline,
                "stage": stage,
                "value": _value(best) if best else 0,
            }
        )
    shaped = []
    for ad in ads.values():
        leads = sorted(ad["leads"], key=lambda lead: lead["date"], reverse=True)
        with_deal = [lead for lead in leads if lead["status"]]
        won = [lead for lead in leads if lead["status"] == "won"]
        shaped.append(
            {
                "name": ad["name"],
                "adId": ad["adId"],
                "landing": ad["urls"].most_common(1)[0][0] if ad["urls"] else None,
                "leads": len(leads),
                "opportunities": len(with_deal),
                "won": len(won),
                "toOpportunity": round(len(with_deal) / len(leads), 4) if leads else None,
                "first": leads[-1]["date"] if leads else None,
                "last": leads[0]["date"] if leads else None,
                "byStage": [{"name": s, "count": c} for s, c in Counter(lead["stage"] or "sin oportunidad" for lead in leads).most_common()],
                "people": leads[: config.MAX_AD_LEADS],
            }
        )
    shaped.sort(key=lambda a: (-a["leads"], a["name"]))
    return {"ads": shaped}
