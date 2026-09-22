from uuid import UUID

from src.core.sessions import service as sessions_service
from src.core.sessions.ports import RevokeSessionsByUserIdFn
from src.users.ports import DeleteUserFn


async def delete_user(
    user_id: UUID,
    delete_user_fn: DeleteUserFn,
    revoke_sessions_by_user_id_fn: RevokeSessionsByUserIdFn,
) -> None:
    await sessions_service.revoke_user_sessions(user_id, revoke_sessions_by_user_id_fn)
    await delete_user_fn(user_id)
