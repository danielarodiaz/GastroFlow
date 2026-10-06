"""add app config

Revision ID: 0004_app_config
Revises: 0003_promo_package_total
Create Date: 2026-10-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0004_app_config"
down_revision: Union[str, None] = "0003_promo_package_total"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_config",
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", sa.String(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_app_config_key", "app_config", ["key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_app_config_key", table_name="app_config")
    op.drop_table("app_config")
