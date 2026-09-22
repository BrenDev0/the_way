from src.core.sessions.domain import Session, SessionCreate

from .models import SessionRow


def row_to_domain(row: SessionRow) -> Session:
    return Session(
        id=row.id,
        user_id=row.user_id,
        token_hash=row.token_hash,
        expires_at=row.expires_at,
        last_seen_at=row.last_seen_at,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
    )


def domain_create_to_row(session: SessionCreate) -> SessionRow:
    return SessionRow(
        user_id=session.user_id,
        token_hash=session.token_hash,
        expires_at=session.expires_at,
        last_seen_at=session.last_seen_at,
    )
