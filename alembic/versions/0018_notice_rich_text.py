"""Optional formatted content for public notices."""

from alembic import op
import sqlalchemy as sa

revision = "0018_notice_rich_text"
down_revision = "0017_public_notices"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("aviso_publico", sa.Column("mensaje_html", sa.String(20000), nullable=True))


def downgrade():
    op.drop_column("aviso_publico", "mensaje_html")
