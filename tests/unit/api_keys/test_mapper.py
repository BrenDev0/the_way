from helpers import make_api_key

from src.api_keys import mapper
from src.api_keys.domain import Provider

SECRET = "enc::sk-ant-supersecret9876"
ACCOUNT = "enc::loc-abc123"


def test_the_response_never_carries_the_secret():
    api_key = make_api_key(encrypted_secret=SECRET)

    payload = mapper.domain_to_api_key_response(api_key).model_dump(by_alias=True)

    assert SECRET not in payload.values()
    assert not any("secret" in str(name).lower() for name in payload)


def test_the_response_never_carries_the_account_id():
    api_key = make_api_key(
        provider=Provider.GOHIGHLEVEL, encrypted_account_id=ACCOUNT
    )

    payload = mapper.domain_to_api_key_response(api_key).model_dump(by_alias=True)

    assert ACCOUNT not in payload.values()
    assert not any("account" in str(name).lower() for name in payload)


def test_the_response_carries_the_identifying_metadata():
    api_key = make_api_key(last_four="9876", model="claude-opus-5")

    response = mapper.domain_to_api_key_response(api_key)

    assert response.id == api_key.id
    assert response.user_id == api_key.user_id
    assert response.provider is api_key.provider
    assert response.last_four == "9876"
    assert response.model == "claude-opus-5"
    assert response.issued_by == api_key.issued_by


def test_the_wire_format_is_camel_case():
    payload = mapper.domain_to_api_key_response(make_api_key()).model_dump(by_alias=True)

    assert "lastFour" in payload
    assert "userId" in payload
