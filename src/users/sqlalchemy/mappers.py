from src.users.domain import User, UserCreate
from src.users.sqlalchemy.models import UserRow


def row_to_domain(row: UserRow) -> User:
    return User(
        id=row.id,
        organization_id=row.organization_id,
        encrypted_email=row.email,
        email_hash=row.email_hash,
        password_hash=row.password,
        created_at=row.created_at,
    )


def domain_create_to_row(user: UserCreate) -> UserRow:
    return UserRow(
        organization_id=user.organization_id,
        email=user.encrypted_email,
        email_hash=user.email_hash,
        password=user.password_hash,
    )
