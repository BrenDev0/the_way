from uuid import uuid4

import pytest
from helpers import make_api_key

from src.api_keys import use_cases as api_keys_use_cases
from src.api_keys.domain import Provider
from src.core.exceptions import ConflictError, NotFoundError, ValidationError


@pytest.fixture
def organization_id():
    return uuid4()


@pytest.fixture
def staff_id():
    return uuid4()


@pytest.fixture
def key_set(organization_id, staff_id, encryption_service):
    stored = []

    async def run(**overrides):
        async def upsert_api_key_fn(api_key):
            stored.append(api_key)
            return make_api_key(
                organization_id=api_key.organization_id,
                provider=api_key.provider,
                encrypted_secret=api_key.encrypted_secret,
                last_four=api_key.last_four,
                encrypted_account_id=api_key.encrypted_account_id,
                model=api_key.model,
                set_by=api_key.set_by,
            )

        payload = {
            "organization_id": organization_id,
            "provider": Provider.ANTHROPIC,
            "secret": "sk-ant-secret1234",
            "set_by": staff_id,
            "upsert_api_key_fn": upsert_api_key_fn,
            "encryption_service": encryption_service,
        }
        payload.update(overrides)
        return await api_keys_use_cases.set_api_key(**payload)

    run.stored = stored
    return run


async def test_the_secret_is_encrypted_before_it_reaches_the_port(key_set):
    await key_set()

    assert key_set.stored[0].encrypted_secret == "enc::sk-ant-secret1234"


async def test_the_key_belongs_to_the_organization_and_records_who_set_it(key_set, organization_id, staff_id):
    await key_set()

    assert key_set.stored[0].organization_id == organization_id
    assert key_set.stored[0].set_by == staff_id


async def test_last_four_comes_from_the_tail_of_the_secret(key_set):
    await key_set()

    assert key_set.stored[0].last_four == "1234"


async def test_a_secret_pasted_with_spaces_is_trimmed(key_set):
    await key_set(secret="  sk-ant-secret1234\n")

    assert key_set.stored[0].encrypted_secret == "enc::sk-ant-secret1234"


@pytest.mark.parametrize("secret", ["", "   "])
async def test_an_empty_secret_is_refused(key_set, secret):
    with pytest.raises(ValidationError) as exc:
        await key_set(secret=secret)

    assert exc.value.code == "api_key_secret_required"
    assert key_set.stored == []


async def test_gohighlevel_needs_an_account_id(key_set):
    with pytest.raises(ValidationError) as exc:
        await key_set(provider=Provider.GOHIGHLEVEL, secret="pit-secret")

    assert exc.value.code == "api_key_account_id_required"
    assert exc.value.status_code == 422


async def test_gohighlevel_account_id_is_encrypted(key_set):
    await key_set(provider=Provider.GOHIGHLEVEL, secret="pit-secret", account_id="loc-123")

    assert key_set.stored[0].encrypted_account_id == "enc::loc-123"


async def test_gohighlevel_does_not_take_a_model(key_set):
    with pytest.raises(ValidationError) as exc:
        await key_set(
            provider=Provider.GOHIGHLEVEL,
            secret="pit-secret",
            account_id="loc-123",
            model="claude-sonnet-5",
        )

    assert exc.value.code == "api_key_model_not_supported"


async def test_an_unknown_model_is_rejected(key_set):
    with pytest.raises(ValidationError) as exc:
        await key_set(model="not-a-real-model")

    assert exc.value.code == "llm_model_not_available"


async def test_a_model_from_another_provider_is_rejected(key_set):
    with pytest.raises(ValidationError) as exc:
        await key_set(provider=Provider.ANTHROPIC, model="gpt-5.4")

    assert exc.value.code == "api_key_model_provider_mismatch"


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


async def test_anthropic_wins_when_the_organization_holds_both(resolve):
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


async def test_an_organization_with_no_keys_is_refused_and_told_to_contact_xplorers(resolve):
    with pytest.raises(ConflictError) as exc:
        await resolve()

    assert exc.value.code == "api_key_not_configured"
    assert "Contact Xplorers" in exc.value.message
    assert "owner" not in exc.value.message.lower()


async def setup_complete(*held):
    async def list_api_keys_for_user_fn(_user_id):
        return list(held)

    return await api_keys_use_cases.is_setup_complete(
        user_id=uuid4(),
        list_api_keys_for_user_fn=list_api_keys_for_user_fn,
    )


async def test_an_organization_with_no_keys_is_awaiting_setup():
    assert await setup_complete() is False


async def test_a_gohighlevel_key_alone_does_not_complete_setup():
    assert await setup_complete(make_api_key(provider=Provider.GOHIGHLEVEL)) is False


@pytest.mark.parametrize("provider", [Provider.ANTHROPIC, Provider.OPENAI])
async def test_any_ai_key_completes_setup(provider):
    assert await setup_complete(make_api_key(provider=provider)) is True


@pytest.mark.parametrize(
    ("held", "expected"),
    [
        ([], False),
        ([Provider.GOHIGHLEVEL], False),
        ([Provider.GOHIGHLEVEL, Provider.OPENAI], True),
    ],
)
async def test_the_organization_as_a_whole_is_set_up_by_an_ai_key(held, expected):
    async def list_api_keys_fn(_organization_id):
        return [make_api_key(provider=provider) for provider in held]

    assert (
        await api_keys_use_cases.organization_is_set_up(uuid4(), list_api_keys_fn) is expected
    )


def test_the_stored_model_is_used_when_set():
    credential = make_api_key(provider=Provider.ANTHROPIC, model="claude-opus-5")

    assert api_keys_use_cases.model_for(credential) == "claude-opus-5"


def test_the_provider_default_is_used_when_no_model_is_stored():
    credential = make_api_key(provider=Provider.OPENAI, model=None)

    assert api_keys_use_cases.model_for(credential) == "gpt-5.4"


async def test_delete_reports_a_missing_key():
    async def delete_fn(_organization_id, _provider):
        return False

    with pytest.raises(NotFoundError) as exc:
        await api_keys_use_cases.delete_api_key(
            organization_id=uuid4(),
            provider=Provider.OPENAI,
            delete_api_key_fn=delete_fn,
        )

    assert exc.value.code == "api_key_not_found"
    assert exc.value.status_code == 404


async def test_delete_is_scoped_to_one_organization_and_one_provider():
    seen = []

    async def delete_fn(organization_id, provider):
        seen.append((organization_id, provider))
        return True

    organization_id = uuid4()
    await api_keys_use_cases.delete_api_key(
        organization_id=organization_id,
        provider=Provider.TAVILY,
        delete_api_key_fn=delete_fn,
    )

    assert seen == [(organization_id, Provider.TAVILY)]
