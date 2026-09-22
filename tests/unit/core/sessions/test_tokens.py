import hashlib
from datetime import UTC, datetime, timedelta

from src.core.sessions.tokens import SessionTokenService


def test_generated_tokens_are_unique():
    service = SessionTokenService()
    tokens = {service.generate_session_token() for _ in range(50)}
    assert len(tokens) == 50


def test_hash_is_deterministic_and_matches_sha256():
    service = SessionTokenService()
    token = "some-raw-token"

    assert service.hash_session_token(token) == service.hash_session_token(token)
    assert service.hash_session_token(token) == hashlib.sha256(token.encode("utf-8")).hexdigest()


def test_different_tokens_hash_differently():
    service = SessionTokenService()
    assert service.hash_session_token("a") != service.hash_session_token("b")


def test_build_expiration_adds_ttl_to_given_time():
    service = SessionTokenService(session_ttl=timedelta(hours=2))
    now = datetime(2026, 1, 1, tzinfo=UTC)

    assert service.build_expiration(now) == now + timedelta(hours=2)


def test_build_expiration_defaults_to_seven_days():
    service = SessionTokenService()
    now = datetime(2026, 1, 1, tzinfo=UTC)

    assert service.build_expiration(now) == now + timedelta(days=7)
