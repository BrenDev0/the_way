from fastapi import APIRouter, Depends

from src.api import signing
from src.api_keys.routes import router as api_keys_router
from src.auth.routes import router as auth_router
from src.auth.session_routes import router as sessions_router
from src.background.routes import router as background_router
from src.conversations.routes import router as conversations_router
from src.documents.routes import router as documents_router
from src.invitations.routes import router as invitations_router
from src.organizations.routes import router as organizations_router
from src.preferences.routes import router as preferences_router
from src.projects.management.routes import router as projects_management_router
from src.projects.routes import router as projects_router
from src.skills.routes import router as skills_router
from src.users.routes import router as users_router
from src.voice.routes import router as voice_router

router = APIRouter(dependencies=[Depends(signing.verify_request_signature)])
router.include_router(api_keys_router, prefix="/api-keys")
router.include_router(auth_router, prefix="/auth")
router.include_router(sessions_router, prefix="/auth")
router.include_router(background_router, prefix="/background-tasks")
router.include_router(conversations_router, prefix="/conversations")
router.include_router(documents_router, prefix="/documents")
router.include_router(invitations_router, prefix="/invitations")
router.include_router(organizations_router, prefix="/organizations")
router.include_router(preferences_router, prefix="/preferences")
# Before the projects router, whose /{project_id} routes would otherwise claim it.
router.include_router(projects_management_router, prefix="/projects/management")
router.include_router(projects_router, prefix="/projects")
router.include_router(skills_router, prefix="/skills")
router.include_router(users_router, prefix="/users")
router.include_router(voice_router, prefix="/voice")
