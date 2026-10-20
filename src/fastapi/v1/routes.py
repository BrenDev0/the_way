from fastapi import APIRouter, Depends

from src.api_keys.fastapi.routes import router as api_keys_router
from src.auth.fastapi.routes.registration import router as auth_registration_router
from src.auth.fastapi.routes.sessions import router as sessions_router
from src.auth.fastapi.routes.web import router as auth_web_router
from src.background.fastapi.routes import router as background_router
from src.conversations.fastapi.routes.attachments import (
    router as conversation_attachments_router,
)
from src.conversations.fastapi.routes.conversations import (
    router as conversations_router,
)
from src.conversations.fastapi.routes.events import router as conversation_events_router
from src.conversations.fastapi.routes.turns import router as conversation_turns_router
from src.cx_dashboard.fastapi.routes import router as cx_dashboard_router
from src.documents.fastapi.routes import router as documents_router
from src.downloads.fastapi.routes import router as downloads_router
from src.fastapi import signing
from src.invitations.fastapi.routes import router as invitations_router
from src.organizations.fastapi.overview import router as organization_overview_router
from src.organizations.fastapi.routes import router as organizations_router
from src.preferences.fastapi.routes import router as preferences_router
from src.projects.fastapi.routes.files import router as project_files_router
from src.projects.fastapi.routes.folders import router as project_folders_router
from src.projects.fastapi.routes.management import router as projects_management_router
from src.projects.fastapi.routes.projects import router as projects_router
from src.skills.fastapi.routes import router as skills_router
from src.users.fastapi.routes import router as users_router
from src.voice.fastapi.routes import router as voice_router

router = APIRouter(dependencies=[Depends(signing.verify_request_signature)])
router.include_router(api_keys_router, prefix="/api-keys")
router.include_router(auth_registration_router, prefix="/auth")
router.include_router(auth_web_router, prefix="/auth")
router.include_router(sessions_router, prefix="/auth")
router.include_router(background_router, prefix="/background-tasks")
router.include_router(conversations_router, prefix="/conversations")
router.include_router(conversation_attachments_router, prefix="/conversations")
router.include_router(conversation_turns_router, prefix="/conversations")
router.include_router(conversation_events_router, prefix="/conversations")
router.include_router(cx_dashboard_router, prefix="/cx")
router.include_router(documents_router, prefix="/documents")
router.include_router(downloads_router, prefix="/downloads")
router.include_router(invitations_router, prefix="/invitations")
router.include_router(organizations_router, prefix="/organizations")
router.include_router(organization_overview_router, prefix="/organizations")
router.include_router(preferences_router, prefix="/preferences")
# Before the projects routers, whose /{project_id} routes would otherwise claim it.
router.include_router(projects_management_router, prefix="/projects/management")
router.include_router(projects_router, prefix="/projects")
router.include_router(project_folders_router, prefix="/projects")
router.include_router(project_files_router, prefix="/projects")
router.include_router(skills_router, prefix="/skills")
router.include_router(users_router, prefix="/users")
router.include_router(voice_router, prefix="/voice")
