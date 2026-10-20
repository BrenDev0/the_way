"""The desktop app's API.

The same slices the front end uses, mounted a second time under their own prefix. There
is no request signature here: a secret shipped inside a desktop app can be pulled out of
it, so signing would prove nothing. The bearer token -- which only a successful login can
produce -- is the credential, and get_current_session refuses anything else on this prefix.

Only what the desktop app needs is mounted. Organization management -- issuing keys,
invitations, documents, skills, everyone's projects -- stays behind the front end.
"""

from fastapi import APIRouter

from src.auth.fastapi.routes.desktop import router as desktop_auth_router
from src.auth.fastapi.routes.sessions import router as sessions_router
from src.background.fastapi.routes import router as background_router
from src.conversations.fastapi.routes.attachments import (
    router as conversation_attachments_router,
)
from src.conversations.fastapi.routes.conversations import (
    router as conversations_router,
)
from src.conversations.fastapi.routes.events import router as conversation_events_router
from src.conversations.fastapi.routes.turns import router as conversation_turns_router
from src.desktop.fastapi.routes import router as desktop_tools_router
from src.downloads.fastapi.desktop_routes import router as app_version_router
from src.preferences.fastapi.routes import router as preferences_router
from src.projects.fastapi.routes.files import router as project_files_router
from src.projects.fastapi.routes.folders import router as project_folders_router
from src.projects.fastapi.routes.projects import router as projects_router
from src.users.fastapi.routes import router as users_router
from src.voice.fastapi.routes import router as voice_router

router = APIRouter()
router.include_router(app_version_router, prefix="/app")
router.include_router(desktop_auth_router, prefix="/auth")
router.include_router(sessions_router, prefix="/auth")
router.include_router(background_router, prefix="/background-tasks")
router.include_router(conversations_router, prefix="/conversations")
router.include_router(conversation_attachments_router, prefix="/conversations")
router.include_router(conversation_turns_router, prefix="/conversations")
router.include_router(conversation_events_router, prefix="/conversations")
router.include_router(desktop_tools_router, prefix="/desktop-tools")
router.include_router(preferences_router, prefix="/preferences")
router.include_router(projects_router, prefix="/projects")
router.include_router(project_folders_router, prefix="/projects")
router.include_router(project_files_router, prefix="/projects")
router.include_router(users_router, prefix="/users")
router.include_router(voice_router, prefix="/voice")
