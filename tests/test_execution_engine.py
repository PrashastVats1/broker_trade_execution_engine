from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from pydantic import ValidationError

from app.brokers import BrokerRegistry
from app.domain import (
    BrokerName,
    BrokerOrderResult,
    BrokerUnavailableError,
    ExecutionRequest,
    ExecutionStatus,
    ExistingHoldingsError,
    Holding,
    IdempotencyConflictError,
    InstrumentInput,
    OrderInstruction,
    OrderStatus,
    PortfolioItem,
    ResolvedInstrument,
    Side,
    Workflow,
)
from app.mock_broker import MockBrokerAdapter, MockBrokerState
from app.notifications import NotificationService
from app.persistence import ExecutionRepository, create_engine_and_session, create_schema
from app.services import ExecutionService


@dataclass
class RecordingNotifier(NotificationService):
    fail: bool = False
    execution_ids: list[str] = field(default_factory=list)

    async def notify(self, execution) -> None:  # type: ignore[no-untyped-def]
        self.execution_ids.append(str(execution.id))
        if self.fail:
            raise RuntimeError("notification unavailable")


@pytest.fixture
async def service_factory(tmp_path) -> AsyncIterator:  # type: ignore[no-untyped-def]
    engines = []

    async def build(
        state: MockBrokerState | None = None,
        notifier: RecordingNotifier | None = None,
    ) -> tuple[ExecutionService, RecordingNotifier]:
        database = tmp_path / f"test-{len(engines)}.db"
        engine, sessions = create_engine_and_session(f"sqlite+aiosqlite:///{database}")
        engines.append(engine)
        await create_schema(engine)
        adapter = MockBrokerAdapter(state)
        registry = BrokerRegistry()
        registry.register(BrokerName.MOCK, lambda: adapter)
        actual_notifier = notifier or RecordingNotifier()
        return (
            ExecutionService(
                ExecutionRepository(sessions),
                registry,
                actual_notifier,
                poll_interval_seconds=0,
            ),
            actual_notifier,
        )

    yield build
    for engine in engines:
        await engine.dispose()


@pytest.mark.asyncio
async def test_first_time_portfolio_buys_all_items(service_factory) -> None:  # type: ignore[no-untyped-def]
    service, notifier = await service_factory()
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.FIRST_TIME,
        portfolio=[
            PortfolioItem(symbol="RELIANCE", quantity=10),
            PortfolioItem(symbol="TCS", quantity=5),
        ],
    )

    result = await service.execute(request, "first-time-1")

    assert result.status == ExecutionStatus.SUCCESS
    assert [order.side for order in result.orders] == [Side.BUY, Side.BUY]
    assert [order.filled_quantity for order in result.orders] == [10, 5]
    assert result.notification_status == "SENT"
    assert notifier.execution_ids == [str(result.id)]


@pytest.mark.asyncio
async def test_first_time_rejects_nonempty_account(service_factory) -> None:  # type: ignore[no-untyped-def]
    state = MockBrokerState(
        holdings=[
            Holding(
                ResolvedInstrument("RELIANCE", "NSE", broker_symbol="RELIANCE"),
                1,
            )
        ]
    )
    service, _ = await service_factory(state)
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.FIRST_TIME,
        portfolio=[PortfolioItem(symbol="TCS", quantity=1)],
    )

    with pytest.raises(ExistingHoldingsError):
        await service.execute(request, "not-empty")


@pytest.mark.asyncio
async def test_mixed_rebalance_preserves_instruction_order(service_factory) -> None:  # type: ignore[no-untyped-def]
    service, _ = await service_factory()
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.REBALANCE,
        orders=[
            OrderInstruction(symbol="RELIANCE", quantity=5, side=Side.SELL),
            OrderInstruction(symbol="INFY", quantity=10, side=Side.BUY),
            OrderInstruction(symbol="TCS", quantity=2, side=Side.SELL),
        ],
    )

    result = await service.execute(request, "rebalance-1")

    assert result.status == ExecutionStatus.SUCCESS
    assert [(order.symbol, order.side, order.quantity) for order in result.orders] == [
        ("RELIANCE", Side.SELL, 5),
        ("INFY", Side.BUY, 10),
        ("TCS", Side.SELL, 2),
    ]


@pytest.mark.asyncio
async def test_partial_failure_keeps_successful_trades(service_factory) -> None:  # type: ignore[no-untyped-def]
    state = MockBrokerState(reject_symbols={"INFY"})
    service, _ = await service_factory(state)
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.REBALANCE,
        orders=[
            OrderInstruction(symbol="RELIANCE", quantity=5, side=Side.SELL),
            OrderInstruction(symbol="INFY", quantity=10, side=Side.BUY),
            OrderInstruction(symbol="TCS", quantity=2, side=Side.SELL),
        ],
    )

    result = await service.execute(request, "partial-1")

    assert result.status == ExecutionStatus.PARTIAL_SUCCESS
    assert [order.status for order in result.orders] == [
        OrderStatus.EXECUTED,
        OrderStatus.REJECTED,
        OrderStatus.EXECUTED,
    ]
    assert result.orders[1].error_code == "order_rejected"
    assert "insufficient funds" in (result.orders[1].error_message or "")


@pytest.mark.asyncio
async def test_ambiguous_submission_is_unknown_and_not_retried(service_factory) -> None:  # type: ignore[no-untyped-def]
    state = MockBrokerState(timeout_symbols={"INFY"})
    service, _ = await service_factory(state)
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.REBALANCE,
        orders=[OrderInstruction(symbol="INFY", quantity=1, side=Side.BUY)],
    )

    result = await service.execute(request, "unknown-1")

    assert result.status == ExecutionStatus.RECONCILIATION_REQUIRED
    assert result.orders[0].status == OrderStatus.UNKNOWN
    assert state.orders == {}


@pytest.mark.asyncio
async def test_idempotent_replay_returns_existing_execution(service_factory) -> None:  # type: ignore[no-untyped-def]
    service, notifier = await service_factory()
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.REBALANCE,
        orders=[OrderInstruction(symbol="TCS", quantity=2, side=Side.BUY)],
    )

    first = await service.execute(request, "same-key")
    second = await service.execute(request, "same-key")

    assert second.id == first.id
    assert notifier.execution_ids == [str(first.id)]


@pytest.mark.asyncio
async def test_idempotency_key_payload_conflict(service_factory) -> None:  # type: ignore[no-untyped-def]
    service, _ = await service_factory()
    first = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.REBALANCE,
        orders=[OrderInstruction(symbol="TCS", quantity=2, side=Side.BUY)],
    )
    second = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.REBALANCE,
        orders=[OrderInstruction(symbol="TCS", quantity=3, side=Side.BUY)],
    )
    await service.execute(first, "conflict-key")

    with pytest.raises(IdempotencyConflictError):
        await service.execute(second, "conflict-key")


@pytest.mark.asyncio
async def test_notification_failure_does_not_change_trade_success(service_factory) -> None:  # type: ignore[no-untyped-def]
    service, _ = await service_factory(notifier=RecordingNotifier(fail=True))
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.REBALANCE,
        orders=[OrderInstruction(symbol="TCS", quantity=1, side=Side.BUY)],
    )

    result = await service.execute(request, "notify-fail")

    assert result.status == ExecutionStatus.SUCCESS
    assert result.notification_status == "FAILED"


def test_invalid_quantity_and_symbol_are_rejected() -> None:
    with pytest.raises(ValidationError):
        PortfolioItem(symbol="TCS", quantity=0)
    with pytest.raises(ValidationError):
        InstrumentInput(symbol="../TCS")


def test_limit_order_requires_price() -> None:
    with pytest.raises(ValidationError):
        OrderInstruction(symbol="TCS", quantity=1, side=Side.BUY, order_type="LIMIT")


def test_adapter_registry_extension_does_not_change_execution_engine() -> None:
    registry = BrokerRegistry()
    adapter = MockBrokerAdapter()
    registry.register(BrokerName.MOCK, lambda: adapter)

    assert registry.get(BrokerName.MOCK) is adapter
    assert registry.names() == [BrokerName.MOCK]


@pytest.mark.asyncio
async def test_acknowledged_order_with_failed_status_lookup_requires_reconciliation(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    class StatusUnavailableBroker(MockBrokerAdapter):
        async def place_order(self, order):  # type: ignore[no-untyped-def]
            return BrokerOrderResult(OrderStatus.SUBMITTED, "accepted-1")

        async def get_order_status(
            self, broker_order_id, client_order_id  # type: ignore[no-untyped-def]
        ):
            raise BrokerUnavailableError("status API unavailable")

    engine, sessions = create_engine_and_session(
        f"sqlite+aiosqlite:///{tmp_path / 'status-unavailable.db'}"
    )
    await create_schema(engine)
    registry = BrokerRegistry()
    adapter = StatusUnavailableBroker()
    registry.register(BrokerName.MOCK, lambda: adapter)
    service = ExecutionService(
        ExecutionRepository(sessions),
        registry,
        RecordingNotifier(),
        poll_interval_seconds=0,
    )
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.REBALANCE,
        orders=[OrderInstruction(symbol="TCS", quantity=1, side=Side.BUY)],
    )

    result = await service.execute(request, "status-unavailable")
    await engine.dispose()

    assert result.status == ExecutionStatus.RECONCILIATION_REQUIRED
    assert result.orders[0].status == OrderStatus.UNKNOWN
    assert result.orders[0].broker_order_id == "accepted-1"
    assert "acknowledged" in (result.orders[0].error_message or "")
