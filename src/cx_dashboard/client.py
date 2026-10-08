"""The CX (GoHighLevel) REST API, read-only, for the dashboard.

The agent reaches CX through the vendor's MCP server, one operation at a time. A dashboard
needs whole result sets, quickly and the same way every time, so it calls the REST API
directly with the same private-integration token and location.
"""

import asyncio
from typing import Any

import httpx

from . import config


class MissingScope(Exception):
    """The token works but was not given the permission this read needs."""


class InvalidToken(Exception):
    """The token itself was refused: revoked, mistyped, or for another location."""


class RateLimited(Exception):
    pass


class CXApiError(Exception):
    def __init__(self, text: str, detail: str | None = None) -> None:
        super().__init__(text)
        # what CX itself said, worth showing a person -- "outside the 24 hour window"
        self.detail = detail


class CXClient:
    def __init__(self, token: str, location_id: str, http: httpx.AsyncClient | None = None) -> None:
        self.location_id = location_id
        self._http = http or httpx.AsyncClient(
            base_url=config.API_URL,
            timeout=config.TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {token}", "Version": config.API_VERSION, "Accept": "application/json"},
        )
        self._slots = asyncio.Semaphore(config.CONCURRENCY)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def request(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        for attempt in range(config.RETRIES + 1):
            async with self._slots:
                try:
                    response = await self._http.request(method, path, params=params, json=body)
                except httpx.HTTPError as exc:
                    raise CXApiError(f"CX did not answer ({type(exc).__name__})") from exc
                await asyncio.sleep(config.PAGE_PAUSE_SECONDS)
            if response.status_code != 429 or attempt == config.RETRIES:
                break
            # a whole dashboard is near CX's burst limit: wait the window out, then go on
            try:
                wait = float(response.headers.get("retry-after") or config.RETRY_AFTER_SECONDS)
            except ValueError:
                wait = config.RETRY_AFTER_SECONDS
            await asyncio.sleep(min(wait, 10))

        if response.status_code in (401, 403):
            text = response.text.lower()
            # GHL answers 401 for both; only the wording tells a missing scope from a bad token
            if "scope" in text or response.status_code == 403:
                raise MissingScope(path)
            raise InvalidToken(path)
        if response.status_code == 429:
            raise RateLimited(path)
        if response.status_code >= 400:
            try:
                said = response.json().get("message")
            except ValueError:
                said = None
            detail = " ".join(said) if isinstance(said, list) else (str(said) if said else None)
            raise CXApiError(f"{method} {path} answered {response.status_code}: {response.text[:200]}", detail=detail)
        try:
            return response.json()
        except ValueError as exc:
            raise CXApiError(f"{method} {path} did not answer JSON") from exc

    # --- the reads the dashboard makes ----------------------------------------------

    async def contacts_count(self, filters: list[dict]) -> int:
        data = await self.request(
            "POST", "/contacts/search", body={"locationId": self.location_id, "pageLimit": 1, "page": 1, "filters": filters}
        )
        return int(data.get("total") or 0)

    async def contacts(self, filters: list[dict], limit: int) -> tuple[list[dict], bool]:
        """Contacts matching `filters`, newest first, and whether there were more."""
        rows: list[dict] = []
        body: dict[str, Any] = {
            "locationId": self.location_id,
            "pageLimit": config.PAGE_SIZE,
            "filters": filters,
            "sort": [{"field": "dateAdded", "direction": "desc"}],
        }
        total = None
        while len(rows) < limit:
            data = await self.request("POST", "/contacts/search", body=body if rows else {**body, "page": 1})
            page = data.get("contacts") or []
            total = data.get("total", total)
            rows += page
            if len(page) < config.PAGE_SIZE or not page[-1].get("searchAfter"):
                break
            body = {**body, "searchAfter": page[-1]["searchAfter"]}
            body.pop("page", None)
        more = (total is not None and total > len(rows)) or len(rows) > limit
        return rows[:limit], more

    async def opportunities(self, limit: int) -> tuple[list[dict], bool]:
        rows: list[dict] = []
        params: dict[str, Any] = {"location_id": self.location_id, "limit": config.PAGE_SIZE}
        total = None
        while len(rows) < limit:
            data = await self.request("GET", "/opportunities/search", params=params)
            page = data.get("opportunities") or []
            meta = data.get("meta") or {}
            total = meta.get("total", total)
            rows += page
            if len(page) < config.PAGE_SIZE or not meta.get("startAfterId"):
                break
            params = {**params, "startAfter": meta.get("startAfter"), "startAfterId": meta["startAfterId"]}
        more = (total is not None and total > len(rows)) or len(rows) > limit
        return rows[:limit], more

    async def pipelines(self) -> list[dict]:
        data = await self.request("GET", "/opportunities/pipelines", params={"locationId": self.location_id})
        return data.get("pipelines") or []

    async def conversations_count(self, **filters: Any) -> int:
        data = await self.request("GET", "/conversations/search", params={"locationId": self.location_id, "limit": 1, **filters})
        return int(data.get("total") or 0)

    async def conversations(self, limit: int, **filters: Any) -> tuple[list[dict], bool]:
        """Conversations matching `filters`, most recent message first."""
        rows: list[dict] = []
        params: dict[str, Any] = {
            "locationId": self.location_id,
            "limit": config.PAGE_SIZE,
            "sortBy": "last_message_date",
            "sort": "desc",
            **filters,
        }
        total = None
        while len(rows) < limit:
            data = await self.request("GET", "/conversations/search", params=params)
            page = data.get("conversations") or []
            total = data.get("total", total)
            rows += page
            cursor = (page[-1].get("sort") or [None])[0] if page else None
            if len(page) < config.PAGE_SIZE or cursor is None:
                break
            params = {**params, "startAfterDate": cursor}
        more = (total is not None and total > len(rows)) or len(rows) > limit
        return rows[:limit], more

    async def calendars(self) -> list[dict]:
        data = await self.request("GET", "/calendars/", params={"locationId": self.location_id})
        return data.get("calendars") or []

    async def events(self, calendar_id: str, start_ms: int, end_ms: int) -> list[dict]:
        data = await self.request(
            "GET",
            "/calendars/events",
            params={"locationId": self.location_id, "calendarId": calendar_id, "startTime": start_ms, "endTime": end_ms},
        )
        return data.get("events") or []

    async def users(self) -> list[dict]:
        data = await self.request("GET", "/users/", params={"locationId": self.location_id})
        return data.get("users") or []

    async def transactions(self, start_iso: str, end_iso: str, limit: int) -> tuple[list[dict], bool]:
        rows: list[dict] = []
        offset = 0
        total = None
        while len(rows) < limit:
            data = await self.request(
                "GET",
                "/payments/transactions",
                params={
                    "altId": self.location_id,
                    "altType": "location",
                    "startAt": start_iso,
                    "endAt": end_iso,
                    "limit": config.PAGE_SIZE,
                    "offset": offset,
                },
            )
            page = data.get("data") or []
            total = data.get("totalCount", total)
            rows += page
            if len(page) < config.PAGE_SIZE:
                break
            offset += len(page)
        more = (total is not None and total > len(rows)) or len(rows) > limit
        return rows[:limit], more

    async def subscriptions(self, limit: int) -> tuple[list[dict], bool]:
        rows: list[dict] = []
        offset = 0
        total = None
        while len(rows) < limit:
            data = await self.request(
                "GET",
                "/payments/subscriptions",
                params={"altId": self.location_id, "altType": "location", "limit": config.PAGE_SIZE, "offset": offset},
            )
            page = data.get("data") or []
            total = data.get("totalCount", total)
            rows += page
            if len(page) < config.PAGE_SIZE:
                break
            offset += len(page)
        more = (total is not None and total > len(rows)) or len(rows) > limit
        return rows[:limit], more

    async def messages(self, conversation_id: str, limit: int) -> list[dict]:
        """A conversation's latest messages, oldest first."""
        data = await self.request("GET", f"/conversations/{conversation_id}/messages", params={"limit": limit})
        wrapper = data.get("messages") or {}
        rows = wrapper.get("messages") if isinstance(wrapper, dict) else wrapper
        return sorted(rows or [], key=lambda message: str(message.get("dateAdded") or ""))

    async def surveys(self) -> list[dict]:
        data = await self.request("GET", "/surveys/", params={"locationId": self.location_id})
        return data.get("surveys") or []

    async def survey_submissions(self, survey_id: str, start_iso: str, end_iso: str, limit: int) -> list[dict]:
        rows: list[dict] = []
        page = 1
        while len(rows) < limit:
            data = await self.request(
                "GET",
                "/surveys/submissions",
                params={
                    "locationId": self.location_id,
                    "surveyId": survey_id,
                    "startAt": start_iso,
                    "endAt": end_iso,
                    "limit": config.PAGE_SIZE,
                    "page": page,
                },
            )
            batch = data.get("submissions") or []
            rows += batch
            if len(batch) < config.PAGE_SIZE:
                break
            page += 1
        return rows[:limit]

    async def social_accounts(self) -> list[dict]:
        data = await self.request("GET", f"/social-media-posting/{self.location_id}/accounts")
        return (data.get("results") or {}).get("accounts") or []

    async def social_statistics(self, profile_ids: list[str]) -> dict:
        data = await self.request(
            "POST", "/social-media-posting/statistics", params={"locationId": self.location_id}, body={"profileIds": profile_ids}
        )
        return data.get("results") or {}

    async def social_posts(self, start_iso: str, end_iso: str, limit: int) -> list[dict]:
        rows: list[dict] = []
        while len(rows) < limit:
            data = await self.request(
                "POST",
                f"/social-media-posting/{self.location_id}/posts/list",
                body={
                    "type": "all",
                    "skip": str(len(rows)),
                    "limit": str(config.PAGE_SIZE),
                    "fromDate": start_iso,
                    "toDate": end_iso,
                    "includeUsers": "false",
                },
            )
            batch = (data.get("results") or {}).get("posts") or []
            rows += batch
            if len(batch) < config.PAGE_SIZE:
                break
        return rows[:limit]

    async def location(self) -> dict:
        data = await self.request("GET", f"/locations/{self.location_id}")
        return data.get("location") or {}

    async def tasks(self, limit: int) -> list[dict]:
        """Open and done tasks of the location, newest first."""
        rows: list[dict] = []
        body: dict[str, Any] = {"limit": config.PAGE_SIZE}
        while len(rows) < limit:
            data = await self.request("POST", f"/locations/{self.location_id}/tasks/search", body=body)
            page = data.get("tasks") or []
            rows += page
            if len(page) < config.PAGE_SIZE or not page[-1].get("searchAfter"):
                break
            body = {**body, "searchAfter": page[-1]["searchAfter"]}
        return rows[:limit]

    async def conversation(self, conversation_id: str) -> dict:
        data = await self.request("GET", f"/conversations/{conversation_id}")
        return data.get("conversation") or data

    async def message_page(self, conversation_id: str, limit: int, before: str | None = None) -> tuple[list[dict], str | None]:
        """One page of a conversation's messages, newest first as CX gives them, and the
        cursor for the page before it (None at the start of the conversation)."""
        params: dict[str, Any] = {"limit": limit}
        if before:
            params["lastMessageId"] = before
        data = await self.request("GET", f"/conversations/{conversation_id}/messages", params=params)
        wrapper = data.get("messages") or {}
        rows = (wrapper.get("messages") if isinstance(wrapper, dict) else wrapper) or []
        more = isinstance(wrapper, dict) and wrapper.get("nextPage")
        return rows, (wrapper.get("lastMessageId") if more else None)

    async def contact(self, contact_id: str) -> dict:
        data = await self.request("GET", f"/contacts/{contact_id}")
        return data.get("contact") or {}

    async def send_message(self, kind: str, contact_id: str, message: str) -> dict:
        """Sends a message to a contact on a channel. The one write the dashboard makes."""
        return await self.request(
            "POST", "/conversations/messages", body={"type": kind, "contactId": contact_id, "message": message}
        )
