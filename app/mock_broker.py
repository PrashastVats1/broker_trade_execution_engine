from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

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


@dataclass
class MockBrokerState:
    holdings: list[Holding] = field(default_factory=list)
    orders: dict[str, BrokerOrderResult] = field(default_factory=dict)
    reject_symbols: set[str] = field(default_factory=set)
    timeout_symbols: set[str] = field(default_factory=set)
    notification_fail: bool = False


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
        result = BrokerOrderResult(
            OrderStatus.EXECUTED,
            broker_id,
            order.quantity,
            Decimal("100.00"),
            "mock fill",
        )
        self.state.orders[order.client_order_id] = result
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
