from src.core.cryptography.ports import HashingService
from src.core.exceptions import AuthenticationError
from src.users.domain import User
from src.users.ports import GetUserByEmailHashFn


def invalid_credentials() -> AuthenticationError:
    return AuthenticationError(message="Incorrect email or password", code="invalid_credentials")


async def authenticate(
    email: str,
    password: str,
    get_user_by_email_hash_fn: GetUserByEmailHashFn,
    hashing_service: HashingService,
) -> User | None:
    """The user these credentials belong to, or None. An unknown email still pays for a
    password hash, so the response time does not reveal which emails have accounts."""
    user = await get_user_by_email_hash_fn(hashing_service.deterministic_hash(email))
    if user is None:
        hashing_service.hash_password(password)
        return None
    if not hashing_service.compare_password(password, user.password_hash):
        return None
    return user
