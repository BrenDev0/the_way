from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.core.exceptions import ApplicationError
from src.core.schemas import ErrorResponse


async def application_error_handler(_request: Request, exc: ApplicationError) -> JSONResponse:
    error = ErrorResponse(message=exc.message, code=exc.code)
    return JSONResponse(status_code=exc.status_code, content=error.model_dump(by_alias=True))


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApplicationError, application_error_handler)
