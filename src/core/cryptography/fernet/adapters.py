from cryptography.fernet import Fernet

from src.core.cryptography.ports import EncryptionService


class FernetEncryptionService(EncryptionService):
    def __init__(self, key: str):
        self._fernet = Fernet(key.encode("utf-8"))

    def encrypt(self, data: str | int) -> str:
        value = str(data).encode("utf-8")
        return self._fernet.encrypt(value).decode("utf-8")

    def decrypt(self, encrypted: str) -> str:
        return self._fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")
