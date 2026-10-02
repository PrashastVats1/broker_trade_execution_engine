from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BrokerName(StrEnum):
    MOCK = "mock"
    ZERODHA = "zerodha"
    DHAN = "dhan"
    ANGEL_ONE = "angel_one"
    GROWW = "groww"
    UPSTOX = "upstox"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class Workflow(StrEnum):
    FIRST_TIME = "FIRST_TIME"
    REBALANCE = "REBALANCE"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class ExecutionStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


TERMINAL_ORDER_STATUSES = {
    OrderStatus.EXECUTED,
    OrderStatus.REJECTED,
    OrderStatus.FAILED,
    OrderStatus.CANCELLED,
}


class TradeEngineError(Exception):
    code = "trade_engine_error"


class BrokerAuthenticationError(TradeEngineError):
    code = "broker_authentication_error"


class BrokerRateLimitError(TradeEngineError):
    code = "broker_rate_limit"


class BrokerUnavailableError(TradeEngineError):
    code = "broker_unavailable"


class OrderRejectedError(TradeEngineError):
    code = "order_rejected"


class OrderStatusUnknownError(TradeEngineError):
    code = "order_status_unknown"


class InstrumentResolutionError(TradeEngineError):
    code = "instrument_resolution_error"


class DeliveryAuthorizationRequired(TradeEngineError):
    code = "delivery_authorization_required"


class IdempotencyConflictError(TradeEngineError):
    code = "idempotency_conflict"


class ExistingHoldingsError(TradeEngineError):
    code = "existing_holdings"


class InstrumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(pattern=r"^[A-Z0-9][A-Z0-9&._-]{0,29}$")
    exchange: str = Field(default="NSE", pattern=r"^(NSE|BSE)$")
    segment: str = Field(default="CASH", pattern=r"^CASH$")
    isin: str | None = Field(default=None, pattern=r"^IN[A-Z0-9]{10}$")


class PortfolioItem(InstrumentInput):
    quantity: int = Field(gt=0, le=1_000_000)


class OrderInstruction(PortfolioItem):
    side: Side
    product: str = Field(default="DELIVERY", pattern=r"^(DELIVERY|INTRADAY)$")
    order_type: str = Field(default="MARKET", pattern=r"^(MARKET|LIMIT)$")
    validity: str = Field(default="DAY", pattern=r"^(DAY|IOC)$")
    price: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def limit_requires_price(self) -> OrderInstruction:
        if self.order_type == "LIMIT" and self.price is None:
            raise ValueError("price is required for LIMIT orders")
        if self.order_type == "MARKET" and self.price is not None:
            raise ValueError("price is not accepted for MARKET orders")
        return self


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    broker: BrokerName
    workflow: Workflow
    portfolio: list[PortfolioItem] | None = None
    orders: list[OrderInstruction] | None = None
    confirm_live: bool = False

    @model_validator(mode="after")
    def validate_workflow_payload(self) -> ExecutionRequest:
        if self.workflow == Workflow.FIRST_TIME:
            if not self.portfolio or self.orders is not None:
                raise ValueError("FIRST_TIME requires portfolio and forbids orders")
        elif not self.orders or self.portfolio is not None:
            raise ValueError("REBALANCE requires orders and forbids portfolio")
        return self


@dataclass(frozen=True, slots=True)
class ResolvedInstrument:
    symbol: str
    exchange: str
    segment: str = "CASH"
    isin: str | None = None
    broker_token: str | None = None
    broker_symbol: str | None = None


@dataclass(frozen=True, slots=True)
class Holding:
    instrument: ResolvedInstrument
    quantity: int


@dataclass(frozen=True, slots=True)
class BrokerOrderRequest:
    instrument: ResolvedInstrument
    side: Side
    quantity: int
    client_order_id: str
    product: str = "DELIVERY"
    order_type: str = "MARKET"
    validity: str = "DAY"
    price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class BrokerOrderResult:
    status: OrderStatus
    broker_order_id: str | None = None
    filled_quantity: int = 0
    average_price: Decimal | None = None
    message: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class OrderView(BaseModel):
    id: UUID
    client_order_id: str
    symbol: str
    exchange: str
    side: Side
    quantity: int
    filled_quantity: int
    status: OrderStatus
    broker_order_id: str | None = None
    average_price: Decimal | None = None
    error_code: str | None = None
    error_message: str | None = None


class ExecutionView(BaseModel):
    id: UUID
    broker: BrokerName
    workflow: Workflow
    status: ExecutionStatus
    notification_status: str
    created_at: datetime
    updated_at: datetime
    orders: list[OrderView]


def new_id() -> UUID:
    return uuid4()


def utc_now() -> datetime:
    return datetime.now(UTC)


def aggregate_execution_status(statuses: list[OrderStatus]) -> ExecutionStatus:
    if any(
        status
        in {
            OrderStatus.UNKNOWN,
            OrderStatus.SUBMITTED,
            OrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED,
        }
        for status in statuses
    ):
        return ExecutionStatus.RECONCILIATION_REQUIRED
    successes = sum(status == OrderStatus.EXECUTED for status in statuses)
    if successes == len(statuses):
        return ExecutionStatus.SUCCESS
    if successes:
        return ExecutionStatus.PARTIAL_SUCCESS
    return ExecutionStatus.FAILED
