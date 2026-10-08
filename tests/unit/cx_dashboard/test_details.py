from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.cx_dashboard import details, metrics

TZ = ZoneInfo("America/Mexico_City")
NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
PERIOD = metrics.period_ending(NOW, 30, TZ)


def iso(delta: timedelta) -> str:
    return (NOW - delta).isoformat().replace("+00:00", "Z")


def msg(direction, minutes, kind="TYPE_WHATSAPP", body="hola", user=None, **extra):
    return {"id": f"m{minutes}", "direction": direction, "messageType": kind, "body": body, "dateAdded": iso(timedelta(minutes=minutes)), "userId": user, **extra}


def test_a_reply_goes_out_on_the_channel_the_client_last_wrote_on():
    messages = [msg("inbound", 50, "TYPE_SMS"), msg("outbound", 40, "TYPE_SMS", user="u1"), msg("inbound", 30, "TYPE_INSTAGRAM"), msg("outbound", 5, "TYPE_ACTIVITY_OPPORTUNITY")]

    assert details.reply_type(messages) == "IG"
    assert details.reply_type([msg("outbound", 3)]) == "WhatsApp"  # nobody wrote in: the last channel used
    assert details.reply_type([msg("inbound", 3, "TYPE_EMAIL")]) is None  # left to GoHighLevel
    assert details.reply_type([]) is None


def test_a_conversation_reads_oldest_first_with_who_said_what():
    messages = [
        msg("outbound", 10, body="Claro, te paso precios", user="u1", status="read"),
        msg("inbound", 20, body="¿Precio?", attachments=["https://cdn/x.jpg", "not-a-url"]),
        msg("outbound", 15, kind="TYPE_ACTIVITY_EMPLOYEE_ACTION_LOG", body="Employee action log created"),
        msg("outbound", 12, body="Gracias por escribir"),  # nobody behind it
    ]

    view = details.conversation_view(
        {"id": "c1", "contactId": "k1", "assignedTo": "u1", "unreadCount": 2},
        {"id": "k1", "firstName": "Ana", "lastName": "López", "phone": "+52 999", "tags": ["kids"]},
        messages,
        "cursor-1",
        {"u1": "Brenda"},
        NOW,
    )

    assert (view["name"], view["assignedTo"], view["before"], view["replyType"], view["replyChannel"]) == ("Ana López", "Brenda", "cursor-1", "WhatsApp", "whatsapp")
    assert [m["body"] for m in view["messages"]] == ["¿Precio?", "Employee action log created", "Gracias por escribir", "Claro, te paso precios"]
    first, log, bot, person = view["messages"]
    assert first["attachments"] == ["https://cdn/x.jpg"] and first["direction"] == "inbound"
    assert log["kind"] == "activity"
    assert bot["automated"] is True and person["sender"] == "Brenda" and person["automated"] is False


def post(days, **extra):
    return {"_id": f"p{days}", "status": "published", "platform": "youtube", "type": "post", "publishedAt": iso(timedelta(days=days)),
            "summary": "Un video largo " * 10, "insights": {"like": 2, "comment": 1, "share": 0}, "accountIds": ["acc1"], **extra}


def test_posts_are_named_by_title_or_caption_and_carry_their_profiles():
    accounts = [{"id": "acc1", "name": "Soul Lens Studios", "platform": "youtube"}]
    posts = [
        post(1, youtubePostDetails={"title": "Cómo hacer un spot con IA"}, media=[{"url": "https://cdn/v.mp4", "type": "video/mp4", "thumbnail": "https://cdn/t.jpg"}], previewLink="https://yt/v"),
        post(2, platform="tiktok"),
        post(3, status="scheduled"),
        post(80),  # before the period
    ]

    view = details.posts_view(posts, accounts, {}, PERIOD)

    first = view["posts"][0]
    assert (first["title"], first["profiles"], first["thumbnail"], first["link"], first["engagement"]) == ("Cómo hacer un spot con IA", ["Soul Lens Studios"], "https://cdn/t.jpg", "https://yt/v", 3)
    assert view["posts"][1]["title"].endswith("…") and len(view["posts"][1]["title"]) == 91
    assert [p["id"] for p in view["posts"]] == ["p1", "p2"]  # newest first; scheduled and older left out
    assert view["networks"] == [{"name": "youtube", "count": 1, "measured": True}, {"name": "tiktok", "count": 1, "measured": True}]


def test_an_ad_lists_its_leads_and_how_far_each_got():
    pipelines = [{"id": "p", "name": "Comercial", "stages": [{"id": "s1", "name": "Nuevo"}, {"id": "s2", "name": "Propuesta"}]}]
    contacts = [
        {"id": "k1", "firstName": "Ana", "dateAdded": iso(timedelta(days=1)), "attributionSource": {"adName": "Kids", "adId": "123", "medium": "WhatsApp", "url": "https://x.mx/kids?fbclid=1"},
         "opportunities": [{"status": "open", "pipelineStageId": "s2", "monetaryValue": 999}]},
        {"id": "k2", "phone": "+52 1", "dateAdded": iso(timedelta(days=2)), "attributionSource": {"adName": "Kids", "url": "https://x.mx/kids"}},
        {"id": "k3", "firstName": "Old", "dateAdded": iso(timedelta(days=60)), "attributionSource": {"adName": "Kids"}},
    ]

    ad = details.ads_view(contacts, pipelines, PERIOD)["ads"][0]

    assert (ad["name"], ad["adId"], ad["landing"], ad["leads"], ad["opportunities"], ad["toOpportunity"]) == ("Kids", "123", "https://x.mx/kids", 2, 1, 0.5)
    assert ad["people"][0] == {"contactId": "k1", "name": "Ana", "date": iso(timedelta(days=1)).replace("Z", "+00:00"), "channel": "whatsapp",
                               "status": "open", "pipeline": "Comercial", "stage": "Propuesta", "value": 999}
    assert ad["people"][1]["name"] == "+52 1" and ad["people"][1]["status"] is None
    assert {s["name"]: s["count"] for s in ad["byStage"]} == {"Propuesta": 1, "sin oportunidad": 1}


def test_whatsapp_can_be_answered_only_within_24_hours_of_the_clients_last_message():
    fresh = [msg("inbound", 60 * 23), msg("outbound", 60, user="u1")]
    stale = [msg("inbound", 60 * 25), msg("outbound", 60, user="u1")]

    open_window = details.reply_window(fresh, "WhatsApp", NOW)
    closed = details.reply_window(stale, "WhatsApp", NOW)

    assert open_window["open"] is True and open_window["closesAt"] == (NOW + timedelta(hours=1)).isoformat()
    assert closed == {"open": False, "closesAt": (NOW - timedelta(hours=1)).isoformat(), "lastInbound": (NOW - timedelta(hours=25)).isoformat(), "reason": "window_closed"}
    # our own later messages never reopen it
    assert details.reply_window([*stale, msg("outbound", 1, user="u1")], "WhatsApp", NOW)["open"] is False


def test_the_window_counts_the_clients_messages_on_that_channel_only():
    messages = [msg("inbound", 60 * 2, "TYPE_SMS"), msg("inbound", 60 * 30, "TYPE_INSTAGRAM")]

    assert details.reply_window(messages, "IG", NOW)["open"] is False
    assert details.reply_window(messages, "SMS", NOW) == {"open": True, "closesAt": None, "lastInbound": None, "reason": None}
    assert details.reply_window([], "WhatsApp", NOW)["reason"] == "window_closed"
    assert details.reply_window([], None, NOW)["reason"] == "unsupported_channel"


def test_with_no_client_message_loaded_the_conversation_record_decides():
    conversation = {"lastInboundWhatsappMessageDate": int((NOW - timedelta(hours=2)).timestamp() * 1000)}

    assert details.reply_window([msg("outbound", 5, user="u1")], "WhatsApp", NOW, conversation)["open"] is True


def test_a_conversation_says_whether_it_can_be_answered():
    view = details.conversation_view({"id": "c"}, {}, [msg("inbound", 60 * 30)], None, {}, NOW)

    assert view["replyType"] == "WhatsApp" and view["replyWindow"]["open"] is False


def test_text_from_cx_never_names_the_platform_behind_it():
    from src.cx_dashboard.routes import as_cx

    assert as_cx("HighLevel: the LeadConnector number is blocked") == "CX: the CX number is blocked"
    assert as_cx("GoHighLevel and Go High Level and GHL said no") == "CX and CX and CX said no"
    assert as_cx("highlight this") == "highlight this"
    assert as_cx(None) is None
