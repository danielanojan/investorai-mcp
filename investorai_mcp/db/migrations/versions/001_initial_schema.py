from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[str, None] = None

def upgrade() -> None:
    # Enable foreign keys for SQLite
    op.execute("PRAGMA foreign_keys=ON")
    
    # ── tickers ──────────────────────────────────────────────────────────
    op.create_table(
        "tickers",
        sa.Column("symbol",             sa.String(),  nullable=False),
        sa.Column("name",               sa.String(),  nullable=False),
        sa.Column("sector",             sa.String(),  nullable=False),
        sa.Column("exchange",           sa.String(),  nullable=False),
        sa.Column("market_cap",         sa.Float(),   nullable=True),
        sa.Column("shares_outstanding", sa.Integer(), nullable=True),
        sa.Column("currency",           sa.String(),  nullable=False, server_default="USD"),
        sa.Column("is_supported",       sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("last_updated",       sa.DateTime(), nullable=True),
        sa.Column("created_at",         sa.DateTime(), nullable=False,
                  server_default=sa.text("(datetime('now'))")),
        sa.PrimaryKeyConstraint("symbol"),
    )
    op.create_index("idx_tickers_sector", "tickers", ["sector"])
 
    # ── price_history ─────────────────────────────────────────────────────
    op.create_table(
        "price_history",
        sa.Column("id",           sa.Integer(),  nullable=False, autoincrement=True),
        sa.Column("symbol",       sa.String(),   nullable=False),
        sa.Column("date",         sa.Date(),     nullable=False),
        sa.Column("open",         sa.Float(),    nullable=False),
        sa.Column("high",         sa.Float(),    nullable=False),
        sa.Column("low",          sa.Float(),    nullable=False),
        sa.Column("close",        sa.Float(),    nullable=False),
        sa.Column("adj_close",    sa.Float(),    nullable=False),
        sa.Column("avg_price",    sa.Float(),    nullable=False),
        sa.Column("volume",       sa.Integer(),  nullable=False),
        sa.Column("split_factor", sa.Float(),    nullable=False, server_default="1.0"),
        sa.Column("fetched_at",   sa.DateTime(), nullable=False,
                  server_default=sa.text("(datetime('now'))")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["symbol"], ["tickers.symbol"], ondelete="CASCADE"),
        sa.UniqueConstraint("symbol", "date", name="uq_price_history_symbol_date"),
        sa.CheckConstraint("open > 0",      name="ck_ph_open_positive"),
        sa.CheckConstraint("adj_close > 0", name="ck_ph_adj_close_positive"),
        sa.CheckConstraint("close > 0",     name="ck_ph_close_positive"),
        sa.CheckConstraint("volume >= 0",   name="ck_ph_volume_non_negative"),
    )
    op.create_index("idx_ph_symbol_date", "price_history", ["symbol", "date"])
 
    # ── news_articles ─────────────────────────────────────────────────────
    op.create_table(
        "news_articles",
        sa.Column("id",              sa.Integer(),  nullable=False, autoincrement=True),
        sa.Column("symbol",          sa.String(),   nullable=False),
        sa.Column("headline",        sa.String(),   nullable=False),
        sa.Column("source",          sa.String(),   nullable=False),
        sa.Column("url",             sa.Text(),     nullable=False),
        sa.Column("ai_summary",      sa.Text(),     nullable=True),
        sa.Column("sentiment_score", sa.Integer(),  nullable=True),
        sa.Column("published_at",    sa.DateTime(), nullable=False),
        sa.Column("fetched_at",      sa.DateTime(), nullable=False,
                  server_default=sa.text("(datetime('now'))")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["symbol"], ["tickers.symbol"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "sentiment_score >= -1 AND sentiment_score <= 1",
            name="ck_news_sentiment_range",
        ),
    )
    op.create_index(
        "idx_news_symbol_published", "news_articles", ["symbol", "published_at"]
    )
 
    # ── cache_metadata ────────────────────────────────────────────────────
    op.create_table(
        "cache_metadata",
        sa.Column("id",           sa.Integer(),  nullable=False, autoincrement=True),
        sa.Column("symbol",       sa.String(),   nullable=False),
        sa.Column("data_type",    sa.String(),   nullable=False),
        sa.Column("last_fetched", sa.DateTime(), nullable=True),
        sa.Column("ttl_seconds",  sa.Integer(),  nullable=False),
        sa.Column("is_stale",     sa.Boolean(),  nullable=False, server_default="1"),
        sa.Column("fetch_count",  sa.Integer(),  nullable=False, server_default="0"),
        sa.Column("error_count",  sa.Integer(),  nullable=False, server_default="0"),
        sa.Column("provider_used",sa.String(),   nullable=True),
        sa.Column("updated_at",   sa.DateTime(), nullable=False,
                  server_default=sa.text("(datetime('now'))")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["symbol"], ["tickers.symbol"], ondelete="CASCADE"),
        sa.UniqueConstraint("symbol", "data_type", name="uq_cache_symbol_data_type"),
        sa.CheckConstraint(
            "data_type IN ('price_history', 'news', 'ticker_info', 'sentiment')",
            name="ck_cache_data_type_valid",
        ),
        sa.CheckConstraint("ttl_seconds > 0", name="ck_cache_ttl_positive"),
    )
 
    # ── eval_log ──────────────────────────────────────────────────────────
    op.create_table(
        "eval_log",
        sa.Column("id",             sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("query_id",       sa.String(),  nullable=False),
        sa.Column("symbol",         sa.String(),  nullable=True),
        sa.Column("question",       sa.Text(),    nullable=False),
        sa.Column("ai_answer",      sa.Text(),    nullable=False),
        sa.Column("ground_truth",   sa.Text(),    nullable=True),
        sa.Column("pass_fail",      sa.String(),  nullable=False),
        sa.Column("deviation_pct",  sa.Float(),   nullable=True),
        sa.Column("violation_json", sa.Text(),    nullable=True),
        sa.Column("reviewed_by",    sa.String(),  nullable=True),
        sa.Column("source",         sa.String(),  nullable=False, server_default="live"),
        sa.Column("ts",             sa.DateTime(), nullable=False,
                  server_default=sa.text("(datetime('now'))")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["symbol"], ["tickers.symbol"]),
        sa.UniqueConstraint("query_id", name="uq_eval_query_id"),
        sa.CheckConstraint(
            "pass_fail IN ('PASS', 'FAIL', 'SKIP')",
            name="ck_eval_pass_fail_valid",
        ),
        sa.CheckConstraint(
            "source IN ('live', 'eval_suite')",
            name="ck_eval_source_valid",
        ),
    )
    op.create_index("idx_eval_query_id", "eval_log", ["query_id"])
    op.create_index("idx_eval_ts",       "eval_log", ["ts"])
 
    # ── llm_usage_log ─────────────────────────────────────────────────────
    op.create_table(
        "llm_usage_log",
        sa.Column("id",           sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("session_hash", sa.String(),  nullable=False),
        sa.Column("provider",     sa.String(),  nullable=False),
        sa.Column("model",        sa.String(),  nullable=False),
        sa.Column("tool_name",    sa.String(),  nullable=True),
        sa.Column("tokens_in",    sa.Integer(), nullable=False),
        sa.Column("tokens_out",   sa.Integer(), nullable=False),
        sa.Column("latency_ms",   sa.Integer(), nullable=True),
        sa.Column("status",       sa.String(),  nullable=False),
        sa.Column("ts",           sa.DateTime(), nullable=False,
                  server_default=sa.text("(datetime('now'))")),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("tokens_in >= 0",  name="ck_llm_tokens_in_non_negative"),
        sa.CheckConstraint("tokens_out >= 0", name="ck_llm_tokens_out_non_negative"),
        sa.CheckConstraint(
            "status IN ('success', 'error', 'rate_limited', 'timeout')",
            name="ck_llm_status_valid",
        ),
    )
    op.create_index("idx_llm_session", "llm_usage_log", ["session_hash"])
    op.create_index("idx_llm_ts",      "llm_usage_log", ["ts"])
 
    # ── SQLite pragmas ────────────────────────────────────────────────────
    op.execute("PRAGMA journal_mode=WAL")
    op.execute("PRAGMA foreign_keys=ON")
 
 
def downgrade() -> None:
    op.drop_table("llm_usage_log")
    op.drop_table("eval_log")
    op.drop_table("cache_metadata")
    op.drop_table("news_articles")
    op.drop_table("price_history")
    op.drop_table("tickers")