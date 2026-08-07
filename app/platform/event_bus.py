import asyncio
import logging
from app.core.metrics import metrics

logger = logging.getLogger("ShadePlatform")

class EventBus:
    """Phase 5: Domain Event Bus for Decoupling"""
    def __init__(self):
        self.subscribers = {}

    def subscribe(self, event_type: str, callback):
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(callback)

    def publish(self, event_type: str, payload: dict):
        metrics.events_published.labels(event_type=event_type).inc()
        if event_type in self.subscribers:
            for callback in self.subscribers[event_type]:
                asyncio.create_task(self._safe_execute(callback, payload))
                
    async def _safe_execute(self, callback, payload):
        try:
            await callback(payload)
        except Exception as e:
            logger.error({"event": "bus_error", "error": str(e)})
