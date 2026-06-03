import asyncio
from typing import Callable, Dict, List, Any

class AsyncEventBus:
    def __init__(self):
        self.subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable):
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        if callback not in self.subscribers[event_type]:
            self.subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable):
        if event_type in self.subscribers and callback in self.subscribers[event_type]:
            self.subscribers[event_type].remove(callback)

    async def publish(self, event_type: str, payload: Any = None):
        """Publish an event asynchronously to all subscribers."""
        if event_type in self.subscribers:
            for callback in self.subscribers[event_type]:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(payload))
                else:
                    # Call synchronous callbacks immediately
                    callback(payload)

# Global instance for MVP
bus = AsyncEventBus()
