from datetime import datetime

from src.core.schemas import ApiBaseModel
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
