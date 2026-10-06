"""add package total to promotions

Revision ID: 0003_promo_package_total
Revises: 0002_catalog_media
Create Date: 2026-10-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0003_promo_package_total"
down_revision: Union[str, None] = "0002_catalog_media"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "promocion",
        sa.Column("precio_total_promocional", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("promocion", "precio_total_promocional")
