import hashlib

import bcrypt

from src.core.cryptography.ports import HashingService


class BcryptHashingService(HashingService):
    def hash_password(self, password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def deterministic_hash(self, str_to_dhash: str) -> str:
        return hashlib.sha256(str_to_dhash.encode("utf-8")).hexdigest()

    def compare_password(self, password: str, hashed_value: str) -> bool:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_value.encode("utf-8"))
