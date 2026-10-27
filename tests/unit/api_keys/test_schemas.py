from helpers import make_api_key

from src.api_keys.domain import Provider
from src.staff.fastapi.schemas import OrganizationApiKeyResponse

SECRET = "enc::sk-ant-supersecret9876"


def decrypt(value: str) -> str:
    return value.removeprefix("enc::")


def test_what_staff_see_afterwards_never_carries_the_secret():
    api_key = make_api_key(encrypted_secret=SECRET)

    payload = OrganizationApiKeyResponse.from_domain(api_key, decrypt).model_dump(by_alias=True)

    assert SECRET not in payload.values()
    assert "sk-ant-supersecret9876" not in str(payload)
    assert not any("secret" in str(name).lower() for name in payload)


def test_the_response_carries_the_identifying_metadata():
    api_key = make_api_key(last_four="9876", model="claude-opus-5", set_by=None)

    response = OrganizationApiKeyResponse.from_domain(api_key, decrypt)

    assert response.provider is api_key.provider
    assert response.last_four == "9876"
    assert response.model == "claude-opus-5"
    assert response.set_by is None


def test_the_cx_location_id_is_shown_to_staff_because_it_is_not_a_secret():
    api_key = make_api_key(provider=Provider.GOHIGHLEVEL, encrypted_account_id="enc::loc-abc123")

    response = OrganizationApiKeyResponse.from_domain(api_key, decrypt)

    assert response.account_id == "loc-abc123"


def test_a_key_with_no_account_id_has_none():
    assert OrganizationApiKeyResponse.from_domain(make_api_key(), decrypt).account_id is None
