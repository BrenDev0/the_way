from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.cx_dashboard import metrics

TZ = ZoneInfo("America/Mexico_City")
NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
PERIOD = metrics.period_ending(NOW, 7, TZ)


def iso(delta: timedelta) -> str:
    return (NOW - delta).isoformat().replace("+00:00", "Z")


def ms(delta: timedelta) -> int:
    return int((NOW - delta).timestamp() * 1000)


def test_a_period_starts_at_local_midnight_and_covers_whole_days():
    assert PERIOD.start == datetime(2026, 10, 2, 0, 0, tzinfo=TZ)
    assert len(PERIOD.days_list()) == 7
    assert PERIOD.previous_start == PERIOD.start - (NOW - PERIOD.start)


def test_times_are_read_whether_iso_or_milliseconds():
    assert metrics.parse_time("2026-10-06T04:37:30.542Z") == datetime(2026, 10, 6, 4, 37, 30, 542000, tzinfo=UTC)
    assert metrics.parse_time(1791261683055).year == 2026
    assert metrics.parse_time("2026-07-30T13:00:00-06:00").utcoffset() == timedelta(hours=-6)
    assert metrics.parse_time(None) is None and metrics.parse_time("nope") is None


def test_leads_are_counted_by_day_channel_and_ad_against_the_period_before():
    contacts = [
        {"dateAdded": iso(timedelta(hours=1)), "attributionSource": {"medium": "WhatsApp", "adName": "Promo Kids"}},
        {"dateAdded": iso(timedelta(days=2)), "attributionSource": {"medium": "whatsapp", "adName": "Promo Kids"}},
        {"dateAdded": iso(timedelta(days=3)), "source": "Formulario web"},
        {"dateAdded": iso(timedelta(days=30))},  # outside the period
    ]

    section = metrics.leads(contacts, previous_total=2, period=PERIOD, truncated=False)

    assert section["total"] == 3
    assert section["change"] == 0.5
    assert section["byChannel"][0] == {"name": "whatsapp", "count": 2}
    assert section["byAd"] == [{"name": "Promo Kids", "count": 2}]
    assert sum(day["count"] for day in section["byDay"]) == 3 and len(section["byDay"]) == 7


def test_there_is_no_percentage_change_from_nothing():
    assert metrics.leads([], previous_total=0, period=PERIOD, truncated=False)["change"] is None


def test_the_inbox_puts_the_freshest_unanswered_first_and_buckets_the_backlog():
    waiting = [
        {"id": "old", "lastMessageDirection": "inbound", "lastMessageDate": ms(timedelta(days=90)), "lastMessageType": "TYPE_WHATSAPP"},
        {"id": "fresh", "lastMessageDirection": "inbound", "lastMessageDate": ms(timedelta(minutes=20)), "lastMessageType": "TYPE_INSTAGRAM", "fullName": "Ana"},
        {"id": "day", "lastMessageDirection": "inbound", "lastMessageDate": ms(timedelta(hours=5)), "lastMessageType": "TYPE_SMS"},
        {"id": "answered", "lastMessageDirection": "outbound", "lastMessageDate": ms(timedelta(hours=1))},
    ]

    section = metrics.inbox(waiting, unread=12, now=NOW, truncated=False)

    assert section["waiting"] == 3 and section["unread"] == 12
    assert [c["conversationId"] for c in section["toAnswer"]] == ["fresh", "day", "old"]
    assert section["toAnswer"][0]["channel"] == "instagram" and section["toAnswer"][0]["name"] == "Ana"
    assert [b["count"] for b in section["buckets"]] == [1, 1, 0, 0, 1]
    assert section["recent"] == 2


PIPELINES = [
    {"id": "p1", "name": "Ventas", "stages": [{"id": "s2", "name": "Propuesta", "position": 1}, {"id": "s1", "name": "Nuevo", "position": 0}]},
]


def deal(status="open", stage="s1", value=0, moved=timedelta(days=1), **extra):
    return {"id": extra.pop("id", f"d{value}{stage}"), "status": status, "pipelineId": "p1", "pipelineStageId": stage,
            "monetaryValue": value, "lastStageChangeAt": iso(moved), "createdAt": iso(moved), **extra}


def test_the_pipeline_counts_open_deals_by_stage_in_stage_order_and_finds_stale_ones():
    deals = [deal(value=100), deal(stage="s2", value=300, moved=timedelta(days=40)), deal(status="won", value=999)]

    section = metrics.pipeline(deals, PIPELINES, NOW, truncated=False)

    stages = section["pipelines"][0]["stages"]
    assert [s["name"] for s in stages] == ["Nuevo", "Propuesta"]
    assert [(s["count"], s["value"]) for s in stages] == [(1, 100), (1, 300)]
    assert section["open"] == 2 and section["openValue"] == 400
    assert section["stale"] == 1 and section["staleList"][0]["idleDays"] == 40
    assert section["staleList"][0]["stage"] == "Propuesta"


def test_amounts_that_look_mistyped_are_kept_out_of_the_value_and_named():
    deals = [deal(value=749, id="a"), deal(value=999, id="b"), deal(value=229, id="c"), deal(value=229_749_899_999, id="typo")]

    section = metrics.pipeline(deals, PIPELINES, NOW, truncated=False)

    assert section["openValue"] == 749 + 999 + 229
    warning = section["valueWarning"]
    assert warning["count"] == 1 and warning["examples"][0]["id"] == "typo"


def test_no_warning_when_amounts_are_ordinary():
    deals = [deal(value=v, id=str(v)) for v in (500, 900, 1500, 4000)]
    assert metrics.pipeline(deals, PIPELINES, NOW, truncated=False)["valueWarning"] is None


def test_sales_count_what_closed_inside_the_period():
    deals = [
        deal(status="won", value=1000, moved=timedelta(days=2), lastStatusChangeAt=iso(timedelta(days=2)), source="Anuncio"),
        deal(status="won", value=500, lastStatusChangeAt=iso(timedelta(days=60))),  # closed before
        deal(status="lost", lastStatusChangeAt=iso(timedelta(days=1))),
    ]

    section = metrics.sales(deals, PERIOD)

    assert (section["won"], section["wonValue"], section["lost"]) == (1, 1000, 1)
    assert section["winRate"] == 0.5 and section["averageWon"] == 1000
    assert {s["name"]: s["count"] for s in section["bySource"]} == {"sin dato": 2, "Anuncio": 1}


def test_appointments_split_into_the_period_and_the_coming_week():
    events = [
        {"id": "1", "startTime": iso(timedelta(days=1)), "appointmentStatus": "showed"},
        {"id": "2", "startTime": iso(timedelta(days=2)), "appointmentStatus": "noshow"},
        {"id": "3", "startTime": iso(timedelta(days=3)), "appointmentStatus": "cancelled"},
        {"id": "4", "startTime": iso(-timedelta(days=2)), "appointmentStatus": "confirmed", "title": "Demo"},
        {"id": "4", "startTime": iso(-timedelta(days=2)), "appointmentStatus": "confirmed"},  # same event, two calendars
        {"id": "5", "startTime": iso(-timedelta(days=3)), "appointmentStatus": "cancelled"},
    ]

    section = metrics.appointments(events, PERIOD, NOW)

    assert (section["showed"], section["noShow"], section["cancelled"]) == (1, 1, 1)
    assert section["showRate"] == 0.5
    assert section["upcoming"] == 1 and section["upcomingList"][0]["title"] == "Demo"


def test_the_team_without_the_users_scope_is_partial_and_known_by_id():
    deals = [deal(assignedTo="u1"), deal(assignedTo="u1", id="x"), deal(assignedTo=None, id="y")]
    waiting = [{"lastMessageDirection": "inbound", "assignedTo": "u2"}]

    partial = metrics.team(deals, waiting, users=None)
    named = metrics.team(deals, waiting, users=[{"id": "u1", "firstName": "Brenda", "lastName": "R"}])

    assert partial["status"] == "partial"
    assert {m["id"]: m["openOpportunities"] for m in partial["members"]} == {"u1": 2, None: 1, "u2": 0}
    assert partial["members"][-1]["name"] == "Sin asignar"
    assert next(m for m in named["members"] if m["id"] == "u1")["name"] == "Brenda R"


def test_payments_add_up_only_what_was_paid_in_the_period():
    transactions = [
        {"status": "succeeded", "amount": 1500, "currency": "mxn", "createdAt": iso(timedelta(days=1))},
        {"status": "failed", "amount": 900, "createdAt": iso(timedelta(days=1))},
        {"status": "succeeded", "amount": 700, "createdAt": iso(timedelta(days=40))},
    ]

    section = metrics.payments(transactions, PERIOD, truncated=False)

    assert (section["collected"], section["count"], section["currency"]) == (1500, 1, "MXN")
