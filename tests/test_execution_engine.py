from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from pydantic import ValidationError

from app.brokers import BrokerCredentials, BrokerRegistry
from app.domain import (
    BrokerName,
    BrokerOrderRequest,
    BrokerOrderResult,
    BrokerUnavailableError,
    ExecutionRequest,
    ExecutionStatus,
    ExistingHoldingsError,
    Holding,
    IdempotencyConflictError,
    InstrumentInput,
    InvalidOrderTransitionError,
    OrderInstruction,
    OrderStatus,
    OrderStatusUnknownError,
    PortfolioItem,
    ResolvedInstrument,
    Side,
    Workflow,
)
from app.mock_broker import MockBrokerAdapter, MockBrokerState, MockScenario
from app.notifications import NotificationService
from app.persistence import (
    ExecutionRepository,
    create_engine_and_session,
    create_schema,
)
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
        adapter: MockBrokerAdapter | None = None,
        repository_type: type[ExecutionRepository] = ExecutionRepository,
    ) -> tuple[ExecutionService, RecordingNotifier]:
        database = tmp_path / f"test-{len(engines)}.db"
        engine, sessions = create_engine_and_session(f"sqlite+aiosqlite:///{database}")
        engines.append(engine)
        await create_schema(engine)
        actual_adapter = adapter or MockBrokerAdapter(state)
        registry = BrokerRegistry()
        registry.register(BrokerName.MOCK, lambda: actual_adapter)
        actual_notifier = notifier or RecordingNotifier()
        return (
            ExecutionService(
                repository_type(sessions),
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
async def test_first_time_partial_failure_keeps_successful_buy(service_factory) -> None:  # type: ignore[no-untyped-def]
    state = MockBrokerState(reject_symbols={"INFY"})
    service, _ = await service_factory(state)
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.FIRST_TIME,
        portfolio=[
            PortfolioItem(symbol="RELIANCE", quantity=4),
            PortfolioItem(symbol="INFY", quantity=2),
        ],
    )

    result = await service.execute(request, "first-time-partial")

    assert result.status == ExecutionStatus.PARTIAL_SUCCESS
    assert [(order.symbol, order.side, order.status) for order in result.orders] == [
        ("RELIANCE", Side.BUY, OrderStatus.EXECUTED),
        ("INFY", Side.BUY, OrderStatus.REJECTED),
    ]
    assert result.orders[0].filled_quantity == 4


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
    assert state.recorded_executions == 0


@pytest.mark.asyncio
async def test_normal_mock_execution_records_one_fill(service_factory) -> None:  # type: ignore[no-untyped-def]
    state = MockBrokerState(scenario=MockScenario.NORMAL)
    service, _ = await service_factory(state)
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.REBALANCE,
        orders=[OrderInstruction(symbol="INFY", quantity=1, side=Side.BUY)],
    )

    result = await service.execute(request, "normal-mock-1")

    assert result.status == ExecutionStatus.SUCCESS
    assert result.orders[0].status == OrderStatus.EXECUTED
    assert result.orders[0].broker_order_id == "mock-1"
    assert state.recorded_executions == 1


@pytest.mark.asyncio
async def test_executed_response_timeout_reconciles_original_fill(service_factory) -> None:  # type: ignore[no-untyped-def]
    state = MockBrokerState(scenario=MockScenario.EXECUTED_BUT_RESPONSE_TIMEOUT)
    service, _ = await service_factory(state)
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.REBALANCE,
        orders=[
            OrderInstruction(symbol="INFY", quantity=1, side=Side.BUY),
            OrderInstruction(symbol="TCS", quantity=2, side=Side.BUY),
        ],
    )

    result = await service.execute(request, "lost-response-1")

    assert result.status == ExecutionStatus.RECONCILIATION_REQUIRED
    assert result.orders[0].status == OrderStatus.UNKNOWN
    assert result.orders[0].broker_order_id is None
    assert "timed out" in (result.orders[0].error_message or "")
    assert result.orders[1].status == OrderStatus.SKIPPED
    assert state.recorded_executions == 1
    stored = next(iter(state.orders.values()))
    assert stored.status == OrderStatus.EXECUTED
    assert stored.broker_order_id == "mock-1"
    assert stored.filled_quantity == 1

    replay = await service.execute(request, "lost-response-1")
    assert replay.id == result.id
    assert state.recorded_executions == 1

    reconciled = await service.reconcile(result.id)
    assert reconciled.orders[0].status == OrderStatus.EXECUTED
    assert reconciled.orders[0].broker_order_id == "mock-1"
    assert reconciled.orders[0].filled_quantity == 1
    assert reconciled.orders[1].status == OrderStatus.SKIPPED
    assert reconciled.status == ExecutionStatus.PARTIAL_SUCCESS
    assert state.recorded_executions == 1

    repeated = await service.reconcile(result.id)
    assert repeated.orders[0].status == OrderStatus.EXECUTED
    assert repeated.orders[0].broker_order_id == "mock-1"
    assert state.recorded_executions == 1
    assert len(state.orders) == 1


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


@pytest.mark.asyncio
async def test_unknown_reconciles_to_executed_without_resubmission(service_factory) -> None:  # type: ignore[no-untyped-def]
    class AcceptedWithLostResponseBroker(MockBrokerAdapter):
        place_calls = 0

        async def place_order(self, order: BrokerOrderRequest) -> BrokerOrderResult:
            self.place_calls += 1
            self.state.orders[order.client_order_id] = BrokerOrderResult(
                OrderStatus.EXECUTED,
                "accepted-1",
                order.quantity,
            )
            raise OrderStatusUnknownError("response lost after acceptance")

    adapter = AcceptedWithLostResponseBroker()
    service, _ = await service_factory(adapter=adapter)
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.REBALANCE,
        orders=[OrderInstruction(symbol="TCS", quantity=2, side=Side.BUY)],
    )

    initial = await service.execute(request, "reconcile-unknown")
    reconciled = await service.reconcile(initial.id)

    assert initial.orders[0].status == OrderStatus.UNKNOWN
    assert reconciled.status == ExecutionStatus.SUCCESS
    assert reconciled.orders[0].status == OrderStatus.EXECUTED
    assert adapter.place_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reconciled_status", [OrderStatus.EXECUTED, OrderStatus.REJECTED])
async def test_submitting_order_can_be_reconciled(
    service_factory, reconciled_status: OrderStatus  # type: ignore[no-untyped-def]
) -> None:
    class CorrelationBroker(MockBrokerAdapter):
        async def get_order_status(
            self, broker_order_id: str | None, client_order_id: str
        ) -> BrokerOrderResult:
            assert broker_order_id is None
            return BrokerOrderResult(
                reconciled_status,
                "found-by-correlation",
                1 if reconciled_status == OrderStatus.EXECUTED else 0,
            )

    service, _ = await service_factory(adapter=CorrelationBroker())
    instructions = [OrderInstruction(symbol="TCS", quantity=1, side=Side.BUY)]
    execution_id, _ = await service.repository.create_or_get(
        BrokerName.MOCK,
        Workflow.REBALANCE,
        f"submitting-{reconciled_status.value}",
        f"hash-{reconciled_status.value}",
        instructions,
    )
    record = await service.repository.get_record(execution_id)
    assert record is not None
    await service.repository.update_order(
        record.orders[0].id,
        status=OrderStatus.SUBMITTING,
    )

    result = await service.reconcile(execution_id)

    assert result.orders[0].status == reconciled_status
    assert result.orders[0].broker_order_id == "found-by-correlation"


@pytest.mark.asyncio
async def test_broker_acceptance_followed_by_db_failure_becomes_unknown(
    service_factory,
) -> None:  # type: ignore[no-untyped-def]
    class FailAcknowledgementOnceRepository(ExecutionRepository):
        failed = False

        async def update_order(
            self,
            order_id,  # type: ignore[no-untyped-def]
            *,
            status: OrderStatus,
            **kwargs,  # type: ignore[no-untyped-def]
        ) -> None:
            if status == OrderStatus.EXECUTED and not self.failed:
                self.failed = True
                raise RuntimeError("simulated commit failure")
            await super().update_order(order_id, status=status, **kwargs)

    service, _ = await service_factory(repository_type=FailAcknowledgementOnceRepository)
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.REBALANCE,
        orders=[OrderInstruction(symbol="TCS", quantity=1, side=Side.BUY)],
    )

    result = await service.execute(request, "db-after-acceptance")

    assert result.status == ExecutionStatus.RECONCILIATION_REQUIRED
    assert result.orders[0].status == OrderStatus.UNKNOWN
    assert result.orders[0].broker_order_id == "mock-1"
    assert result.orders[0].error_code == "broker_ack_persistence_failed"


@pytest.mark.asyncio
async def test_unknown_stops_and_skips_subsequent_orders(service_factory) -> None:  # type: ignore[no-untyped-def]
    state = MockBrokerState(timeout_symbols={"INFY"})
    service, _ = await service_factory(state)
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.REBALANCE,
        orders=[
            OrderInstruction(symbol="INFY", quantity=1, side=Side.BUY),
            OrderInstruction(symbol="TCS", quantity=1, side=Side.BUY),
        ],
    )

    result = await service.execute(request, "unknown-stops")

    assert result.status == ExecutionStatus.RECONCILIATION_REQUIRED
    assert [order.status for order in result.orders] == [
        OrderStatus.UNKNOWN,
        OrderStatus.SKIPPED,
    ]
    assert state.orders == {}


@pytest.mark.asyncio
async def test_executed_unknown_skips_remaining_orders(service_factory) -> None:  # type: ignore[no-untyped-def]
    class CountingBroker(MockBrokerAdapter):
        def __init__(self, state: MockBrokerState) -> None:
            super().__init__(state)
            self.resolved: list[str] = []
            self.placed: list[str] = []

        async def resolve_instrument(self, instrument: InstrumentInput):  # type: ignore[no-untyped-def]
            self.resolved.append(instrument.symbol)
            return await super().resolve_instrument(instrument)

        async def place_order(self, order: BrokerOrderRequest) -> BrokerOrderResult:
            self.placed.append(order.instrument.symbol)
            return await super().place_order(order)

    state = MockBrokerState(timeout_symbols={"INFY"})
    adapter = CountingBroker(state)
    service, _ = await service_factory(adapter=adapter)
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.REBALANCE,
        orders=[
            OrderInstruction(symbol="RELIANCE", quantity=1, side=Side.SELL),
            OrderInstruction(symbol="INFY", quantity=1, side=Side.BUY),
            OrderInstruction(symbol="TCS", quantity=1, side=Side.SELL),
        ],
    )

    result = await service.execute(request, "executed-unknown-skipped")

    assert result.status == ExecutionStatus.RECONCILIATION_REQUIRED
    assert [order.status for order in result.orders] == [
        OrderStatus.EXECUTED,
        OrderStatus.UNKNOWN,
        OrderStatus.SKIPPED,
    ]
    assert adapter.resolved == ["RELIANCE", "INFY"]
    assert adapter.placed == ["RELIANCE", "INFY"]
    assert set(state.orders) == {result.orders[0].client_order_id}


def test_broker_credentials_repr_hides_secrets() -> None:
    credentials = BrokerCredentials(
        api_key="public-key",
        access_token="access-token-value",
        api_secret="api-secret-value",
        client_id="client-1",
    )

    rendered = repr(credentials)

    assert "access-token-value" not in rendered
    assert "api-secret-value" not in rendered
    assert "access_token=<redacted>" in rendered
    assert "api_secret=<redacted>" in rendered


@pytest.mark.asyncio
async def test_first_time_idempotent_replay_precedes_changed_holdings(
    service_factory,
) -> None:  # type: ignore[no-untyped-def]
    state = MockBrokerState()
    service, _ = await service_factory(state)
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.FIRST_TIME,
        portfolio=[PortfolioItem(symbol="TCS", quantity=1)],
    )
    first = await service.execute(request, "first-time-replay")
    state.holdings.append(
        Holding(ResolvedInstrument("TCS", "NSE", broker_symbol="TCS"), 1)
    )

    replay = await service.execute(request, "first-time-replay")

    assert replay.id == first.id


@pytest.mark.asyncio
async def test_concurrent_identical_requests_return_one_execution(
    service_factory,
) -> None:  # type: ignore[no-untyped-def]
    class BarrierLookupRepository(ExecutionRepository):
        initial_lookups = 0
        both_initial_lookups = asyncio.Event()

        async def find_idempotent(
            self, idempotency_key: str, request_hash: str
        ):  # type: ignore[no-untyped-def]
            if self.initial_lookups < 2:
                self.initial_lookups += 1
                if self.initial_lookups == 2:
                    self.both_initial_lookups.set()
                await self.both_initial_lookups.wait()
                return None
            return await super().find_idempotent(idempotency_key, request_hash)

    service, notifier = await service_factory(repository_type=BarrierLookupRepository)
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.REBALANCE,
        orders=[OrderInstruction(symbol="TCS", quantity=1, side=Side.BUY)],
    )

    first, second = await asyncio.gather(
        service.execute(request, "concurrent-key"),
        service.execute(request, "concurrent-key"),
    )

    assert first.id == second.id
    record = await service.repository.get_record(first.id)
    assert record is not None
    assert len(record.orders) == 1
    assert notifier.execution_ids == [str(first.id)]


@pytest.mark.asyncio
async def test_invalid_terminal_transition_and_overfill_are_rejected(
    service_factory,
) -> None:  # type: ignore[no-untyped-def]
    service, _ = await service_factory()
    request = ExecutionRequest(
        broker=BrokerName.MOCK,
        workflow=Workflow.REBALANCE,
        orders=[OrderInstruction(symbol="TCS", quantity=1, side=Side.BUY)],
    )
    result = await service.execute(request, "invalid-transition")

    for invalid_target in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED):
        with pytest.raises(InvalidOrderTransitionError):
            await service.repository.update_order(
                result.orders[0].id,
                status=invalid_target,
            )
    with pytest.raises(ValueError, match="filled_quantity"):
        await service.repository.update_order(
            result.orders[0].id,
            status=OrderStatus.EXECUTED,
            filled_quantity=2,
        )

    cancelled_id, _ = await service.repository.create_or_get(
        BrokerName.MOCK,
        Workflow.REBALANCE,
        "cancelled-transition",
        "cancelled-transition-hash",
        [OrderInstruction(symbol="INFY", quantity=1, side=Side.BUY)],
    )
    cancelled_record = await service.repository.get_record(cancelled_id)
    assert cancelled_record is not None
    cancelled_order = cancelled_record.orders[0]
    await service.repository.update_order(
        cancelled_order.id,
        status=OrderStatus.SUBMITTING,
    )
    await service.repository.update_order(
        cancelled_order.id,
        status=OrderStatus.CANCELLED,
    )
    with pytest.raises(InvalidOrderTransitionError):
        await service.repository.update_order(
            cancelled_order.id,
            status=OrderStatus.OPEN,
        )
