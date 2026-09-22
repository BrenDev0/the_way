from src.core.cryptography.ports import EncryptionService
from src.users.domain import User
from src.users.schemas import UserResponse


def domain_to_user_response(user: User, encryption_service: EncryptionService) -> UserResponse:
    return UserResponse(
        id=user.id,
        organization_id=user.organization_id,
        email=encryption_service.decrypt(user.encrypted_email),
        created_at=user.created_at,
    )
