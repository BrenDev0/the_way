import hashlib

import pytest
from cryptography.fernet import Fernet

from src.core.cryptography.bcrypt.adapter import BcryptHashingService
from src.core.cryptography.fernet.adapter import FernetEncryptionService


@pytest.fixture
def fernet():
    return FernetEncryptionService(Fernet.generate_key().decode("utf-8"))


@pytest.fixture
def bcrypt_service():
    return BcryptHashingService()


def test_fernet_round_trips_a_string(fernet):
    assert fernet.decrypt(fernet.encrypt("someone@example.com")) == "someone@example.com"


def test_fernet_integers_come_back_as_strings(fernet):
    assert fernet.decrypt(fernet.encrypt(42)) == "42"


def test_fernet_ciphertext_does_not_contain_the_plaintext(fernet):
    assert "someone@example.com" not in fernet.encrypt("someone@example.com")


def test_fernet_same_input_encrypts_differently_each_time(fernet):
    first = fernet.encrypt("someone@example.com")
    second = fernet.encrypt("someone@example.com")

    assert first != second
    assert fernet.decrypt(first) == fernet.decrypt(second)


def test_bcrypt_password_verifies_against_its_hash(bcrypt_service):
    hashed = bcrypt_service.hash_password("hunter2")
    assert bcrypt_service.compare_password("hunter2", hashed) is True


def test_bcrypt_wrong_password_is_rejected(bcrypt_service):
    hashed = bcrypt_service.hash_password("hunter2")
    assert bcrypt_service.compare_password("wrong", hashed) is False


def test_bcrypt_hash_is_salted_so_repeats_differ(bcrypt_service):
    first = bcrypt_service.hash_password("hunter2")
    second = bcrypt_service.hash_password("hunter2")

    assert first != second
    assert bcrypt_service.compare_password("hunter2", first)
    assert bcrypt_service.compare_password("hunter2", second)


def test_bcrypt_plaintext_is_not_recoverable_from_the_hash(bcrypt_service):
    assert "hunter2" not in bcrypt_service.hash_password("hunter2")


def test_deterministic_hash_is_stable(bcrypt_service):
    assert bcrypt_service.deterministic_hash("a@example.com") == (
        bcrypt_service.deterministic_hash("a@example.com")
    )


def test_deterministic_hash_matches_sha256(bcrypt_service):
    assert bcrypt_service.deterministic_hash("a@example.com") == (
        hashlib.sha256(b"a@example.com").hexdigest()
    )


def test_deterministic_hash_differs_for_different_inputs(bcrypt_service):
    assert bcrypt_service.deterministic_hash("a@example.com") != (
        bcrypt_service.deterministic_hash("b@example.com")
    )
