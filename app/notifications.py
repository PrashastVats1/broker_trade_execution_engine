from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

import httpx

from app.domain import ExecutionView

logger = logging.getLogger("kalpi.notifications")


class NotificationService(ABC):
    @abstractmethod
    async def notify(self, execution: ExecutionView) -> None: ...


class ConsoleNotifier(NotificationService):
    async def notify(self, execution: ExecutionView) -> None:
        logger.info(
            "execution_completed %s",
            json.dumps(
                {
                    "execution_id": str(execution.id),
                    "status": execution.status.value,
                    "broker": execution.broker.value,
                    "orders": [
                        {
                            "symbol": order.symbol,
                            "side": order.side.value,
                            "quantity": order.quantity,
                            "filled_quantity": order.filled_quantity,
                            "status": order.status.value,
                            "error": order.error_message,
                        }
                        for order in execution.orders
                    ],
                }
            ),
        )


class WebhookNotifier(NotificationService):
    def __init__(self, url: str, client: httpx.AsyncClient | None = None) -> None:
        self.url = url
        self.client = client or httpx.AsyncClient(timeout=5.0)

    async def notify(self, execution: ExecutionView) -> None:
        response = await self.client.post(
            self.url, json=execution.model_dump(mode="json"), follow_redirects=False
        )
        response.raise_for_status()


class CompositeNotifier(NotificationService):
    def __init__(self, notifiers: list[NotificationService]) -> None:
        self.notifiers = notifiers

    async def notify(self, execution: ExecutionView) -> None:
        errors: list[Exception] = []
        for notifier in self.notifiers:
            try:
                await notifier.notify(execution)
            except Exception as exc:  # notification failures are deliberately isolated
                errors.append(exc)
        if errors:
            raise ExceptionGroup("one or more notifications failed", errors)
