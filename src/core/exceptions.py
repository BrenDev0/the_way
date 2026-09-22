from dataclasses import dataclass
from typing import ClassVar

from fastapi import status


@dataclass(eq=False)
class ApplicationError(Exception):
    message: str
    code: str
    status_code: int

    def __str__(self) -> str:
        return self.message


class AuthenticationError(ApplicationError):
    default_status_code: ClassVar[int] = status.HTTP_401_UNAUTHORIZED

    def __init__(self, message: str = "Not authenticated", code: str = "authentication_error") -> None:
        super().__init__(message=message, code=code, status_code=self.default_status_code)


class AuthorizationError(ApplicationError):
    default_status_code: ClassVar[int] = status.HTTP_403_FORBIDDEN

    def __init__(self, message: str = "Not authorized", code: str = "authorization_error") -> None:
        super().__init__(message=message, code=code, status_code=self.default_status_code)


class NotFoundError(ApplicationError):
    default_status_code: ClassVar[int] = status.HTTP_404_NOT_FOUND

    def __init__(self, message: str = "Resource not found", code: str = "not_found") -> None:
        super().__init__(message=message, code=code, status_code=self.default_status_code)


class ConflictError(ApplicationError):
    default_status_code: ClassVar[int] = status.HTTP_409_CONFLICT

    def __init__(self, message: str = "Resource conflict", code: str = "conflict") -> None:
        super().__init__(message=message, code=code, status_code=self.default_status_code)


class ValidationError(ApplicationError):
    default_status_code: ClassVar[int] = status.HTTP_422_UNPROCESSABLE_ENTITY

    def __init__(self, message: str = "Validation failed", code: str = "validation_error") -> None:
        super().__init__(message=message, code=code, status_code=self.default_status_code)


class InternalServerError(ApplicationError):
    default_status_code: ClassVar[int] = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str = "Unable to process request at this time", code: str = "internal_server_error") -> None:
        super().__init__(message=message, code=code, status_code=self.default_status_code)
