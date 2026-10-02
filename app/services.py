from __future__ import annotations

import asyncio
import hashlib
import json
from uuid import UUID

from app.brokers import BrokerAdapter, BrokerRegistry
from app.domain import (
    BrokerName,
    BrokerOrderRequest,
    ExecutionRequest,
    ExecutionStatus,
    ExecutionView,
    ExistingHoldingsError,
    InstrumentInput,
    OrderInstruction,
    OrderRejectedError,
    OrderStatus,
    OrderStatusUnknownError,
    Side,
    TradeEngineError,
    Workflow,
    aggregate_execution_status,
)
from app.notifications import NotificationService
from app.persistence import ExecutionRepository, OrderRecord


class ExecutionService:
    def __init__(
        self,
        repository: ExecutionRepository,
        registry: BrokerRegistry,
        notifier: NotificationService,
        *,
        allow_live_trading: bool = False,
        poll_attempts: int = 2,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.notifier = notifier
        self.allow_live_trading = allow_live_trading
        self.poll_attempts = poll_attempts
        self.poll_interval_seconds = poll_interval_seconds

    async def execute(self, request: ExecutionRequest, idempotency_key: str) -> ExecutionView:
        adapter = self.registry.get(request.broker)
        if adapter.live and (not self.allow_live_trading or not request.confirm_live):
            raise PermissionError(
                "live broker execution requires ALLOW_LIVE_TRADING=true and confirm_live=true"
            )
        instructions = await self._instructions(request, adapter)
        request_hash = hashlib.sha256(
            request.model_dump_json(exclude={"confirm_live"}).encode()
        ).hexdigest()
        execution_id, created = await self.repository.create_or_get(
            request.broker,
            request.workflow,
            idempotency_key,
            request_hash,
            instructions,
        )
        if not created:
            existing = await self.repository.view(execution_id)
            if existing is None:
                raise RuntimeError("idempotent execution disappeared")
            return existing

        await self.repository.set_execution_status(execution_id, ExecutionStatus.RUNNING)
        record = await self.repository.get_record(execution_id)
        if record is None:
            raise RuntimeError("execution disappeared")
        for order in record.orders:
            await self._execute_order(adapter, order)

        await self._finalize(execution_id)
        view = await self.repository.view(execution_id)
        if view is None:
            raise RuntimeError("execution disappeared")
        return view

    async def _instructions(
        self, request: ExecutionRequest, adapter: BrokerAdapter
    ) -> list[OrderInstruction]:
        if request.workflow == Workflow.REBALANCE:
            return list(request.orders or [])
        holdings = await adapter.get_holdings()
        if any(holding.quantity > 0 for holding in holdings):
            raise ExistingHoldingsError(
                "FIRST_TIME is only valid when the broker account has no holdings"
            )
        return [
            OrderInstruction(
                symbol=item.symbol,
                exchange=item.exchange,
                segment=item.segment,
                isin=item.isin,
                quantity=item.quantity,
                side=Side.BUY,
            )
            for item in request.portfolio or []
        ]

    async def _execute_order(self, adapter: BrokerAdapter, order: OrderRecord) -> None:
        try:
            resolved = await adapter.resolve_instrument(
                InstrumentInput(
                    symbol=order.symbol,
                    exchange=order.exchange,
                    segment=order.segment,
                    isin=order.isin,
                )
            )
            await self.repository.update_order(
                order.id,
                status=OrderStatus.SUBMITTING,
                broker_symbol=resolved.broker_symbol,
                broker_token=resolved.broker_token,
            )
            result = await adapter.place_order(
                BrokerOrderRequest(
                    instrument=resolved,
                    side=Side(order.side),
                    quantity=order.quantity,
                    client_order_id=order.client_order_id,
                    product=order.product,
                    order_type=order.order_type,
                    validity=order.validity,
                    price=order.price,
                )
            )
            await self.repository.update_order(
                order.id,
                status=result.status,
                broker_order_id=result.broker_order_id,
                filled_quantity=result.filled_quantity,
                average_price=result.average_price,
                error_message=result.message,
            )
            if result.status in {
                OrderStatus.SUBMITTED,
                OrderStatus.OPEN,
                OrderStatus.PARTIALLY_FILLED,
            }:
                await self._poll(adapter, order, result.broker_order_id)
        except OrderStatusUnknownError as exc:
            await self.repository.update_order(
                order.id,
                status=OrderStatus.UNKNOWN,
                error_code=exc.code,
                error_message=str(exc),
            )
        except OrderRejectedError as exc:
            await self.repository.update_order(
                order.id,
                status=OrderStatus.REJECTED,
                error_code=exc.code,
                error_message=str(exc),
            )
        except TradeEngineError as exc:
            await self.repository.update_order(
                order.id,
                status=OrderStatus.FAILED,
                error_code=exc.code,
                error_message=str(exc),
            )
        except Exception as exc:
            await self.repository.update_order(
                order.id,
                status=OrderStatus.FAILED,
                error_code="unexpected_error",
                error_message=str(exc),
            )

    async def _poll(
        self, adapter: BrokerAdapter, order: OrderRecord, broker_order_id: str | None
    ) -> None:
        for attempt in range(self.poll_attempts):
            try:
                result = await adapter.get_order_status(
                    broker_order_id, order.client_order_id
                )
            except TradeEngineError as exc:
                await self.repository.update_order(
                    order.id,
                    status=OrderStatus.UNKNOWN,
                    broker_order_id=broker_order_id,
                    error_code=exc.code,
                    error_message=(
                        "Order was acknowledged, but status reconciliation failed: "
                        f"{exc}"
                    ),
                )
                return
            await self.repository.update_order(
                order.id,
                status=result.status,
                broker_order_id=result.broker_order_id,
                filled_quantity=result.filled_quantity,
                average_price=result.average_price,
                error_message=result.message,
            )
            if result.status not in {
                OrderStatus.SUBMITTED,
                OrderStatus.OPEN,
                OrderStatus.PARTIALLY_FILLED,
            }:
                return
            if attempt + 1 < self.poll_attempts:
                await asyncio.sleep(self.poll_interval_seconds)

    async def reconcile(self, execution_id: UUID) -> ExecutionView:
        record = await self.repository.get_record(execution_id)
        if record is None:
            raise LookupError(execution_id)
        adapter = self.registry.get(BrokerName(record.broker))
        for order in record.orders:
            if OrderStatus(order.status) in {
                OrderStatus.UNKNOWN,
                OrderStatus.SUBMITTED,
                OrderStatus.OPEN,
                OrderStatus.PARTIALLY_FILLED,
            }:
                try:
                    result = await adapter.get_order_status(
                        order.broker_order_id, order.client_order_id
                    )
                    await self.repository.update_order(
                        order.id,
                        status=result.status,
                        broker_order_id=result.broker_order_id,
                        filled_quantity=result.filled_quantity,
                        average_price=result.average_price,
                        error_message=result.message,
                    )
                except TradeEngineError:
                    continue
        await self._finalize(execution_id)
        view = await self.repository.view(execution_id)
        if view is None:
            raise LookupError(execution_id)
        return view

    async def _finalize(self, execution_id: UUID) -> None:
        record = await self.repository.get_record(execution_id)
        if record is None:
            raise LookupError(execution_id)
        status = aggregate_execution_status([OrderStatus(order.status) for order in record.orders])
        await self.repository.set_execution_status(execution_id, status)
        view = await self.repository.view(execution_id)
        if view is None:
            raise LookupError(execution_id)
        try:
            await self.notifier.notify(view)
        except Exception:
            await self.repository.set_notification_status(execution_id, "FAILED")
        else:
            await self.repository.set_notification_status(execution_id, "SENT")


def execution_json(view: ExecutionView) -> str:
    return json.dumps(view.model_dump(mode="json"), sort_keys=True)
