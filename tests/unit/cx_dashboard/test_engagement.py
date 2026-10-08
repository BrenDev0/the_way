from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.cx_dashboard import engagement, metrics

TZ = ZoneInfo("America/Mexico_City")
NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)  # a Thursday, 12:00 in Mexico City
PERIOD = metrics.period_ending(NOW, 30, TZ)


def iso(delta: timedelta) -> str:
    return (NOW - delta).isoformat().replace("+00:00", "Z")


def post(days, platform="instagram", kind="post", like=0, comment=0, share=0, status="published", caption="Hola"):
    return {"_id": f"{platform}{days}{like}", "status": status, "platform": platform, "type": kind, "publishedAt": iso(timedelta(days=days)),
            "insights": {"like": like, "comment": comment, "share": share}, "summary": caption, "media": [{"thumbnail": "https://img/x.jpg", "type": "video"}]}


def test_posts_are_summed_by_platform_and_format_with_the_best_ones_first():
    rows = [
        post(1, "tiktok", "reel", like=40, comment=5, share=5),
        post(2, "tiktok", "reel", like=10),
        post(3, "instagram", like=4, comment=1),
        post(4, "instagram", status="draft", like=999),  # not published: not counted
        post(60, "instagram", like=100),  # before the period
    ]

    section = engagement.posts(rows, PERIOD, NOW)

    assert (section["posts"], section["engagement"]) == (3, 65)
    assert section["byPlatform"][0] == {"name": "tiktok", "posts": 2, "likes": 50, "comments": 5, "shares": 5, "engagement": 60, "average": 30}
    assert [f["name"] for f in section["byFormat"]] == ["reel", "post"]
    assert section["top"][0]["engagement"] == 50 and section["top"][0]["thumbnail"] == "https://img/x.jpg"
    assert section["daysSinceLastPost"] == 1
    assert sum(w["posts"] for w in section["cadence"]) == 3


def test_the_best_day_needs_enough_posts_behind_it():
    # three Wednesday posts that do well, one huge Monday post
    wednesdays = [post(d, like=20) for d in (1, 8, 15)]
    rows = [*wednesdays, post(3, like=500)]

    section = engagement.posts(rows, PERIOD, NOW)

    assert section["bestWeekday"] == "miércoles"
    assert next(d for d in section["byWeekday"] if d["name"] == "lunes")["posts"] == 1


def test_open_and_late_tasks_are_counted_per_person():
    rows = [
        {"_id": "a", "title": "Llamar a Ana", "completed": False, "dueDate": iso(timedelta(days=3)), "assignedTo": "u1", "contactDetails": {"firstName": "Ana"}},
        {"_id": "b", "title": "Enviar cotización", "completed": False, "dueDate": iso(timedelta(hours=1)), "assignedTo": "u1"},
        {"_id": "c", "title": "Seguimiento", "completed": False, "dueDate": iso(-timedelta(days=2)), "assignedTo": "u2"},
        {"_id": "d", "title": "Hecha", "completed": True, "dueDate": iso(timedelta(days=9)), "assignedTo": "u2"},
    ]

    section = engagement.tasks(rows, NOW, TZ)

    assert (section["open"], section["overdue"], section["dueToday"]) == (3, 1, 1)
    assert section["byPerson"][0] == {"id": "u1", "open": 2, "overdue": 1}
    assert section["overdueList"][0] == {"id": "a", "title": "Llamar a Ana", "contact": "Ana", "daysLate": 3, "assignedTo": "u1"}


def test_handovers_count_leads_an_ai_agent_passed_to_a_person():
    contacts = [
        {"dateAdded": iso(timedelta(days=1)), "tags": ["Human Handover", "kids"]},
        {"dateAdded": iso(timedelta(days=2)), "tags": ["transferencia a humano"]},
        {"dateAdded": iso(timedelta(days=2)), "tags": ["kids"]},
        {"dateAdded": iso(timedelta(days=90)), "tags": ["human handover"]},  # before the period
    ]

    section = engagement.handovers(contacts, PERIOD)

    assert (section["leads"], section["handedOver"], section["handoverRate"]) == (3, 2, round(2 / 3, 4))
    assert section["tags"][0] == {"name": "kids", "count": 2}


def test_campaigns_come_from_the_landing_pages_utm_tags():
    contacts = [
        {"dateAdded": iso(timedelta(days=1)), "attributionSource": {"url": "https://x.mx/?utm_source=fb&utm_campaign=kids-oct"}, "opportunities": [{"status": "won"}]},
        {"dateAdded": iso(timedelta(days=1)), "attributionSource": {"url": "https://x.mx/?utm_campaign=kids-oct"}},
        {"dateAdded": iso(timedelta(days=1)), "attributionSource": {"url": "https://x.mx/"}},
    ]

    rows = engagement.campaigns(contacts, PERIOD)

    assert rows == [{"name": "kids-oct", "source": "fb", "leads": 2, "opportunities": 1, "won": 1}]


def test_the_weekly_series_reads_the_statistics_day_by_day():
    statistics = {"dayRange": ["Thu", "Fri"], "postPerformance": {"impressions": [112, 245], "likes": [3], "comments": None}}

    assert engagement.weekly_series(statistics) == [
        {"day": "Thu", "impressions": 112, "likes": 3, "comments": 0},
        {"day": "Fri", "impressions": 245, "likes": 0, "comments": 0},
    ]


def test_networks_that_report_no_per_post_numbers_are_set_apart():
    rows = [post(1, "instagram", like=6), post(2, "tiktok"), post(3, "tiktok"), post(4, "youtube")]

    section = engagement.posts(rows, PERIOD, NOW)

    assert section["unmeasured"] == ["tiktok", "youtube"]
    assert section["published"] == 4 and section["posts"] == 1 and section["average"] == 6
    assert [p["name"] for p in section["byPlatform"]] == ["instagram"]
    assert {p["name"]: p["count"] for p in section["postsByPlatform"]} == {"tiktok": 2, "instagram": 1, "youtube": 1}
