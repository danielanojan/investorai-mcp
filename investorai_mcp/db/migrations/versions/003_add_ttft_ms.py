from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "chat_request_log",
        sa.Column("ttft_ms", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_request_log", "ttft_ms")
