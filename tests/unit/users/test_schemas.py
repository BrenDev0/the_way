from helpers import make_user

from src.users.fastapi.schemas import UserResponse


def test_user_response_carries_the_email_it_is_given_and_the_identifiers():
    user = make_user(encrypted_email="enc::someone@example.com")

    response = UserResponse.from_domain(user, email="someone@example.com", setup_complete=True)

    assert response.id == user.id
    assert response.organization_id == user.organization_id
    assert response.email == "someone@example.com"
    assert response.created_at == user.created_at
    assert response.setup_complete is True


def test_user_response_serializes_setup_complete_in_camel_case():
    response = UserResponse.from_domain(make_user(), email="someone@example.com", setup_complete=False)

    assert response.model_dump(by_alias=True)["setupComplete"] is False


def test_user_response_never_carries_the_stored_encrypted_email_or_password_hash():
    user = make_user(encrypted_email="enc::someone@example.com", password_hash="pwhash::secret")

    payload = UserResponse.from_domain(user, email="someone@example.com", setup_complete=True).model_dump(
        by_alias=True
    )

    assert "enc::someone@example.com" not in payload.values()
    assert "pwhash::secret" not in payload.values()
    assert not any("password" in str(name).lower() or "encrypted" in str(name).lower() for name in payload)
