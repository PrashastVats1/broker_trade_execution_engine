"""Enforce requested and filled quantity bounds.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_orders_quantity_positive",
        "orders",
        "quantity > 0",
    )
    op.create_check_constraint(
        "ck_orders_filled_quantity_bounds",
        "orders",
        "filled_quantity >= 0 AND filled_quantity <= quantity",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_orders_filled_quantity_bounds",
        "orders",
        type_="check",
    )
    op.drop_constraint(
        "ck_orders_quantity_positive",
        "orders",
        type_="check",
    )
