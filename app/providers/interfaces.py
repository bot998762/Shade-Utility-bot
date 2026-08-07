from typing import Protocol

class IOCRProvider(Protocol):
    async def parse_image(self, photo_bytes: bytes) -> str: ...
