import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api import dependencies as api_dependencies
from src.api_keys.credentials import load_credentials
from src.api_keys.domain import Provider
from src.api_keys.sqlalchemy import adapter as api_keys_adapter
from src.auth import dependencies as auth_dependencies
from src.core.cache.ports import CacheStore
from src.core.cryptography.ports import EncryptionService
from src.core.database.sqlalchemy.dependencies import get_db_session
from src.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from src.core.schemas import ApiBaseModel
from src.users.domain import User

from . import config, details, metrics, service
from .client import CXApiError, CXClient, InvalidToken, MissingScope, RateLimited

router = APIRouter(tags=["cx-dashboard"])

# The platform behind CX is never named to users. Its own error text names it, so text
# from it is rewritten before the panel shows it.
VENDOR = re.compile(r"go\s*high\s*level|high\s*level|lead\s*connector|\bghl\b", re.IGNORECASE)


def as_cx(text: str | None) -> str | None:
    return VENDOR.sub("CX", text) if text else text

CurrentUser = Annotated[User, Depends(auth_dependencies.get_current_user)]
Session = Annotated[AsyncSession, Depends(get_db_session)]
Encryption = Annotated[EncryptionService, Depends(api_dependencies.get_encryption_service)]
Cache = Annotated[CacheStore, Depends(api_dependencies.get_cache_store)]


def _zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or config.DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(config.DEFAULT_TIMEZONE)


async def _credential(user: User, session: AsyncSession, encryption_service: EncryptionService):
    credentials = await load_credentials(user.id, lambda uid: api_keys_adapter.list_for_user(session, uid), encryption_service)
    credential = credentials.get(str(Provider.GOHIGHLEVEL))
    return credential if credential is not None and credential.account_id else None


@asynccontextmanager
async def _cx(user: User, session: AsyncSession, encryption_service: EncryptionService) -> AsyncIterator[CXClient]:
    """The person's own CX, for the detail routes: their key, their location. CX trouble
    becomes an error the panel can say plainly (never a 5xx, which the proxy hides)."""
    credential = await _credential(user, session, encryption_service)
    if credential is None:
        raise NotFoundError(message="Connect a CX key first", code="cx_not_connected")
    client = CXClient(token=credential.secret, location_id=credential.account_id)
    try:
        yield client
    except MissingScope as exc:
        raise AuthorizationError(message=f"The CX key is missing a permission for {exc}", code="cx_missing_scope") from exc
    except InvalidToken as exc:
        raise ValidationError(message="CX refused the key", code="cx_invalid_token") from exc
    except RateLimited as exc:
        raise ValidationError(message="CX asked to slow down", code="cx_rate_limited") from exc
    except CXApiError as exc:
        raise ValidationError(message=as_cx(exc.detail) or "CX could not answer", code="cx_error") from exc
    finally:
        await client.aclose()


async def _names(client: CXClient) -> dict[str, str]:
    try:
        users = await client.users()
    except MissingScope:
        return {}
    return {u["id"]: service.user_name(u) for u in users if u.get("id") and service.user_name(u)}


async def _period(client: CXClient, days: int, timezone: str | None):
    days = days if days in config.PERIODS else config.DEFAULT_PERIOD
    account = await service.account(client)
    tz = service.zone((account or {}).get("timezone"), _zone(timezone))
    return metrics.period_ending(datetime.now(UTC), days, tz)


@router.get("/dashboard")
async def dashboard_route(
    current_user: CurrentUser,
    session: Session,
    encryption_service: Encryption,
    cache: Cache,
    days: Annotated[int, Query()] = config.DEFAULT_PERIOD,
    timezone: Annotated[str | None, Query(alias="tz", max_length=64)] = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """The business at a glance, from the signed-in person's own CX key: leads, the inbox
    waiting on an answer, the pipeline, sales, appointments, the team and payments. Each
    section stands alone; one the key has no permission for says which scope to add."""
    days = days if days in config.PERIODS else config.DEFAULT_PERIOD
    tz = _zone(timezone)

    credential = await _credential(current_user, session, encryption_service)
    if credential is None:
        return {"connected": False}

    # per person and per location: changing the key's location must not show the old one
    key = f"cx-dashboard:{current_user.id}:{credential.account_id}:{days}:{tz.key}"
    if not refresh:
        cached = await cache.get_json(key)
        if cached is not None:
            return {**cached, "cached": True}

    client = CXClient(token=credential.secret, location_id=credential.account_id)
    try:
        result = await service.build(client, days, tz)
    finally:
        await client.aclose()

    if not result.get("invalidToken"):
        await cache.store_json(key, result, config.CACHE_SECONDS)
    return {**result, "cached": False}


@router.get("/conversations/{conversation_id}")
async def conversation_route(
    conversation_id: str,
    current_user: CurrentUser,
    session: Session,
    encryption_service: Encryption,
    before: Annotated[str | None, Query(max_length=128)] = None,
) -> dict[str, Any]:
    """One conversation with its latest messages; `before` loads the page before."""
    async with _cx(current_user, session, encryption_service) as client:
        conversation = await client.conversation(conversation_id)
        if conversation.get("locationId") not in (None, client.location_id):
            raise NotFoundError(message="Conversation not found", code="cx_conversation_not_found")
        (messages, cursor), names = await asyncio.gather(
            client.message_page(conversation_id, config.CONVERSATION_PAGE, before), _names(client)
        )
        contact = await client.contact(conversation["contactId"]) if conversation.get("contactId") else {}
        return details.conversation_view(conversation, contact, messages, cursor, names, datetime.now(UTC))


class ReplyRequest(ApiBaseModel):
    message: str = Field(min_length=1, max_length=config.MAX_REPLY_CHARS)


@router.post("/conversations/{conversation_id}/reply")
async def reply_route(
    conversation_id: str,
    payload: ReplyRequest,
    current_user: CurrentUser,
    session: Session,
    encryption_service: Encryption,
) -> dict[str, Any]:
    """Answers the client on the channel they last wrote on. Sends exactly one message;
    when CX refuses (WhatsApp's 24-hour window, a blocked number), says why instead."""
    text = payload.message.strip()
    if not text:
        raise ValidationError(message="Write a message", code="cx_reply_empty")
    async with _cx(current_user, session, encryption_service) as client:
        conversation = await client.conversation(conversation_id)
        if conversation.get("locationId") not in (None, client.location_id) or not conversation.get("contactId"):
            raise NotFoundError(message="Conversation not found", code="cx_conversation_not_found")
        recent, _ = await client.message_page(conversation_id, config.CONVERSATION_PAGE)
        kind = details.reply_type(recent)
        window = details.reply_window(recent, kind, datetime.now(UTC), conversation)
        if not window["open"]:
            # refused here, before CX: a closed window would only come back as an error
            return {"sent": False, "reason": window["reason"], "lastInbound": window["lastInbound"]}
        try:
            result = await client.send_message(kind, conversation["contactId"], text)
        except CXApiError as exc:
            return {"sent": False, "reason": "rejected", "detail": as_cx(exc.detail)}
        return {"sent": True, "messageId": result.get("messageId") or result.get("id"), "channel": kind}


@router.get("/posts")
async def posts_route(
    current_user: CurrentUser,
    session: Session,
    encryption_service: Encryption,
    days: Annotated[int, Query()] = config.DEFAULT_PERIOD,
    timezone: Annotated[str | None, Query(alias="tz", max_length=64)] = None,
) -> dict[str, Any]:
    """Every post published in the period, with all CX knows of each."""
    async with _cx(current_user, session, encryption_service) as client:
        period = await _period(client, days, timezone)
        accounts, names = await asyncio.gather(client.social_accounts(), _names(client))
        posts = await client.social_posts(period.start.isoformat(), period.end.isoformat(), config.MAX_POSTS)
        return details.posts_view(posts, accounts, names, period)


@router.get("/ads")
async def ads_route(
    current_user: CurrentUser,
    session: Session,
    encryption_service: Encryption,
    days: Annotated[int, Query()] = config.DEFAULT_PERIOD,
    timezone: Annotated[str | None, Query(alias="tz", max_length=64)] = None,
) -> dict[str, Any]:
    """Each ad of the period with the leads it brought and where they are now."""
    async with _cx(current_user, session, encryption_service) as client:
        period = await _period(client, days, timezone)
        (contacts, _), pipelines = await asyncio.gather(
            client.contacts(service.date_range("dateAdded", period.start, period.end), config.MAX_CONTACTS), client.pipelines()
        )
        return details.ads_view(contacts, pipelines, period)
