"""The desktop app's API.

The same slices the front end uses, mounted a second time under their own prefix. There
is no request signature here: a secret shipped inside a desktop app can be pulled out of
it, so signing would prove nothing. The bearer token -- which only a successful login can
produce -- is the credential, and get_current_session refuses anything else on this prefix.

Only what the desktop app needs is mounted. Organization management -- issuing keys,
invitations, documents, skills, everyone's projects -- stays behind the front end.
"""

from fastapi import APIRouter

from src.auth.desktop_routes import router as desktop_auth_router
from src.auth.session_routes import router as sessions_router
from src.background.routes import router as background_router
from src.conversations.routes import router as conversations_router
from src.desktop.routes import router as desktop_tools_router
from src.preferences.routes import router as preferences_router
from src.projects.routes import router as projects_router
from src.users.routes import router as users_router

router = APIRouter()
router.include_router(desktop_auth_router, prefix="/auth")
router.include_router(sessions_router, prefix="/auth")
router.include_router(background_router, prefix="/background-tasks")
router.include_router(conversations_router, prefix="/conversations")
router.include_router(desktop_tools_router, prefix="/desktop-tools")
router.include_router(preferences_router, prefix="/preferences")
router.include_router(projects_router, prefix="/projects")
router.include_router(users_router, prefix="/users")
