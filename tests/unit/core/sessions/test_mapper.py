from datetime import UTC, datetime
from uuid import uuid4

from src.core.sessions.domain import SessionCreate
from src.core.sessions.sqlalchemy import mapper as sessions_mapper
from src.core.sessions.sqlalchemy.models import SessionRow


class TestSessionMapper:
    def test_row_to_domain(self):
        now = datetime.now(UTC)
        row = SessionRow(
            id=uuid4(),
            user_id=uuid4(),
            token_hash="hash",
            expires_at=now,
            last_seen_at=now,
            revoked_at=None,
        )
        row.created_at = now

        session = sessions_mapper.row_to_domain(row)

        assert session.id == row.id
        assert session.user_id == row.user_id
        assert session.token_hash == row.token_hash
        assert session.revoked_at is None

    def test_domain_create_to_row(self):
        now = datetime.now(UTC)
        create = SessionCreate(
            user_id=uuid4(),
            token_hash="hash",
            expires_at=now,
            last_seen_at=now,
        )

        row = sessions_mapper.domain_create_to_row(create)

        assert row.user_id == create.user_id
        assert row.token_hash == create.token_hash
        assert row.expires_at == create.expires_at
