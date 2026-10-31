from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.brokers import BrokerAdapter
from app.domain import (
    BrokerName,
    BrokerOrderRequest,
    BrokerOrderResult,
    Holding,
    InstrumentInput,
    OrderRejectedError,
    OrderStatus,
    OrderStatusUnknownError,
    ResolvedInstrument,
)

logger = logging.getLogger("kalpi.mock")


class MockScenario(StrEnum):
    NORMAL = "NORMAL"
    EXECUTED_BUT_RESPONSE_TIMEOUT = "EXECUTED_BUT_RESPONSE_TIMEOUT"


def parse_mock_scenario(value: str) -> MockScenario:
    try:
        return MockScenario(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported mock broker scenario: {value}") from exc


@dataclass
class MockBrokerState:
    holdings: list[Holding] = field(default_factory=list)
    orders: dict[str, BrokerOrderResult] = field(default_factory=dict)
    reject_symbols: set[str] = field(default_factory=set)
    timeout_symbols: set[str] = field(default_factory=set)
    scenario: MockScenario = MockScenario.NORMAL
    recorded_executions: int = 0


class MockBrokerAdapter(BrokerAdapter):
    name = BrokerName.MOCK
    live = False

    def __init__(self, state: MockBrokerState | None = None) -> None:
        self.state = state or MockBrokerState()

    async def get_holdings(self) -> list[Holding]:
        return list(self.state.holdings)

    async def resolve_instrument(self, instrument: InstrumentInput) -> ResolvedInstrument:
        return ResolvedInstrument(
            symbol=instrument.symbol,
            exchange=instrument.exchange,
            segment=instrument.segment,
            isin=instrument.isin,
            broker_symbol=instrument.symbol,
            broker_token=f"{instrument.exchange}:{instrument.symbol}",
        )

    async def place_order(self, order: BrokerOrderRequest) -> BrokerOrderResult:
        if order.instrument.symbol in self.state.timeout_symbols:
            raise OrderStatusUnknownError("mock accepted order but response was lost")
        if order.instrument.symbol in self.state.reject_symbols:
            raise OrderRejectedError("mock rejection: insufficient funds")
        broker_id = f"mock-{len(self.state.orders) + 1}"
        response_lost = self.state.scenario == MockScenario.EXECUTED_BUT_RESPONSE_TIMEOUT
        result = BrokerOrderResult(
            OrderStatus.EXECUTED,
            broker_id,
            order.quantity,
            Decimal("100.00"),
            (
                "Executed at the mock broker before the response timed out"
                if response_lost
                else "mock fill"
            ),
        )
        self.state.orders[order.client_order_id] = result
        self.state.recorded_executions += 1
        if response_lost:
            logger.info(
                "mock broker executed client_order_id=%s broker_order_id=%s "
                "then dropped the response",
                order.client_order_id,
                broker_id,
            )
            raise OrderStatusUnknownError(
                "Mock broker executed the order but the response timed out "
                "before reaching the application"
            )
        return result

    async def get_order_status(
        self, broker_order_id: str | None, client_order_id: str
    ) -> BrokerOrderResult:
        return self.state.orders.get(
            client_order_id,
            BrokerOrderResult(OrderStatus.UNKNOWN, broker_order_id, message="not found"),
        )

    async def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        return BrokerOrderResult(OrderStatus.CANCELLED, broker_order_id)
