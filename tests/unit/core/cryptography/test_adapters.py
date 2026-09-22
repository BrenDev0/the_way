import hashlib

from cryptography.fernet import Fernet

from src.core.cryptography.bcrypt.adapter import BcryptHashingService
from src.core.cryptography.fernet.adapter import FernetEncryptionService


class TestFernetEncryption:
    def setup_method(self):
        self.service = FernetEncryptionService(Fernet.generate_key().decode("utf-8"))

    def test_round_trips_a_string(self):
        assert self.service.decrypt(self.service.encrypt("someone@example.com")) == (
            "someone@example.com"
        )

    def test_integers_come_back_as_strings(self):
        assert self.service.decrypt(self.service.encrypt(42)) == "42"

    def test_ciphertext_does_not_contain_the_plaintext(self):
        assert "someone@example.com" not in self.service.encrypt("someone@example.com")

    def test_same_input_encrypts_differently_each_time(self):
        first = self.service.encrypt("someone@example.com")
        second = self.service.encrypt("someone@example.com")

        assert first != second
        assert self.service.decrypt(first) == self.service.decrypt(second)


class TestBcryptHashing:
    def setup_method(self):
        self.service = BcryptHashingService()

    def test_password_verifies_against_its_hash(self):
        hashed = self.service.hash_password("hunter2")
        assert self.service.compare_password("hunter2", hashed) is True

    def test_wrong_password_is_rejected(self):
        hashed = self.service.hash_password("hunter2")
        assert self.service.compare_password("wrong", hashed) is False

    def test_hash_is_salted_so_repeats_differ(self):
        first = self.service.hash_password("hunter2")
        second = self.service.hash_password("hunter2")

        assert first != second
        assert self.service.compare_password("hunter2", first)
        assert self.service.compare_password("hunter2", second)

    def test_plaintext_is_not_recoverable_from_the_hash(self):
        assert "hunter2" not in self.service.hash_password("hunter2")

    def test_deterministic_hash_is_stable(self):
        assert self.service.deterministic_hash("a@example.com") == (
            self.service.deterministic_hash("a@example.com")
        )

    def test_deterministic_hash_matches_sha256(self):
        assert self.service.deterministic_hash("a@example.com") == (
            hashlib.sha256(b"a@example.com").hexdigest()
        )

    def test_different_inputs_hash_differently(self):
        assert self.service.deterministic_hash("a@example.com") != (
            self.service.deterministic_hash("b@example.com")
        )
