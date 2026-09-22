from fastapi import APIRouter, Depends

from src.api import signing
from src.auth.routes import router as auth_router
from src.users.routes import router as users_router

router = APIRouter(dependencies=[Depends(signing.verify_request_signature)])
router.include_router(auth_router, prefix="/auth")
router.include_router(users_router, prefix="/users")


@router.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
