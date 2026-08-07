from app.platform.failover import ProviderFailoverEngine
from app.platform.event_bus import EventBus

class OCRService:
    def __init__(self, failover_engine: ProviderFailoverEngine, event_bus: EventBus):
        self.engine = failover_engine
        self.event_bus = event_bus

    async def extract_text(self, photo_bytes: bytes, user_id: int) -> str:
        text = await self.engine.execute("parse_image", photo_bytes)
        # Phase 5: Emit domain event
        self.event_bus.publish("ocr_processed", {"user_id": user_id, "length": len(text)})
        return text
