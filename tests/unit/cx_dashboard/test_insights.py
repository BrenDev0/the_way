from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.cx_dashboard import insights, metrics

TZ = ZoneInfo("America/Mexico_City")
NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
PERIOD = metrics.period_ending(NOW, 30, TZ)


def iso(delta: timedelta) -> str:
    return (NOW - delta).isoformat().replace("+00:00", "Z")


def test_months_run_oldest_first_and_end_with_the_current_one():
    starts = insights.month_starts(NOW, TZ)

    assert len(starts) == 14
    assert (starts[0].year, starts[0].month) == (2025, 9)
    assert (starts[-1].year, starts[-1].month) == (2026, 10)


def test_growth_compares_the_last_whole_month_with_the_one_before_and_a_year_ago():
    starts = insights.month_starts(NOW, TZ)
    leads = [10] + [0] * 11 + [20, 3]  # Sep 2025 = 10, Sep 2026 = 20, Aug 2026 = 0
    leads[11] = 16
    deals = [{"status": "won", "createdAt": "2026-09-02T00:00:00Z", "lastStatusChangeAt": "2026-09-10T18:00:00Z", "monetaryValue": 500}]

    section = insights.growth(starts, leads, deals, transactions=None, now=NOW)

    assert section["leads"] == {"lastMonth": 20, "monthOverMonth": 0.25, "yearOverYear": 1.0}
    assert section["months"][-2]["wonValue"] == 500 and section["months"][-1]["current"] is True
    assert section["revenue"] is None and section["revenueScope"] == "payments/transactions.readonly"


def test_conversion_follows_the_period_leads_through_to_a_sale():
    contacts = [
        {"dateAdded": iso(timedelta(days=1)), "opportunities": [{"status": "won"}]},
        {"dateAdded": iso(timedelta(days=2)), "opportunities": [{"status": "open"}]},
        {"dateAdded": iso(timedelta(days=3)), "opportunities": []},
        {"dateAdded": iso(timedelta(days=3))},
    ]
    deals = [{"status": "won", "createdAt": iso(timedelta(days=12)), "lastStatusChangeAt": iso(timedelta(days=2))}]

    section = insights.conversion(contacts, deals, PERIOD)

    assert (section["leads"], section["withOpportunity"], section["customers"]) == (4, 2, 1)
    assert (section["leadToOpportunity"], section["leadToCustomer"], section["opportunityToCustomer"]) == (0.5, 0.25, 0.5)
    assert section["cycleDays"] == 10


def message(direction, minutes_ago, kind="TYPE_WHATSAPP", source=None, user=None):
    return {"direction": direction, "dateAdded": iso(timedelta(minutes=minutes_ago)), "messageType": kind, "source": source, "userId": user}


def test_the_clock_starts_at_the_clients_message_and_stops_at_a_persons_reply():
    thread = [
        message("inbound", 300),
        message("inbound", 290),  # same wait: the clock already runs
        message("outbound", 280, kind="TYPE_ACTIVITY_OPPORTUNITY"),  # a log line is nobody talking
        message("outbound", 270, source="workflow"),  # an automation does not count
        message("outbound", 240, source="app", user="u1"),  # an hour after the first message
        message("inbound", 100),
        message("outbound", 99.5, source="app", user="u2"),  # 30 seconds: likely an AI agent
        message("inbound", 30),  # still waiting
    ]

    section = insights.response_times([({"id": "c"}, thread)], PERIOD, NOW)

    assert (section["messages"], section["answered"], section["unanswered"]) == (3, 2, 1)
    assert section["medianHours"] == round((1 + 30 / 3600) / 2, 2)
    assert section["instantShare"] == 0.5 and section["medianHoursWithoutInstant"] == 1
    assert {p["id"] for p in section["byPerson"]} == {"u1", "u2"}


def test_ads_are_ranked_by_leads_with_what_they_turned_into():
    contacts = [
        {"dateAdded": iso(timedelta(days=d)), "attributionSource": {"adName": "Kids"}, "opportunities": opps}
        for d, opps in [(1, [{"status": "won", "monetaryValue": 900}]), (2, [{"status": "open", "monetaryValue": 100}]), (3, [])]
    ] + [{"dateAdded": iso(timedelta(days=1)), "attributionSource": {"adName": "Spot IA"}}, {"dateAdded": iso(timedelta(days=1))}]

    section = insights.ads(contacts, PERIOD)

    kids = section["ads"][0]
    assert (kids["name"], kids["leads"], kids["opportunities"], kids["won"], kids["value"]) == ("Kids", 3, 2, 1, 1000)
    assert section["attributedShare"] == 0.8 and section["best"] == "Kids"


def test_social_reads_the_weekly_statistics_and_counts_the_periods_posts():
    statistics = {
        "totals": {"posts": 2, "followers": 1, "impressions": 500},
        "breakdowns": {
            "impressions": {"total": 500, "totalChange": "347.11", "platforms": {"tiktok": {"value": 400, "change": "100.00"}, "instagram": {"value": 100, "change": 0}}},
            "reach": {"total": 60, "totalChange": "5.00"},
            "engagement": {"tiktok": {"likes": 10, "comments": 2, "shares": 3}, "instagram": {"likes": 5, "comments": 0, "shares": 0}},
        },
    }
    posts = [{"status": "published", "platform": "tiktok", "publishedAt": iso(timedelta(days=2))}, {"status": "draft", "platform": "tiktok"}]

    section = insights.social([{"platform": "tiktok"}, {"platform": "instagram", "isExpired": True}], statistics, posts, PERIOD)

    assert section["impressionsChange"] == 3.4711 and section["interactions"] == 20
    assert section["engagementRate"] == 0.04 and section["postsInPeriod"] == 1
    assert section["platforms"][0] == {"name": "tiktok", "impressions": 400, "posts": 0, "engagement": 15, "change": 1.0}
    assert section["expired"] == ["instagram"]


def test_retention_finds_customers_who_buy_again():
    paid = [
        {"status": "succeeded", "amount": 100, "contactId": "a", "createdAt": iso(timedelta(days=200))},
        {"status": "succeeded", "amount": 300, "contactId": "a", "createdAt": iso(timedelta(days=5))},
        {"status": "succeeded", "amount": 600, "contactId": "b", "createdAt": iso(timedelta(days=4))},
        {"status": "failed", "amount": 999, "contactId": "c", "createdAt": iso(timedelta(days=4))},
    ]
    subscriptions = [
        {"status": "active", "amount": 1200, "interval": "year"},
        {"status": "active", "amount": 300, "interval": "month"},
        {"status": "canceled", "amount": 300, "interval": "month", "canceledAt": iso(timedelta(days=3))},
    ]

    section = insights.retention(paid, subscriptions, PERIOD)

    assert (section["customers"], section["repeatCustomers"], section["repeatRate"]) == (2, 1, 0.5)
    assert section["valuePerCustomer"] == 500 and section["returningShare"] == round(300 / 900, 4)
    assert section["subscriptions"] == {"active": 2, "mrr": 400, "cancelled": 1, "churnRate": round(1 / 3, 4)}


def test_nps_finds_the_zero_to_ten_question_whatever_it_is_called():
    def answer(score, days, comment=""):
        return {"createdAt": iso(timedelta(days=days)), "name": "Cliente", "others": {"q_email": "x@y.com", "q_rec": score, "q_why": comment, "q_city": "Mérida"}}

    submissions = [answer(10, 1, "Excelente servicio, muy rápidos"), answer(9, 2), answer(7, 3), answer("3", 4, "Tardaron mucho en contestar"), answer(10, 45)]

    assert insights.nps_field(submissions) == "q_rec"
    section = insights.nps([{"id": "s", "name": "NPS"}], submissions, PERIOD, "NPS")

    assert (section["promoters"], section["passives"], section["detractors"]) == (2, 1, 1)
    assert section["score"] == 25 and section["previousScore"] == 100 and section["change"] == -75
    assert [c["score"] for c in section["comments"]] == [10, 3]


def test_no_survey_or_no_zero_to_ten_question_says_so():
    assert insights.nps([], [], PERIOD, None) == {"status": "no_survey"}
    assert insights.nps([{"id": "s"}], [{"others": {"q": "hola"}}], PERIOD, None)["status"] == "no_survey"
