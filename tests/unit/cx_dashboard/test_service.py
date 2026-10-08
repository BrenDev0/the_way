from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.cx_dashboard import service
from src.cx_dashboard.client import InvalidToken, MissingScope

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)


class FakeCX:
    """Answers like an account whose key has no users or payments scope."""

    def __init__(self, fail_with=None):
        self.fail_with = fail_with

    async def _maybe_fail(self):
        if self.fail_with:
            raise self.fail_with("x")

    async def contacts(self, filters, limit):
        await self._maybe_fail()
        return [{"dateAdded": "2026-10-08T12:00:00Z"}], False

    async def contacts_count(self, filters):
        return 4

    async def opportunities(self, limit):
        await self._maybe_fail()
        return [{"id": "o1", "status": "open", "pipelineId": "p", "pipelineStageId": "s", "createdAt": "2026-10-01T00:00:00Z"}], False

    async def pipelines(self):
        return [{"id": "p", "name": "Ventas", "stages": [{"id": "s", "name": "Nuevo", "position": 0}]}]

    async def conversations(self, limit, **filters):
        return [{"id": "c1", "lastMessageDirection": "inbound", "lastMessageDate": 1791261683055}], False

    async def conversations_count(self, **filters):
        return 9

    async def calendars(self):
        return [{"id": "cal"}]

    async def events(self, calendar_id, start, end):
        return []

    async def users(self):
        raise MissingScope("/users/")

    async def transactions(self, start, end, limit):
        raise MissingScope("/payments/transactions")

    async def subscriptions(self, limit):
        raise MissingScope("/payments/subscriptions")

    async def messages(self, conversation_id, limit):
        return []

    async def surveys(self):
        raise MissingScope("/surveys/")

    async def survey_submissions(self, survey_id, start, end, limit):
        return []

    async def social_accounts(self):
        return []

    async def social_statistics(self, profile_ids):
        return {}

    async def social_posts(self, start, end, limit):
        return []

    async def location(self):
        return {"name": "Agencia", "timezone": "America/Mexico_City", "currency": "MXN"}

    async def tasks(self, limit):
        return [{"_id": "t1", "title": "Llamar", "completed": False, "dueDate": "2026-10-01T00:00:00Z", "assignedTo": "u1"}]


class BrokenCX(FakeCX):
    async def calendars(self):
        return [{"no-id": True, "id": None}, 42]  # a shape nobody expected


async def test_a_missing_scope_locks_only_its_own_section():
    result = await service.build(FakeCX(), 30, ZoneInfo("UTC"), now=NOW)

    assert result["connected"] is True and result["period"]["days"] == 30
    assert result["leads"]["status"] == "ok" and result["leads"]["total"] == 1
    assert result["inbox"]["unread"] == 9
    assert result["pipeline"]["open"] == 1
    assert result["payments"] == {"status": "missing_scope", "scope": "payments/transactions.readonly"}
    assert result["team"]["status"] == "partial" and result["team"]["scope"] == "users.readonly"


async def test_a_dead_key_is_said_once_instead_of_breaking_every_section():
    result = await service.build(FakeCX(fail_with=InvalidToken), 30, ZoneInfo("UTC"), now=NOW)

    assert result["invalidToken"] is True
    assert "leads" not in result


async def test_sales_without_the_opportunities_scope_asks_for_that_scope():
    result = await service.build(FakeCX(fail_with=MissingScope), 30, ZoneInfo("UTC"), now=NOW)

    assert result["sales"] == {"status": "missing_scope", "scope": "opportunities.readonly"}
    assert result["leads"]["status"] == "missing_scope"


async def test_the_new_sections_report_their_locks_and_a_broken_one_costs_only_itself():
    result = await service.build(BrokenCX(), 30, ZoneInfo("UTC"), now=NOW)

    assert result["retention"] == {"status": "missing_scope", "scope": "payments/transactions.readonly"}
    assert result["nps"] == {"status": "missing_scope", "scope": "surveys.readonly"}
    assert result["growth"]["status"] == "ok" and result["growth"]["revenue"] is None
    assert result["social"] == {"status": "ok", "accounts": 0}
    assert result["appointments"]["status"] == "error"
    assert result["leads"]["status"] == "ok"


async def test_the_business_zone_and_currency_come_from_the_account():
    result = await service.build(FakeCX(), 30, ZoneInfo("UTC"), now=NOW)

    assert result["account"] == {"name": "Agencia", "timezone": "America/Mexico_City", "currency": "MXN"}
    assert result["period"]["timezone"] == "America/Mexico_City"
    assert result["tasks"]["overdue"] == 1
    assert result["users"] == {}  # the users scope is missing in this fake
