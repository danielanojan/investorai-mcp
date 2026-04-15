from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column("chat_request_log", sa.Column("db_fetch_ms",   sa.Integer(), nullable=True))
    op.add_column("chat_request_log", sa.Column("llm_ms",        sa.Integer(), nullable=True))
    op.add_column("chat_request_log", sa.Column("validation_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_request_log", "validation_ms")
    op.drop_column("chat_request_log", "llm_ms")
    op.drop_column("chat_request_log", "db_fetch_ms")
