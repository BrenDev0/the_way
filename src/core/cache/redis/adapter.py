import json
from typing import Any, cast

import redis.asyncio as redis


class RedisCacheStore:
    def __init__(self, connection_url: str):
        self._redis = redis.from_url(connection_url, decode_responses=True)

    async def store_json(
        self,
        key: str,
        data: dict[str, Any],
        expire_seconds: int
    ) -> bool:
        result = await self._redis.set(
            name=key,
            value=json.dumps(data),
            ex=expire_seconds
        )
        return bool(result)

    async def store_str(
        self,
        key: str,
        data: str,
        expire_seconds: int
    ) -> bool:
        result = await self._redis.set(
            name=key,
            value=data,
            ex=expire_seconds
        )
        return bool(result)

    async def store_int(
        self,
        key: str,
        data: int,
        expire_seconds: int
    ) -> bool:
        result = await self._redis.set(
            name=key,
            value=str(data), 
            ex=expire_seconds
        )
        return bool(result)

    async def store_bool(
        self,
        key: str,
        data: bool,
        expire_seconds: int
    ) -> bool:
        result = await self._redis.set(
            name=key,
            value=str(data).lower(),
            ex=expire_seconds
        )
        return bool(result)

    async def get_json(self, key: str) -> dict[str, Any] | None:
        data = await self._redis.get(name=key)
        return json.loads(data) if data is not None else None

    async def get_str(self, key: str) -> str | None:
        return cast("str | None", await self._redis.get(name=key))

    async def get_int(self, key: str) -> int | None:
        data = await self._redis.get(name=key)
        return int(data) if data is not None else None

    async def get_bool(self, key: str) -> bool | None:
        data = await self._redis.get(name=key)
        if data is None:
            return None
        return data == "true"
    
    async def expire(
        self, 
        key:str, 
        expire_seconds: int
    )-> bool: 
        return await self._redis.expire(
            name=key,
            time=expire_seconds
        )
    
    async def increment(self, key: str) -> int:
        return await self._redis.incr(name=key)
    
    async def remove(self, key: str) -> bool:
        result = await self._redis.delete(key)
        return bool(result)
    
    async def close_connection(self):
        await self._redis.close()