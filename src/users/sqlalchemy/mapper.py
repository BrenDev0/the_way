from src.users.domain import Role, User, UserCreate

from .models import UserRow


def row_to_domain(row: UserRow) -> User:
    return User(
        id=row.id,
        organization_id=row.organization_id,
        encrypted_email=row.email,
        email_hash=row.email_hash,
        password_hash=row.password,
        role=Role(row.role),
        created_at=row.created_at,
    )


def domain_create_to_row(user: UserCreate) -> UserRow:
    return UserRow(
        organization_id=user.organization_id,
        email=user.encrypted_email,
        email_hash=user.email_hash,
        password=user.password_hash,
        role=user.role,
    )
