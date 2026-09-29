from datetime import datetime
from uuid import UUID

from pydantic import Field

from src.core.schemas import ApiBaseModel
from src.core.sessions.domain import SessionClient
from src.users.schemas import UserResponse


class UserRegistrationRequest(ApiBaseModel):
    organization_name: str
    email: str
    password: str
    verification_code: str


class RequestRegistrationVerificationRequest(ApiBaseModel):
    email: str


class RequestRegistrationVerificationResponse(ApiBaseModel):
    detail: str
    expires_at: datetime


class LoginRequest(ApiBaseModel):
    email: str
    password: str


class AuthUserResponse(ApiBaseModel):
    user: UserResponse


class LogoutResponse(ApiBaseModel):
    detail: str


class DesktopLoginRequest(ApiBaseModel):
    email: str
    password: str
    # Shown in the user's list of signed-in devices, e.g. "Brendan's laptop".
    device_name: str | None = Field(default=None, max_length=100)


class DesktopLoginResponse(ApiBaseModel):
    # Sent back as `Authorization: Bearer <token>` on every desktop request. Shown once;
    # the server keeps only its hash.
    token: str
    expires_at: datetime
    user: UserResponse


class SessionResponse(ApiBaseModel):
    id: UUID
    client: SessionClient
    device_name: str | None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    # The session making this request, so a client can mark "this device".
    current: bool


class RevokeSessionResponse(ApiBaseModel):
    detail: str
