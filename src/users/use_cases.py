from collections.abc import Sequence
from uuid import UUID

from src.auth.dependencies import get_current_user
from src.core.cryptography.ports import EncryptionService
from src.core.exceptions import NotFoundError
from src.core.sessions.ports import RevokeSessionsByUserIdFn
from src.core.sessions.service import revoke_user_sessions
from src.users.mappers import domain_to_user_response
from src.users.ports import DeleteUserFn


async def delete_user(
    user_id: UUID,
    delete_user_fn: DeleteUserFn,
    revoke_sessions_by_user_id_fn: RevokeSessionsByUserIdFn,
) -> None:
    await revoke_user_sessions(user_id, revoke_sessions_by_user_id_fn)
    await delete_user_fn(user_id)
