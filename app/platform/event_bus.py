import asyncio
import logging
from app.core.metrics import metrics

logger = logging.getLogger("ShadePlatform")

class EventBus:
    def __init__(self):
        self.subscribers = {}

    def subscribe(self, event_type: str, callback):
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(callback)

    def publish(self, event_type: str, payload: dict) -> None:
        metrics.events_published.labels(event_type=event_type).inc()
        if event_type not in self.subscribers:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running event loop — publish() called from sync context.
            # Log and skip rather than crashing.
            logger.warning({
                "event": "event_bus_no_running_loop",
                "event_type": event_type,
                "subscriber_count": len(self.subscribers[event_type]),
            })
            return
        for callback in self.subscribers[event_type]:
            loop.create_task(self._safe_execute(callback, payload))
                
    async def _safe_execute(self, callback, payload):
        try:
            await callback(payload)
        except Exception as e:
            logger.error({"event": "bus_error", "error": str(e)})
