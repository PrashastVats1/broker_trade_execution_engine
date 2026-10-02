"""Create execution and order state tables.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("broker", sa.String(length=32), nullable=False),
        sa.Column("workflow", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("notification_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_executions_idempotency_key"),
        "executions",
        ["idempotency_key"],
        unique=True,
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("client_order_id", sa.String(length=30), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=8), nullable=False),
        sa.Column("segment", sa.String(length=16), nullable=False),
        sa.Column("isin", sa.String(length=16), nullable=True),
        sa.Column("broker_symbol", sa.String(length=64), nullable=True),
        sa.Column("broker_token", sa.String(length=128), nullable=True),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("filled_quantity", sa.Integer(), nullable=False),
        sa.Column("product", sa.String(length=16), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("validity", sa.String(length=8), nullable=False),
        sa.Column("price", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("average_price", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("broker_order_id", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_order_id"),
    )
    op.create_index(op.f("ix_orders_execution_id"), "orders", ["execution_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_orders_execution_id"), table_name="orders")
    op.drop_table("orders")
    op.drop_index(op.f("ix_executions_idempotency_key"), table_name="executions")
    op.drop_table("executions")
