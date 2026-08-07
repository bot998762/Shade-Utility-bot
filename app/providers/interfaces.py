from typing import Protocol

class IOCRProvider(Protocol):
    async def parse_image(self, photo_bytes: bytes) -> str: ...

class IUrlProvider(Protocol):
    async def create_short_url(self, target_url: str) -> str: ...
