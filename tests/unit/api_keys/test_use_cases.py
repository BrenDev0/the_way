from uuid import uuid4

import pytest
from helpers import make_api_key, make_user

from src.api_keys import use_cases as api_keys_use_cases
from src.api_keys.domain import Provider
from src.core.exceptions import ConflictError, NotFoundError, ValidationError


@pytest.fixture
def organization_id():
    return uuid4()


@pytest.fixture
def issuer_id():
    return uuid4()


@pytest.fixture
def issued(organization_id, issuer_id, encryption_service):
    stored = []

    async def run(user=None, **overrides):
        target = user if user is not None else make_user(organization_id=organization_id)

        async def get_user_by_id_fn(uid):
            return target if uid == target.id else None

        async def upsert_api_key_fn(api_key):
            stored.append(api_key)
            return make_api_key(
                organization_id=api_key.organization_id,
                user_id=api_key.user_id,
                provider=api_key.provider,
                encrypted_secret=api_key.encrypted_secret,
                last_four=api_key.last_four,
                encrypted_account_id=api_key.encrypted_account_id,
                model=api_key.model,
                issued_by=api_key.issued_by,
            )

        payload = {
            "organization_id": organization_id,
            "user_id": target.id,
            "provider": Provider.ANTHROPIC,
            "secret": "sk-ant-secret1234",
            "issued_by": issuer_id,
            "get_user_by_id_fn": get_user_by_id_fn,
            "upsert_api_key_fn": upsert_api_key_fn,
            "encryption_service": encryption_service,
        }
        payload.update(overrides)
        return await api_keys_use_cases.issue_api_key(**payload)

    run.stored = stored
    return run


async def test_the_secret_is_encrypted_before_it_reaches_the_port(issued):
    await issued()

    assert issued.stored[0].encrypted_secret == "enc::sk-ant-secret1234"


async def test_last_four_comes_from_the_tail_of_the_secret(issued):
    await issued()

    assert issued.stored[0].last_four == "1234"


async def test_gohighlevel_needs_an_account_id(issued):
    with pytest.raises(ValidationError) as exc:
        await issued(provider=Provider.GOHIGHLEVEL, secret="pit-secret")

    assert exc.value.code == "api_key_account_id_required"
    assert exc.value.status_code == 422


async def test_gohighlevel_account_id_is_encrypted(issued):
    await issued(
        provider=Provider.GOHIGHLEVEL, secret="pit-secret", account_id="loc-123"
    )

    assert issued.stored[0].encrypted_account_id == "enc::loc-123"


async def test_gohighlevel_does_not_take_a_model(issued):
    with pytest.raises(ValidationError) as exc:
        await issued(
            provider=Provider.GOHIGHLEVEL,
            secret="pit-secret",
            account_id="loc-123",
            model="claude-sonnet-5",
        )

    assert exc.value.code == "api_key_model_not_supported"


async def test_an_unknown_model_is_rejected(issued):
    with pytest.raises(ValidationError) as exc:
        await issued(model="not-a-real-model")

    assert exc.value.code == "llm_model_not_available"


async def test_a_model_from_another_provider_is_rejected(issued):
    with pytest.raises(ValidationError) as exc:
        await issued(provider=Provider.ANTHROPIC, model="gpt-5.4")

    assert exc.value.code == "api_key_model_provider_mismatch"


async def test_a_user_from_another_organization_is_not_found(issued):
    outsider = make_user(organization_id=uuid4())

    with pytest.raises(NotFoundError) as exc:
        await issued(user=outsider)

    assert exc.value.code == "user_not_found"
    assert exc.value.status_code == 404


async def test_nothing_is_stored_when_the_user_is_rejected(issued):
    with pytest.raises(NotFoundError):
        await issued(user=make_user(organization_id=uuid4()))

    assert issued.stored == []


@pytest.fixture
def resolve():
    async def run(*keys):
        async def list_api_keys_for_user_fn(_user_id):
            return list(keys)

        return await api_keys_use_cases.resolve_llm_credential(
            user_id=uuid4(),
            list_api_keys_for_user_fn=list_api_keys_for_user_fn,
        )

    return run


async def test_anthropic_wins_when_a_user_holds_both(resolve):
    credential = await resolve(
        make_api_key(provider=Provider.OPENAI),
        make_api_key(provider=Provider.ANTHROPIC),
    )

    assert credential.provider is Provider.ANTHROPIC


async def test_the_only_ai_key_is_used(resolve):
    credential = await resolve(make_api_key(provider=Provider.OPENAI))

    assert credential.provider is Provider.OPENAI


async def test_a_gohighlevel_key_does_not_satisfy_a_turn(resolve):
    with pytest.raises(ConflictError) as exc:
        await resolve(make_api_key(provider=Provider.GOHIGHLEVEL))

    assert exc.value.code == "api_key_not_configured"
    assert exc.value.status_code == 409


async def test_a_user_with_no_keys_is_refused(resolve):
    with pytest.raises(ConflictError) as exc:
        await resolve()

    assert exc.value.code == "api_key_not_configured"


def test_the_stored_model_is_used_when_set():
    credential = make_api_key(provider=Provider.ANTHROPIC, model="claude-opus-5")

    assert api_keys_use_cases.model_for(credential) == "claude-opus-5"


def test_the_provider_default_is_used_when_no_model_is_stored():
    credential = make_api_key(provider=Provider.OPENAI, model=None)

    assert api_keys_use_cases.model_for(credential) == "gpt-5.4"


async def test_delete_reports_a_missing_key():
    async def delete_fn(_api_key_id, _organization_id):
        return False

    with pytest.raises(NotFoundError) as exc:
        await api_keys_use_cases.delete_api_key(
            api_key_id=uuid4(),
            organization_id=uuid4(),
            delete_api_key_for_organization_fn=delete_fn,
        )

    assert exc.value.code == "api_key_not_found"
    assert exc.value.status_code == 404


async def test_delete_is_scoped_to_the_callers_organization():
    seen = []

    async def delete_fn(api_key_id, organization_id):
        seen.append((api_key_id, organization_id))
        return True

    api_key_id, organization_id = uuid4(), uuid4()
    await api_keys_use_cases.delete_api_key(
        api_key_id=api_key_id,
        organization_id=organization_id,
        delete_api_key_for_organization_fn=delete_fn,
    )

    assert seen == [(api_key_id, organization_id)]
