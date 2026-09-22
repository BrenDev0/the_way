from fastapi import APIRouter, Depends

from src.api import signing
from src.auth.routes import router as auth_router
from src.conversations.routes import router as conversations_router
from src.organizations.routes import router as organizations_router
from src.users.routes import router as users_router

router = APIRouter(dependencies=[Depends(signing.verify_request_signature)])
router.include_router(auth_router, prefix="/auth")
router.include_router(conversations_router, prefix="/conversations")
router.include_router(organizations_router, prefix="/organizations")
router.include_router(users_router, prefix="/users")
