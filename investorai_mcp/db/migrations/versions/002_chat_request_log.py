from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "chat_request_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False, server_default=sa.text("(datetime('now'))")),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("symbols", sa.String(), nullable=False),
        sa.Column("range", sa.String(4), nullable=False),
        sa.Column("total_latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="success"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('success', 'error')", name="ck_chat_req_status"),
    )
    op.create_index("idx_chat_req_ts", "chat_request_log", ["ts"])
    op.create_index("idx_chat_req_latency", "chat_request_log", ["total_latency_ms"])


def downgrade() -> None:
    op.drop_index("idx_chat_req_latency", table_name="chat_request_log")
    op.drop_index("idx_chat_req_ts", table_name="chat_request_log")
    op.drop_table("chat_request_log")
