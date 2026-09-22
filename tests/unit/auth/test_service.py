import pytest

from src.auth import service as auth_service
from src.auth.cache import AuthCacheKey, build_auth_cache_key
from src.core.exceptions import AuthenticationError, ConflictError, InternalServerError
from src.core.settings import settings

EMAIL_HASH = "dhash::user@example.com"


def key(name: AuthCacheKey) -> str:
    return build_auth_cache_key(name, EMAIL_HASH)


def hash_code(raw: str) -> str:
    return f"codehash::{raw}"


def compare_code(submitted: str, stored_hash: str) -> bool:
    return hash_code(submitted) == stored_hash


class TestGenerateNumericCode:
    def test_default_length_is_six_digits(self):
        code = auth_service.generate_numeric_code()
        assert len(code) == auth_service.DEFAULT_VERIFICATION_CODE_LENGTH
        assert code.isdigit()

    def test_honours_requested_length(self):
        assert len(auth_service.generate_numeric_code(4)) == 4


class TestIssueVerificationCode:
    async def _issue(self, cache_store, code: str = "123456"):
        return await auth_service.issue_registration_verification_code(
            email_hash=EMAIL_HASH,
            cache_store=cache_store,
            code_hash_fn=hash_code,
            code_generator=lambda _length: code,
        )

    async def test_stores_hashed_code_and_zeroed_attempts(self, cache_store):
        raw_code, expires_at = await self._issue(cache_store)

        assert raw_code == "123456"
        assert cache_store.data[key(AuthCacheKey.VERIFICATION_CODE)] == hash_code("123456")
        assert cache_store.data[key(AuthCacheKey.VERIFICATION_ATTEMPTS)] == 0
        assert expires_at is not None

    async def test_raw_code_is_never_stored(self, cache_store):
        raw_code, _ = await self._issue(cache_store)
        assert raw_code not in cache_store.data.values()

    async def test_first_request_sets_ttl_on_the_request_counter(self, cache_store):
        await self._issue(cache_store)
        ttl = settings.REGISTRATION_VERIFICATION_CODE_TTL_SECONDS
        assert cache_store.ttls[key(AuthCacheKey.VERIFICATION_REQUESTS)] == ttl

    async def test_active_cooldown_is_rejected(self, cache_store):
        cache_store.data[key(AuthCacheKey.VERIFICATION_COOLDOWN)] = True

        with pytest.raises(ConflictError) as exc:
            await self._issue(cache_store)
        assert exc.value.code == "verification_request_cooldown_active"

    async def test_exceeding_max_requests_starts_a_cooldown(self, cache_store):
        cache_store.data[key(AuthCacheKey.VERIFICATION_REQUESTS)] = (
            settings.REGISTRATION_VERIFICATION_MAX_REQUESTS
        )

        with pytest.raises(ConflictError) as exc:
            await self._issue(cache_store)

        assert exc.value.code == "verification_request_limit_reached"
        assert cache_store.data[key(AuthCacheKey.VERIFICATION_COOLDOWN)] is True

    async def test_requests_up_to_the_limit_are_allowed(self, cache_store):
        cache_store.data[key(AuthCacheKey.VERIFICATION_REQUESTS)] = (
            settings.REGISTRATION_VERIFICATION_MAX_REQUESTS - 1
        )
        raw_code, _ = await self._issue(cache_store)
        assert raw_code == "123456"

    async def test_code_store_failure_raises(self, cache_store):
        cache_store.store_str_succeeds = False

        with pytest.raises(InternalServerError) as exc:
            await self._issue(cache_store)
        assert exc.value.code == "verification_code_store_failed"

    async def test_attempt_store_failure_rolls_back_the_code(self, cache_store):
        cache_store.store_int_succeeds = False

        with pytest.raises(InternalServerError) as exc:
            await self._issue(cache_store)

        assert exc.value.code == "verification_attempt_store_failed"
        assert key(AuthCacheKey.VERIFICATION_CODE) not in cache_store.data


class TestVerifyVerificationCode:
    async def _verify(self, cache_store, submitted: str):
        await auth_service.verify_registration_email_code(
            email_hash=EMAIL_HASH,
            submitted_code=submitted,
            cache_store=cache_store,
            compare_code_hash_fn=compare_code,
        )

    async def test_missing_code_is_treated_as_expired(self, cache_store):
        with pytest.raises(AuthenticationError) as exc:
            await self._verify(cache_store, "123456")
        assert exc.value.code == "verification_code_expired"

    async def test_correct_code_clears_all_verification_state(self, cache_store):
        cache_store.data[key(AuthCacheKey.VERIFICATION_CODE)] = hash_code("123456")
        cache_store.data[key(AuthCacheKey.VERIFICATION_ATTEMPTS)] = 0
        cache_store.data[key(AuthCacheKey.VERIFICATION_REQUESTS)] = 1

        await self._verify(cache_store, "123456")

        assert key(AuthCacheKey.VERIFICATION_CODE) not in cache_store.data
        assert key(AuthCacheKey.VERIFICATION_ATTEMPTS) not in cache_store.data
        assert key(AuthCacheKey.VERIFICATION_REQUESTS) not in cache_store.data

    async def test_wrong_code_increments_attempts(self, cache_store):
        cache_store.data[key(AuthCacheKey.VERIFICATION_CODE)] = hash_code("123456")
        cache_store.data[key(AuthCacheKey.VERIFICATION_ATTEMPTS)] = 0

        with pytest.raises(AuthenticationError) as exc:
            await self._verify(cache_store, "000000")

        assert exc.value.code == "invalid_verification_code"
        assert cache_store.data[key(AuthCacheKey.VERIFICATION_ATTEMPTS)] == 1
        assert key(AuthCacheKey.VERIFICATION_CODE) in cache_store.data

    async def test_final_wrong_attempt_burns_the_code_and_starts_cooldown(self, cache_store):
        cache_store.data[key(AuthCacheKey.VERIFICATION_CODE)] = hash_code("123456")
        cache_store.data[key(AuthCacheKey.VERIFICATION_ATTEMPTS)] = (
            settings.REGISTRATION_VERIFICATION_MAX_ATTEMPTS - 1
        )

        with pytest.raises(AuthenticationError) as exc:
            await self._verify(cache_store, "000000")

        assert exc.value.code == "verification_attempt_limit_reached"
        assert key(AuthCacheKey.VERIFICATION_CODE) not in cache_store.data
        assert cache_store.data[key(AuthCacheKey.VERIFICATION_COOLDOWN)] is True
