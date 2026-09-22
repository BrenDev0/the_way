import json

import pytest

from src.core.exception_handlers import application_error_handler
from src.core.exceptions import ConflictError, NotFoundError


class TestApplicationErrorHandler:
    async def test_renders_the_error_body_and_status(self):
        exc = NotFoundError(message="User not found", code="user_not_found")

        response = await application_error_handler(None, exc)

        assert response.status_code == 404
        assert json.loads(response.body) == {
            "message": "User not found",
            "code": "user_not_found",
        }

    async def test_uses_the_status_code_of_the_error(self):
        response = await application_error_handler(None, ConflictError())
        assert response.status_code == 409

    async def test_unexpected_exceptions_are_re_raised(self):
        with pytest.raises(ValueError):
            await application_error_handler(None, ValueError("boom"))
