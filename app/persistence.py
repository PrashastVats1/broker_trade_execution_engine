from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload

from app.domain import (
    BrokerName,
    ExecutionStatus,
    ExecutionView,
    IdempotencyConflictError,
    OrderInstruction,
    OrderStatus,
    OrderView,
    Side,
    Workflow,
    new_id,
    utc_now,
    validate_order_transition,
)


class Base(DeclarativeBase):
    pass


class ExecutionRecord(Base):
    __tablename__ = "executions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    broker: Mapped[str] = mapped_column(String(32))
    workflow: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default=ExecutionStatus.PENDING.value)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    notification_status: Mapped[str] = mapped_column(String(32), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    orders: Mapped[list[OrderRecord]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", order_by="OrderRecord.sequence"
    )


class OrderRecord(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
        CheckConstraint(
            "filled_quantity >= 0 AND filled_quantity <= quantity",
            name="ck_orders_filled_quantity_bounds",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("executions.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    client_order_id: Mapped[str] = mapped_column(String(30), unique=True)
    symbol: Mapped[str] = mapped_column(String(32))
    exchange: Mapped[str] = mapped_column(String(8))
    segment: Mapped[str] = mapped_column(String(16))
    isin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    broker_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    broker_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[int] = mapped_column(Integer)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    product: Mapped[str] = mapped_column(String(16))
    order_type: Mapped[str] = mapped_column(String(16))
    validity: Mapped[str] = mapped_column(String(8))
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    average_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=OrderStatus.PENDING.value)
    broker_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    execution: Mapped[ExecutionRecord] = relationship(back_populates="orders")


class ExecutionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def ping(self) -> None:
        async with self.session_factory() as session:
            await session.execute(text("SELECT 1"))

    async def create_or_get(
        self,
        broker: BrokerName,
        workflow: Workflow,
        idempotency_key: str,
        request_hash: str,
        orders: list[OrderInstruction],
    ) -> tuple[UUID, bool]:
        try:
            async with self.session_factory.begin() as session:
                execution = ExecutionRecord(
                    broker=broker.value,
                    workflow=workflow.value,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
                session.add(execution)
                await session.flush()
                for sequence, order in enumerate(orders):
                    session.add(
                        OrderRecord(
                            execution_id=execution.id,
                            sequence=sequence,
                            client_order_id=f"{execution.id.hex[:12]}-{sequence:03d}",
                            symbol=order.symbol,
                            exchange=order.exchange,
                            segment=order.segment,
                            isin=order.isin,
                            side=order.side.value,
                            quantity=order.quantity,
                            product=order.product,
                            order_type=order.order_type,
                            validity=order.validity,
                            price=order.price,
                        )
                    )
                return execution.id, True
        except IntegrityError:
            # The unique constraint is the final authority when concurrent requests
            # both observe a missing key. The loser reloads the committed winner.
            existing_id = await self.find_idempotent(idempotency_key, request_hash)
            if existing_id is None:
                raise
            return existing_id, False

    async def find_idempotent(
        self, idempotency_key: str, request_hash: str
    ) -> UUID | None:
        async with self.session_factory() as session:
            existing = await session.scalar(
                select(ExecutionRecord).where(
                    ExecutionRecord.idempotency_key == idempotency_key
                )
            )
            if existing is None:
                return None
            self._validate_request_hash(existing, request_hash)
            return existing.id

    @staticmethod
    def _validate_request_hash(
        existing: ExecutionRecord, request_hash: str
    ) -> None:
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError(
                "Idempotency-Key was already used with a different payload"
            )

    async def get_record(self, execution_id: UUID) -> ExecutionRecord | None:
        async with self.session_factory() as session:
            return await session.scalar(
                select(ExecutionRecord)
                .options(selectinload(ExecutionRecord.orders))
                .where(ExecutionRecord.id == execution_id)
            )

    async def set_execution_status(
        self,
        execution_id: UUID,
        status: ExecutionStatus,
        *,
        notification_status: str | None = None,
    ) -> None:
        async with self.session_factory.begin() as session:
            record = await session.get(ExecutionRecord, execution_id)
            if record is None:
                raise LookupError(execution_id)
            record.status = status.value
            record.updated_at = utc_now()
            if notification_status is not None:
                record.notification_status = notification_status

    async def set_notification_status(self, execution_id: UUID, status: str) -> None:
        async with self.session_factory.begin() as session:
            record = await session.get(ExecutionRecord, execution_id)
            if record is None:
                raise LookupError(execution_id)
            record.notification_status = status
            record.updated_at = utc_now()

    async def update_order(
        self,
        order_id: UUID,
        *,
        status: OrderStatus,
        broker_symbol: str | None = None,
        broker_token: str | None = None,
        broker_order_id: str | None = None,
        filled_quantity: int | None = None,
        average_price: Decimal | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        async with self.session_factory.begin() as session:
            record = await session.scalar(
                select(OrderRecord).where(OrderRecord.id == order_id).with_for_update()
            )
            if record is None:
                raise LookupError(order_id)
            validate_order_transition(OrderStatus(record.status), status)
            next_filled_quantity = (
                record.filled_quantity if filled_quantity is None else filled_quantity
            )
            if not 0 <= next_filled_quantity <= record.quantity:
                raise ValueError(
                    "filled_quantity must be between zero and requested quantity"
                )
            record.status = status.value
            record.updated_at = utc_now()
            if broker_symbol is not None:
                record.broker_symbol = broker_symbol
            if broker_token is not None:
                record.broker_token = broker_token
            if broker_order_id is not None:
                record.broker_order_id = broker_order_id
            if filled_quantity is not None:
                record.filled_quantity = filled_quantity
            if average_price is not None:
                record.average_price = average_price
            record.error_code = error_code
            record.error_message = error_message

    async def view(self, execution_id: UUID) -> ExecutionView | None:
        record = await self.get_record(execution_id)
        if record is None:
            return None
        return ExecutionView(
            id=record.id,
            broker=BrokerName(record.broker),
            workflow=Workflow(record.workflow),
            status=ExecutionStatus(record.status),
            notification_status=record.notification_status,
            created_at=record.created_at,
            updated_at=record.updated_at,
            orders=[
                OrderView(
                    id=order.id,
                    client_order_id=order.client_order_id,
                    symbol=order.symbol,
                    exchange=order.exchange,
                    side=Side(order.side),
                    quantity=order.quantity,
                    filled_quantity=order.filled_quantity,
                    status=OrderStatus(order.status),
                    broker_order_id=order.broker_order_id,
                    average_price=order.average_price,
                    error_code=order.error_code,
                    error_message=order.error_message,
                )
                for order in record.orders
            ],
        )


def create_engine_and_session(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory


async def create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
